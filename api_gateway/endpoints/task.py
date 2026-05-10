"""POST /v1/task — agentic loop entrypoint.

Pipeline (doctrine §10):
  1. injection_scanner.require_clean(message) — 400 on detection
  2. AgenticLoop.run(...) — brain ↔ skill cycle, max 6 iterations
  3. soul_container.enforce(response) — strip assistant-isms from final text

The loop itself gates each skill through safety_tier_gate + doctrine_enforce;
DESTRUCTIVE/CRITICAL tasks land in the approval_queue and return queued=True.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request

from api_gateway.shared.types import TaskRequest, TaskResponse
from safety.identity.soul_container import enforce as soul_enforce
from safety.output_filters.safety_tier_gate import TaskSource

logger = logging.getLogger("nexus.api_gateway.endpoints.task")

router = APIRouter(tags=["task"])


def _get_loop(request: Request):
    """Shared AgenticLoop from app state, or build one on first use."""
    loop = getattr(request.app.state, "agentic_loop", None)
    if loop is not None:
        return loop
    from safety.output_filters.approval_queue import ApprovalQueue
    from serving.skills.agentic_loop import AgenticLoop
    from serving.skills.skill_manager import get_skill_manager

    try:
        from kv_cache.cold.supabase_client import get_supabase
        db = get_supabase()
    except Exception:
        db = None
    loop = AgenticLoop(
        skill_manager=get_skill_manager(),
        approval_queue=ApprovalQueue(db=db),
    )
    request.app.state.agentic_loop = loop
    return loop


@router.post("/v1/task", response_model=TaskResponse)
async def task(req: TaskRequest, request: Request) -> TaskResponse:
    # Injection scan runs in TaskRequest's field_validator; a hit becomes
    # a 422 from FastAPI with the rules in `detail`.
    loop = _get_loop(request)
    try:
        result = await loop.run(
            message=req.message,
            source=TaskSource.HUMAN,
            conversation_id=req.conversation_id,
            max_iterations=req.max_iterations,
        )
    except Exception as exc:
        logger.exception("agentic loop failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"task execution failed: {exc}")

    result["response"] = soul_enforce(result.get("response", ""))
    return TaskResponse(**result)
