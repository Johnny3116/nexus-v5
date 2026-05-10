"""events/supabase_subscriber.py — Supabase automation_runs logging.

Inserts a row into automation_runs for every completed build so the full
build history is queryable from outside the server process.

Environment:
  SUPABASE_URL — Supabase project REST URL (https://<ref>.supabase.co)
  SUPABASE_KEY — Supabase service_role or anon key
  SUPABASE_ENABLED — set to "false" to disable (default: enabled if creds present)

Table: public.automation_runs
  task_id          text    — "nexus_v5_build:{plan_id}"
  success          bool    — build result
  result           jsonb   — full event data snapshot
  error            text    — error message if failed (null on success)
  timestamp / created_at — auto-set by DB default
"""

from __future__ import annotations

import logging
import os

import httpx

from events.event_types import Event, EventType
from events.event_bus import subscribe

logger = logging.getLogger(__name__)

_TABLE = "automation_runs"


def _creds() -> tuple[str, str]:
    """Return (url, key) from environment. Both must be non-empty to be usable."""
    url = os.getenv("SUPABASE_URL", "")
    key = os.getenv("SUPABASE_KEY", "")
    return url, key


def _enabled() -> bool:
    return os.getenv("SUPABASE_ENABLED", "true").lower() not in ("false", "0", "no")


async def _on_build_complete(event: Event) -> None:
    url, key = _creds()
    if not url or not key or not _enabled():
        return

    data = event.data
    row = {
        "task_id": f"nexus_v5_build:{event.plan_id}",
        "success": bool(data.get("success", False)),
        "result": {
            "event": "build.complete",
            "plan_id": event.plan_id,
            "goal": data.get("goal", ""),
            "builder": data.get("builder_used", data.get("builder", "")),
            "attempt_count": data.get("attempt_count"),
            "files_written": data.get("files_written"),
            "verify_summary": data.get("verify_summary", ""),
            "test_summary": data.get("test_summary", ""),
            "verification_status": data.get("verification_status", ""),
            "test_status": data.get("test_status", ""),
        },
        "error": data.get("error") if not data.get("success") else None,
    }

    endpoint = f"{url}/rest/v1/{_TABLE}"
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal",
    }

    async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=4.0)) as client:
        resp = await client.post(endpoint, json=row, headers=headers)
        resp.raise_for_status()

    logger.info(
        "Supabase: automation_runs inserted (plan=%s success=%s)",
        event.plan_id, data.get("success"),
    )


def register() -> int:
    """Register Supabase subscribers if credentials are configured.

    Returns number of subscribers registered (0 if not configured).
    """
    url, key = _creds()
    if not url or not key:
        logger.debug("Supabase subscriber: SUPABASE_URL/KEY not set — skipping")
        return 0
    if not _enabled():
        logger.debug("Supabase subscriber: SUPABASE_ENABLED=false — skipping")
        return 0

    subscribe(EventType.BUILD_COMPLETE, _on_build_complete)
    logger.info("Supabase: 1 subscriber registered (build.complete \u2192 automation_runs)")
    return 1
