"""subscribers.py -- built-in event subscribers for the Nexus pipeline.

All handlers log structured [EVENT] lines at INFO level so build runs
are fully traceable from logs without touching pipeline code.

Future subscribers (Discord, Supabase, telemetry) register here or
in their own modules and call subscribe() directly.

Call register_all() once at server startup.
"""

from __future__ import annotations

import logging

from events.event_types import Event

logger = logging.getLogger("nexus.events")


# ---------------------------------------------------------------------------
# Plan lifecycle
# ---------------------------------------------------------------------------

async def _on_plan_created(event: Event) -> None:
    goal = event.data.get("goal", "")
    route = event.data.get("route", "")
    logger.info(
        "[EVENT] plan.created   plan=%s route=%-12s goal=%.60s",
        event.plan_id, route, goal,
    )


async def _on_plan_revised(event: Event) -> None:
    round_n = event.data.get("revision_round", "?")
    goal = event.data.get("goal", "")
    logger.info(
        "[EVENT] plan.revised   plan=%s round=%s goal=%.60s",
        event.plan_id, round_n, goal,
    )


async def _on_plan_approved(event: Event) -> None:
    goal = event.data.get("goal", "")
    logger.info(
        "[EVENT] plan.approved  plan=%s goal=%.60s",
        event.plan_id, goal,
    )


async def _on_plan_rejected(event: Event) -> None:
    logger.info("[EVENT] plan.rejected  plan=%s", event.plan_id)


# ---------------------------------------------------------------------------
# Build lifecycle
# ---------------------------------------------------------------------------

async def _on_build_started(event: Event) -> None:
    builder = event.data.get("builder", "unknown")
    goal = event.data.get("goal", "")
    logger.info(
        "[EVENT] build.started  plan=%s builder=%-30s goal=%.60s",
        event.plan_id, builder, goal,
    )


async def _on_build_attempt_failed(event: Event) -> None:
    attempt = event.data.get("attempt", "?")
    stage = event.data.get("stage", "unknown")
    reason = event.data.get("reason", "unknown")
    logger.info(
        "[EVENT] build.attempt_failed plan=%s attempt=%s stage=%s reason=%.80s",
        event.plan_id, attempt, stage, reason,
    )


async def _on_build_retried(event: Event) -> None:
    next_attempt = event.data.get("attempt", "?")
    reason = event.data.get("reason", "")
    logger.info(
        "[EVENT] build.retried  plan=%s next_attempt=%s reason=%s",
        event.plan_id, next_attempt, reason,
    )


async def _on_build_complete(event: Event) -> None:
    success = event.data.get("success")
    attempts = event.data.get("attempt_count")
    files = event.data.get("files_written", 0)
    verify = event.data.get("verify_summary", "")
    tests = event.data.get("test_summary", "")
    logger.info(
        "[EVENT] build.complete plan=%s success=%-5s attempts=%s files=%s verify=%r tests=%r",
        event.plan_id, success, attempts, files, verify, tests,
    )


# ---------------------------------------------------------------------------
# Test execution
# ---------------------------------------------------------------------------

async def _on_test_passed(event: Event) -> None:
    tests_run = event.data.get("tests_run", 0)
    attempt = event.data.get("attempt", "?")
    logger.info(
        "[EVENT] test.passed    plan=%s attempt=%s tests_run=%s",
        event.plan_id, attempt, tests_run,
    )


async def _on_test_failed(event: Event) -> None:
    attempt = event.data.get("attempt", "?")
    summary = event.data.get("summary", "")
    tests_run = event.data.get("tests_run", 0)
    logger.info(
        "[EVENT] test.failed    plan=%s attempt=%s tests_run=%s summary=%r",
        event.plan_id, attempt, tests_run, summary,
    )


# ---------------------------------------------------------------------------
# Workspace
# ---------------------------------------------------------------------------

async def _on_workspace_written(event: Event) -> None:
    files = event.data.get("files", [])
    count = event.data.get("count", len(files))
    logger.info(
        "[EVENT] workspace.written plan=%s files=%s names=%s",
        event.plan_id, count, [Path(f).name for f in files[:5]],
    )


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def register_all() -> None:
    """Register all built-in subscribers. Call once at server startup."""
    from pathlib import Path  # noqa: PLC0415  (local import for _on_workspace_written closure)
    from events.event_bus import subscribe
    from events.event_types import EventType

    # Rebind _on_workspace_written to have Path in scope
    global _on_workspace_written
    _path_ref = Path

    async def _on_workspace_written_bound(event: Event) -> None:
        files = event.data.get("files", [])
        count = event.data.get("count", len(files))
        logger.info(
            "[EVENT] workspace.written plan=%s files=%s names=%s",
            event.plan_id, count, [_path_ref(f).name for f in files[:5]],
        )

    subscribe(EventType.PLAN_CREATED, _on_plan_created)
    subscribe(EventType.PLAN_REVISED, _on_plan_revised)
    subscribe(EventType.PLAN_APPROVED, _on_plan_approved)
    subscribe(EventType.PLAN_REJECTED, _on_plan_rejected)
    subscribe(EventType.BUILD_STARTED, _on_build_started)
    subscribe(EventType.BUILD_ATTEMPT_FAILED, _on_build_attempt_failed)
    subscribe(EventType.BUILD_RETRIED, _on_build_retried)
    subscribe(EventType.BUILD_COMPLETE, _on_build_complete)
    subscribe(EventType.TEST_PASSED, _on_test_passed)
    subscribe(EventType.TEST_FAILED, _on_test_failed)
    subscribe(EventType.WORKSPACE_WRITTEN, _on_workspace_written_bound)

    logger.info("Event bus: %d built-in subscribers registered", 11)
    _register_external_subscribers()


# ---------------------------------------------------------------------------
# External subscribers (M16)
# ---------------------------------------------------------------------------

def _register_external_subscribers() -> None:
    """Conditionally register Discord + Supabase subscribers.

    Each module's register() is a no-op if its credentials are absent.
    Import errors are caught so a missing module never breaks register_all().
    """
    total = 0
    try:
        from events.discord_subscriber import register as _discord_reg
        total += _discord_reg()
    except Exception as e:
        import logging as _log
        _log.getLogger(__name__).warning("Discord subscriber failed to register: %s", e)

    try:
        from events.supabase_subscriber import register as _sup_reg
        total += _sup_reg()
    except Exception as e:
        import logging as _log
        _log.getLogger(__name__).warning("Supabase subscriber failed to register: %s", e)

    if total:
        logger.info("Event bus: %d external subscriber(s) registered", total)
