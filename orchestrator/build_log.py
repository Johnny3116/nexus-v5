"""build_log.py — append-only JSON build log in workspace/build_log.json.

Each entry records: timestamp, goal, plan_id, files written,
verification result, and builder used. Never modifies existing entries.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

_NEXUS_ROOT = Path(__file__).resolve().parents[1]
_LOG_PATH = _NEXUS_ROOT / "workspace" / "build_log.json"


def append_entry(
    plan_id: str,
    goal: str,
    builder_used: str,
    written_files: list[str],
    verify_result: dict,
    build_error: str | None = None,
) -> None:
    """Append one build record to build_log.json. Silently logs errors."""
    try:
        _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        existing: list[dict] = []
        if _LOG_PATH.exists():
            try:
                existing = json.loads(_LOG_PATH.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                existing = []

        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "plan_id": plan_id,
            "goal": goal,
            "builder": builder_used,
            "files": written_files,
            "verify_passed": verify_result.get("passed", False),
            "verify_summary": verify_result.get("summary", ""),
            "error": build_error,
        }
        existing.append(entry)
        _LOG_PATH.write_text(json.dumps(existing, indent=2), encoding="utf-8")
        logger.info("Build log updated: %d entries", len(existing))
    except Exception as exc:
        logger.error("build_log.append_entry failed: %s", exc)


def recent(n: int = 10) -> list[dict]:
    """Return the n most recent build log entries."""
    try:
        if not _LOG_PATH.exists():
            return []
        entries = json.loads(_LOG_PATH.read_text(encoding="utf-8"))
        return entries[-n:]
    except Exception:
        return []


def get_by_plan_id(plan_id: str) -> dict | None:
    """Return the build log entry for the given plan_id, or None if not found."""
    try:
        if not _LOG_PATH.exists():
            return None
        entries = json.loads(_LOG_PATH.read_text(encoding="utf-8"))
        for entry in reversed(entries):
            if entry.get("plan_id") == plan_id:
                return entry
        return None
    except Exception:
        return None
