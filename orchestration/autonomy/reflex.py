"""Reflex engine — deterministic rule evaluator, no LLM involved.

Loads YAML rules from `autonomy/config/reflexes.yaml`. Each rule has a
condition expression evaluated against a live state snapshot and fires an
action when the condition is true and the cooldown has expired.

Runs at two points:
  1. Top of every user request (via api_gateway middleware — phase 5)
  2. Every automation tick (via scheduler)

The state snapshot is built from sensors already in place:
  - gpu_watch.sample() → gpu_temp_c, gpu_vram_pct
  - brain_cost_tracker.today_spend() → claude_spend_usd, claude_budget_pct
  - psutil (if available) → cpu_pct, ram_pct, disk_pct

Actions today:
  - "alert:<severity>" → fires observability alerting
  - "budget:claude_over_budget" → flips BrainPool budget flag
  - "skill:<name>:<action>" → deferred to phase 5 (skills engine)

Security: rules are YAML on disk. NOT from user input, LLM output, or
Supabase. eval() runs in a restricted namespace.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import yaml

from observability.alerting.discord_notifier import Alert, Severity, send_alert
from observability.alerting import telegram_alerts

logger = logging.getLogger("nexus.orchestration.autonomy.reflex")

_DEFAULT_COOLDOWN = 300
_CONFIG_DIR = Path(__file__).resolve().parent / "config"
_RULES_PATH = _CONFIG_DIR / "reflexes.yaml"
_EXAMPLE_PATH = _CONFIG_DIR / "reflexes.example.yaml"


class ReflexRule:
    def __init__(self, raw: dict) -> None:
        self.name: str = raw["name"]
        self.condition: str = raw["condition"]
        self.action: str = raw["action"]
        self.notify: bool = raw.get("notify", False)
        self.cooldown: int = raw.get("cooldown", _DEFAULT_COOLDOWN)
        self.enabled: bool = raw.get("enabled", True)
        self._last_fired: float = 0.0

    def is_ready(self) -> bool:
        return self.enabled and (time.monotonic() - self._last_fired) >= self.cooldown

    def mark_fired(self) -> None:
        self._last_fired = time.monotonic()

    def evaluate(self, state: dict[str, Any]) -> bool:
        safe_builtins = {"abs": abs, "min": min, "max": max, "len": len, "bool": bool}
        try:
            return bool(eval(self.condition, {"__builtins__": safe_builtins}, state))  # noqa: S307
        except Exception as exc:
            logger.warning("reflex '%s' eval error: %s", self.name, exc)
            return False


class ReflexEngine:
    def __init__(self, rules_path: Optional[Path] = None) -> None:
        self._rules: list[ReflexRule] = []
        self._rules_path = rules_path or (_RULES_PATH if _RULES_PATH.exists() else _EXAMPLE_PATH)

    def load(self) -> int:
        if not self._rules_path.exists():
            logger.info("no reflex rules at %s", self._rules_path)
            return 0
        try:
            with self._rules_path.open("r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            self._rules = [ReflexRule(r) for r in data.get("rules", [])]
            enabled = sum(1 for r in self._rules if r.enabled)
            logger.info("reflex: loaded %d rules (%d enabled)", len(self._rules), enabled)
            return len(self._rules)
        except Exception as exc:
            logger.error("reflex load failed: %s", exc)
            return 0

    def reload(self) -> int:
        self._rules.clear()
        return self.load()

    async def evaluate(self, state: dict[str, Any]) -> list[dict]:
        """Evaluate all ready rules. Returns list of fired results."""
        fired: list[dict] = []
        for rule in self._rules:
            if not rule.is_ready() or not rule.evaluate(state):
                continue
            logger.info("reflex '%s' triggered", rule.name)
            rule.mark_fired()

            result = await self._execute_action(rule, state)
            await self._write_audit(rule, result)

            if rule.notify:
                await self._notify(rule, result)

            fired.append({"rule": rule.name, "action": rule.action, "result": result})
        return fired

    async def _execute_action(self, rule: ReflexRule, state: dict[str, Any]) -> dict:
        action = rule.action

        # alert:<severity>
        if action.startswith("alert:"):
            severity_str = action.split(":", 1)[1]
            try:
                severity = Severity(severity_str)
            except ValueError:
                severity = Severity.WARN
            await send_alert(Alert(
                severity=severity,
                title=f"Reflex: {rule.name}",
                detail=f"Condition `{rule.condition}` matched",
                source="reflex_engine",
            ))
            if severity in (Severity.CRITICAL, Severity.EMERGENCY):
                await telegram_alerts.send_alert(severity, f"Reflex: {rule.name}", rule.condition)
            return {"action": "alert", "severity": severity.value}

        # budget:claude_over_budget
        if action == "budget:claude_over_budget":
            try:
                from serving.brain_pool.brain_pool import get_brain_pool
                get_brain_pool().set_claude_over_budget(True)
                return {"action": "budget_override", "claude_over_budget": True}
            except Exception as exc:
                return {"action": "budget_override", "error": str(exc)}

        # skill:<name>:<action> — phase 5 stub
        if action.startswith("skill:"):
            logger.info("reflex skill action deferred (phase 5): %s", action)
            return {"action": "skill_deferred", "raw": action}

        return {"action": "unknown", "raw": action}

    async def _write_audit(self, rule: ReflexRule, result: dict) -> None:
        """Doctrine 7: every autonomous action writes to automation_history."""
        try:
            from kv_cache.cold.supabase_client import get_supabase
            client = get_supabase()
            client.table("automation_history").insert({
                "task_name": f"reflex:{rule.name}",
                "source": "reflex",
                "result": "ok",
                "tier": "READ_ONLY",
                "params": {"condition": rule.condition, "action": rule.action, "result": result},
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }).execute()
        except Exception as exc:
            logger.debug("automation_history write failed: %s", exc)

    async def _notify(self, rule: ReflexRule, result: dict) -> None:
        await send_alert(Alert(
            severity=Severity.INFO,
            title=f"Reflex fired: {rule.name}",
            detail=f"Action: `{rule.action}`\nResult: {result}",
            source="reflex_engine",
        ))

    def list_rules(self) -> list[dict]:
        return [
            {"name": r.name, "condition": r.condition, "action": r.action,
             "enabled": r.enabled, "cooldown": r.cooldown, "ready": r.is_ready()}
            for r in self._rules
        ]


async def gather_state() -> dict[str, Any]:
    """Build the state snapshot that reflex rules evaluate against."""
    state: dict[str, Any] = {}

    # GPU sensor
    try:
        from observability.metrics.gpu_watch import sample
        s = sample()
        if s:
            state["gpu_temp_c"] = s.temp_c
            state["gpu_vram_pct"] = s.vram_pct
            state["gpu_util_pct"] = s.util_pct
            state["gpu_power_w"] = s.power_w
    except Exception:
        pass

    # Claude budget
    try:
        from observability.metrics.brain_cost_tracker import today_spend
        from api_gateway.config.settings import get_settings
        settings = get_settings()
        spent = await today_spend("claude")
        cap = settings.claude_daily_budget_usd
        state["claude_spend_usd"] = spent
        state["claude_budget_pct"] = (spent / cap * 100) if cap > 0 else 0
    except Exception:
        pass

    # System resources (best-effort)
    try:
        import psutil
        state["cpu_pct"] = psutil.cpu_percent(interval=0.1)
        state["ram_pct"] = psutil.virtual_memory().percent
        state["disk_pct"] = psutil.disk_usage("C:\\").percent
    except ImportError:
        pass

    return state
