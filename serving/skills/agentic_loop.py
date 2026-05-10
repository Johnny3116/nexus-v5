"""Agentic execution loop — Brain → parse → execute → observe cycle.

Max 6 iterations. Each iteration:
  1. Send accumulated message to Brain (via BrainPool)
  2. Parse <nexus_task> blocks from response
  3. Safety-check each task → approve or execute
  4. Collect observations
  5. If Brain signals completion or cap hit → return

Sources route to different providers:
  HUMAN     → BrainPool with task_type from request
  CRON      → BrainPool with task_type="local" (Qwen)
  HEARTBEAT → BrainPool with task_type="heartbeat" (Qwen)
  REFLEX    → Direct skill execution (no Brain call)
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from safety.output_filters.doctrine_enforcer import (
    DoctrineViolation,
    ProposedAction,
    enforce as doctrine_enforce,
)
from safety.output_filters.safety_tier_gate import TaskSource, requires_approval
from serving.skills.execution_context import ExecutionContext
from serving.skills.skill_manager import SkillManager
from serving.skills.task_parser import parse_tasks

logger = logging.getLogger("nexus.skills.agentic_loop")

MAX_ITERATIONS = 6

_SOURCE_TO_TASK_TYPE = {
    TaskSource.HUMAN: "chat",
    TaskSource.CRON: "local",
    TaskSource.HEARTBEAT: "heartbeat",
    TaskSource.REFLEX: "local",
    TaskSource.AUTOMATION: "local",
}


class AgenticLoop:
    def __init__(
        self,
        skill_manager: SkillManager,
        approval_queue: Optional[Any] = None,
    ) -> None:
        self._skills = skill_manager
        self._approval_queue = approval_queue

    async def run(
        self,
        message: str,
        source: TaskSource = TaskSource.HUMAN,
        conversation_id: Optional[str] = None,
        max_iterations: int = MAX_ITERATIONS,
    ) -> dict[str, Any]:
        request_id = str(uuid.uuid4())
        cap = min(max_iterations, MAX_ITERATIONS)
        tasks_executed: list[dict] = []
        iteration = 0
        accumulated = message
        final_response = ""

        logger.info("loop START id=%s source=%s", request_id, source.value)

        try:
            while iteration < cap:
                iteration += 1

                brain_result = await self._call_brain(accumulated, source, conversation_id)
                brain_text = brain_result.get("response", brain_result.get("content", ""))
                final_response = brain_text

                raw_tasks = parse_tasks(brain_text)
                if not raw_tasks:
                    break

                observations: list[str] = []
                for raw in raw_tasks:
                    result = await self._execute_task(raw, source, request_id, iteration, conversation_id)
                    tasks_executed.append({**raw, "result": result})
                    observations.append(self._format_obs(raw, result))

                if not observations:
                    break

                accumulated = (
                    f"{accumulated}\n\n"
                    f"[iteration {iteration} results]\n" + "\n".join(observations) +
                    "\n\nContinue or provide a final response."
                )

            await self._write_audit(request_id, source, tasks_executed, iteration)

            return {
                "response": final_response,
                "tasks_executed": tasks_executed,
                "iterations": iteration,
                "source": source.value,
                "request_id": request_id,
                "success": True,
            }
        except Exception as exc:
            logger.error("loop FATAL id=%s: %s", request_id, exc, exc_info=True)
            return {
                "response": "", "tasks_executed": tasks_executed,
                "iterations": iteration, "source": source.value,
                "request_id": request_id, "success": False, "error": str(exc),
            }

    async def _execute_task(self, raw: dict, source: TaskSource, request_id: str, iteration: int, conv_id: Optional[str]) -> dict:
        skill_name, action, params = raw["skill"], raw["action"], raw.get("params", {})

        skill = self._skills.get(skill_name)
        if skill is None:
            return {"success": False, "error": f"skill '{skill_name}' not found"}

        if requires_approval(skill.safety_tier, source):
            if self._approval_queue:
                qid = await self._approval_queue.enqueue(skill_name=skill_name, action=action, params=params, source=source, request_id=request_id)
                return {"success": False, "queued": True, "approval_id": qid}
            return {"success": False, "error": "requires approval but no queue configured"}

        valid, err = skill.validate_params(params)
        if not valid:
            return {"success": False, "error": f"invalid params: {err}"}

        # Doctrine gate — hard fail on §1/§2/§5 violations before execute.
        try:
            doctrine_enforce(ProposedAction(skill=skill_name, action=action, params=params))
        except DoctrineViolation as exc:
            logger.warning("doctrine violation: %s", exc)
            return {"success": False, "error": str(exc), "doctrine_violation": exc.rule}

        ctx = ExecutionContext(
            skill_name=skill_name, action=action, params=params,
            source=source, iteration=iteration,
            conversation_id=conv_id, request_id=request_id,
        )

        start = datetime.now(timezone.utc)
        try:
            result = await skill.execute(ctx)
            result.setdefault("success", True)
            result["elapsed_s"] = (datetime.now(timezone.utc) - start).total_seconds()
            return result
        except Exception as exc:
            return {"success": False, "error": str(exc), "elapsed_s": (datetime.now(timezone.utc) - start).total_seconds()}

    async def _call_brain(self, message: str, source: TaskSource, conv_id: Optional[str]) -> dict:
        from serving.brain_pool.brain_pool import get_brain_pool
        pool = get_brain_pool()
        task_type = _SOURCE_TO_TASK_TYPE.get(source, "chat")
        system_prompt = self._build_task_system_prompt(task_type)
        return await pool.chat(
            message,
            task_type=task_type,
            system_prompt=system_prompt,
            conversation_id=conv_id,
        )

    def _build_task_system_prompt(self, task_type: str) -> str:
        """Compose a task-mode system prompt: soul + skill manifest + XML contract.

        Small local models (phi4-mini) won't invent the <nexus_task> syntax —
        they have to see it. Keep the prompt short and example-driven.
        """
        parts: list[str] = []
        try:
            from safety.identity.soul_container import get_identity_block
            parts.append(get_identity_block(task_type))
        except Exception:
            parts.append("You are Nexus, a personal AI assistant.")

        # Skill manifest, grouped by skill for readability.
        caps = self._skills.list_capabilities()
        by_skill: dict[str, list[dict]] = {}
        for cap in caps:
            by_skill.setdefault(cap["skill"], []).append(cap)

        lines = ["\n## Available Skills", "Emit <nexus_task> blocks to run these. Pick only when the user needs live data."]
        for name, actions in by_skill.items():
            tier = actions[0].get("safety_tier", "?")
            lines.append(f"\n**{name}** ({tier})")
            for a in actions:
                lines.append(f"  - `{a['action']}` — {a.get('description', '')}")
        parts.append("\n".join(lines))

        parts.append(
            "\n## Tool-Use Contract\n"
            "To execute a skill, output a block exactly like this (and nothing extra inside it):\n"
            "```\n"
            "<nexus_task skill=\"system_monitor\" action=\"check_resources\" />\n"
            "```\n"
            "With params:\n"
            "```\n"
            "<nexus_task skill=\"file_ops\" action=\"read\">\n"
            "  <param name=\"path\">C:\\\\Users\\\\Nexus\\\\notes.md</param>\n"
            "</nexus_task>\n"
            "```\n"
            "Rules:\n"
            "- Only emit a task when live data / an action is required. Normal chat = reply directly, no task block.\n"
            "- After a task runs you'll see `[iteration N results]` — use those results to answer. Do NOT re-emit the same task.\n"
            "- When you have the answer, reply in plain text with no <nexus_task> blocks — that ends the loop."
        )
        return "\n".join(parts)

    async def _write_audit(self, request_id: str, source: TaskSource, tasks: list[dict], iterations: int) -> None:
        try:
            from kv_cache.cold.supabase_client import get_supabase
            success = bool(tasks) and all(t.get("result", {}).get("success") for t in tasks)
            get_supabase().table("automation_runs").insert({
                "task_id": f"agentic_loop:{request_id[:8]}",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "success": success,
                "result": {
                    "source": source.value,
                    "iterations": iterations,
                    "tasks_count": len(tasks),
                    "tasks": [{"skill": t.get("skill"), "action": t.get("action"),
                               "ok": t.get("result", {}).get("success", False)} for t in tasks],
                },
                "error": None,
            }).execute()
        except Exception as exc:
            logger.debug("audit write skipped: %s", exc)

    @staticmethod
    def _format_obs(task: dict, result: dict) -> str:
        s, a = task["skill"], task["action"]
        if result.get("success"):
            return f"[{s}.{a}] SUCCESS"
        if result.get("queued"):
            return f"[{s}.{a}] QUEUED for approval (id={result.get('approval_id')})"
        return f"[{s}.{a}] FAILED: {result.get('error', '?')}"
