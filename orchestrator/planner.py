"""Planner — generates a structured Plan from a TaskPacket using local Ollama.

Pipeline position:
    router.py → task_packet.py → planner.py → Plan dict → WS response

Milestone 2 rules:
    - No file writes
    - No Codex calls
    - No Sonnet calls
    - No MCP calls
    - No shell execution
    - requires_user_approval is always True
"""

from __future__ import annotations

import json
import logging
import os

import httpx

from .plan_prompt import SYSTEM_PROMPT, build_planning_prompt

logger = logging.getLogger(__name__)

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5-coder:7b")

_SAFE_DEFAULTS: dict = {
    "summary": "Plan generation failed — see planner_error for details.",
    "assumptions": [],
    "target_files": [],
    "implementation_steps": [],
    "risks": ["Plan generation failed; manual review required before proceeding."],
    "rollback_plan": "No changes were made.",
    "acceptance_tests": [],
    "verification_commands": [],
    "requires_user_approval": True,
}

_LIST_KEYS = (
    "assumptions",
    "target_files",
    "implementation_steps",
    "risks",
    "acceptance_tests",
    "verification_commands",
)


def _strip_fences(text: str) -> str:
    """Remove markdown code fences that some model versions emit in JSON mode."""
    text = text.strip()
    if text.startswith("```"):
        # Drop the opening fence line (```json or ```)
        text = text.split("\n", 1)[-1]
    if text.endswith("```"):
        text = text.rsplit("```", 1)[0]
    return text.strip()


def _coerce(raw: dict) -> dict:
    """Merge raw LLM output with safe defaults and enforce invariants."""
    plan = {**_SAFE_DEFAULTS, **raw}
    # Hard invariant: user must always approve before a builder runs.
    plan["requires_user_approval"] = True
    # Coerce list fields — model occasionally returns a string instead of list.
    for key in _LIST_KEYS:
        if not isinstance(plan[key], list):
            plan[key] = [str(plan[key])] if plan[key] else []
    # Coerce string fields
    if not isinstance(plan.get("summary"), str):
        plan["summary"] = str(plan.get("summary", ""))
    if not isinstance(plan.get("rollback_plan"), str):
        plan["rollback_plan"] = str(plan.get("rollback_plan", ""))
    return plan


async def generate_plan(task_packet: dict) -> dict:
    """Generate a Plan dict from a TaskPacket dict.

    Calls Ollama with format=json and temperature=0.1 for stable structured
    output. Always returns a complete dict — on any failure, returns safe
    defaults so the caller can still send a useful WS response.

    Raises on network errors so the caller can handle them and include a
    planner_error field in the WS response.
    """
    user_message = build_planning_prompt(task_packet)

    payload = {
        "model": OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
        "stream": False,
        "options": {
            "temperature": 0.1,
            "num_predict": 800,
        },
        "keep_alive": -1,
        "format": "json",
    }

    async with httpx.AsyncClient(timeout=httpx.Timeout(90.0, connect=5.0)) as client:
        resp = await client.post(f"{OLLAMA_URL}/api/chat", json=payload)
        resp.raise_for_status()
        data = resp.json()

    raw_text = data.get("message", {}).get("content", "").strip()
    if not raw_text:
        raise ValueError("Ollama returned an empty plan response")

    raw_text = _strip_fences(raw_text)
    plan_dict = json.loads(raw_text)
    logger.info(
        "Plan generated: %d steps, %d target files, approval_required=%s",
        len(plan_dict.get("implementation_steps", [])),
        len(plan_dict.get("target_files", [])),
        plan_dict.get("requires_user_approval", True),
    )
    return _coerce(plan_dict)
