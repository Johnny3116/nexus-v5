"""events/discord_subscriber.py — Discord webhook notifications.

Posts rich embeds to DISCORD_WEBHOOK_URL on build and test events.

Environment:
  DISCORD_WEBHOOK_URL — Discord incoming webhook URL
                        If not set, all handlers are no-ops.

Events handled:
  build.complete — success or failure embed (green / red)
  test.failed    — orange warning embed with test output snippet
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

import httpx

from events.event_types import Event, EventType
from events.event_bus import subscribe

logger = logging.getLogger(__name__)

# Colors
_GREEN = 0x2ECC71
_RED   = 0xE74C3C
_AMBER = 0xE67E22


def _webhook_url() -> str:
    return os.getenv("DISCORD_WEBHOOK_URL", "")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _on_build_complete(event: Event) -> None:
    url = _webhook_url()
    if not url:
        return

    data = event.data
    success = bool(data.get("success", False))
    color = _GREEN if success else _RED
    status = "\u2705 Build Succeeded" if success else "\u274c Build Failed"
    attempt_count = data.get("attempt_count", "?")
    files_written = data.get("files_written", 0)
    builder = data.get("builder_used", data.get("builder", "?"))
    goal = str(data.get("goal", ""))[:80]

    fields = [
        {"name": "Plan ID",   "value": f"`{event.plan_id[:24]}`", "inline": True},
        {"name": "Builder",   "value": builder,                    "inline": True},
        {"name": "Attempts",  "value": str(attempt_count),         "inline": True},
        {"name": "Files",     "value": str(files_written),         "inline": True},
    ]
    if verify := data.get("verify_summary"):
        fields.append({"name": "Verify", "value": str(verify)[:100], "inline": False})
    if tests := data.get("test_summary"):
        fields.append({"name": "Tests",  "value": str(tests)[:100],  "inline": False})
    if not success and (err := data.get("error")):
        fields.append({"name": "Error",  "value": f"```{str(err)[:200]}```", "inline": False})

    embed = {
        "title": status,
        "description": goal or None,
        "color": color,
        "fields": fields,
        "footer": {"text": "Nexus V5 \u2022 Build Pipeline"},
        "timestamp": _now_iso(),
    }

    async with httpx.AsyncClient(timeout=httpx.Timeout(8.0, connect=3.0)) as client:
        resp = await client.post(url, json={"embeds": [embed]})
        resp.raise_for_status()

    logger.info(
        "Discord: build.complete sent (plan=%s success=%s)", event.plan_id, success
    )


async def _on_test_failed(event: Event) -> None:
    url = _webhook_url()
    if not url:
        return

    data = event.data
    attempt = data.get("attempt", "?")
    tests_run = data.get("tests_run", "?")
    summary = str(data.get("summary", ""))

    fields = [
        {"name": "Plan ID",    "value": f"`{event.plan_id[:24]}`", "inline": True},
        {"name": "Attempt",    "value": str(attempt),              "inline": True},
        {"name": "Tests Run",  "value": str(tests_run),            "inline": True},
    ]
    if summary:
        snippet = summary[:400]
        fields.append({"name": "Output", "value": f"```{snippet}```", "inline": False})

    embed = {
        "title": "\u26a0\ufe0f Tests Failed",
        "color": _AMBER,
        "fields": fields,
        "footer": {"text": "Nexus V5 \u2022 Build Pipeline"},
        "timestamp": _now_iso(),
    }

    async with httpx.AsyncClient(timeout=httpx.Timeout(8.0, connect=3.0)) as client:
        resp = await client.post(url, json={"embeds": [embed]})
        resp.raise_for_status()

    logger.info("Discord: test.failed sent (plan=%s)", event.plan_id)


def register() -> int:
    """Register Discord subscribers if DISCORD_WEBHOOK_URL is configured.

    Returns number of subscribers registered (0 if not configured).
    """
    if not _webhook_url():
        logger.debug("Discord subscriber: DISCORD_WEBHOOK_URL not set — skipping")
        return 0

    subscribe(EventType.BUILD_COMPLETE, _on_build_complete)
    subscribe(EventType.TEST_FAILED, _on_test_failed)
    logger.info("Discord: 2 subscribers registered (build.complete, test.failed)")
    return 2
