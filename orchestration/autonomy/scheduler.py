"""Cron scheduler — fires tasks on schedule using croniter.

Loads tasks from `autonomy/config/scheduled_tasks.yaml`. Each task has a
cron expression and either a skill invocation or a brain prompt.

Tick-driven: the caller (heartbeat loop or api_gateway background task)
calls `tick()` every minute. Scheduler checks which tasks are due and
fires them.

Phase 5 wiring: when the agentic loop exists, `loop_runner` plugs in.
Until then, tasks that need skill execution are logged but not run.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Coroutine, Optional

import yaml

from safety.output_filters.safety_tier_gate import TaskSource

logger = logging.getLogger("nexus.orchestration.autonomy.scheduler")

_CRONITER_AVAILABLE = False
try:
    from croniter import croniter
    _CRONITER_AVAILABLE = True
except ImportError:
    logger.info("croniter not installed — scheduler will not fire time-based tasks")

_CONFIG_DIR = Path(__file__).resolve().parent / "config"
_TASKS_PATH = _CONFIG_DIR / "scheduled_tasks.yaml"
_EXAMPLE_PATH = _CONFIG_DIR / "scheduled_tasks.example.yaml"

# Type for the agentic loop runner (phase 5 plug-in point).
LoopRunner = Callable[..., Coroutine[Any, Any, dict]]


class ScheduledTask:
    def __init__(self, raw: dict) -> None:
        self.name: str = raw["name"]
        self.schedule: str = raw["schedule"]
        self.skill: Optional[str] = raw.get("skill")
        self.action: Optional[str] = raw.get("action")
        self.params: dict[str, Any] = raw.get("params", {})
        self.prompt: Optional[str] = raw.get("prompt")
        self.enabled: bool = raw.get("enabled", True)
        self.last_run: Optional[datetime] = None

    def next_run(self) -> Optional[datetime]:
        if not _CRONITER_AVAILABLE:
            return None
        try:
            return croniter(self.schedule, datetime.now(timezone.utc)).get_next(datetime)
        except Exception:
            return None

    def is_due(self) -> bool:
        if not self.enabled or not _CRONITER_AVAILABLE:
            return False
        try:
            now = datetime.now(timezone.utc)
            prev = croniter(self.schedule, now).get_prev(datetime)
            return 0 <= (now - prev).total_seconds() < 60
        except Exception:
            return False

    def to_dict(self) -> dict:
        nxt = self.next_run()
        return {
            "name": self.name, "schedule": self.schedule,
            "skill": self.skill, "action": self.action,
            "prompt": self.prompt, "enabled": self.enabled,
            "last_run": self.last_run.isoformat() if self.last_run else None,
            "next_run": nxt.isoformat() if nxt else None,
        }


class Scheduler:
    def __init__(
        self,
        loop_runner: Optional[LoopRunner] = None,
        tasks_path: Optional[Path] = None,
    ) -> None:
        self._tasks: list[ScheduledTask] = []
        self._loop_runner = loop_runner
        self._tasks_path = tasks_path or (_TASKS_PATH if _TASKS_PATH.exists() else _EXAMPLE_PATH)

    def load(self) -> int:
        if not self._tasks_path.exists():
            logger.info("no scheduled tasks at %s", self._tasks_path)
            return 0
        try:
            with self._tasks_path.open("r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            self._tasks = [ScheduledTask(t) for t in data.get("tasks", [])]
            enabled = sum(1 for t in self._tasks if t.enabled)
            logger.info("scheduler: loaded %d tasks (%d enabled)", len(self._tasks), enabled)
            return len(self._tasks)
        except Exception as exc:
            logger.error("scheduler load failed: %s", exc)
            return 0

    def reload(self) -> int:
        self._tasks.clear()
        return self.load()

    async def tick(self) -> list[dict]:
        """Check for due tasks and fire them. Returns list of results."""
        results: list[dict] = []
        for task in self._tasks:
            if not task.is_due():
                continue
            logger.info("scheduler firing '%s' (schedule: %s)", task.name, task.schedule)
            task.last_run = datetime.now(timezone.utc)

            result = await self._fire_task(task)
            await self._write_audit(task, result)
            results.append({"task": task.name, "result": result})
        return results

    async def _fire_task(self, task: ScheduledTask) -> dict:
        if self._loop_runner:
            message = self._build_message(task)
            try:
                return await self._loop_runner(
                    message=message,
                    source=TaskSource.CRON,
                )
            except Exception as exc:
                logger.error("scheduler task '%s' failed: %s", task.name, exc)
                return {"success": False, "error": str(exc)}

        # No loop runner yet (phase 5).
        logger.info("scheduler: no loop_runner — task '%s' logged but not executed", task.name)
        return {"success": False, "reason": "no_loop_runner"}

    async def _write_audit(self, task: ScheduledTask, result: dict) -> None:
        try:
            from kv_cache.cold.supabase_client import get_supabase
            client = get_supabase()
            client.table("automation_history").insert({
                "task_name": f"scheduler:{task.name}",
                "source": "cron",
                "result": "ok" if result.get("success") else "failed",
                "tier": "NON_DESTRUCTIVE",
                "params": {"schedule": task.schedule, "result_excerpt": str(result)[:500]},
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }).execute()
        except Exception as exc:
            logger.debug("scheduler audit write failed: %s", exc)

    @staticmethod
    def _build_message(task: ScheduledTask) -> str:
        if task.prompt:
            return task.prompt
        if task.skill:
            return f'<nexus_task><skill>{task.skill}</skill><action>{task.action or "run"}</action></nexus_task>'
        return f"Run scheduled task: {task.name}"

    async def start_background_loop(self, interval_seconds: int = 60) -> None:
        logger.info("scheduler background loop started (interval=%ds)", interval_seconds)
        while True:
            await asyncio.sleep(interval_seconds)
            try:
                await self.tick()
            except Exception as exc:
                logger.error("scheduler tick error: %s", exc, exc_info=True)

    def list_tasks(self) -> list[dict]:
        return [t.to_dict() for t in self._tasks]

    def status(self) -> dict:
        return {
            "tasks_total": len(self._tasks),
            "tasks_enabled": sum(1 for t in self._tasks if t.enabled),
            "croniter_available": _CRONITER_AVAILABLE,
            "loop_runner_configured": self._loop_runner is not None,
        }
