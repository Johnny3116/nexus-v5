"""POST /v1/skill — direct skill invocation (bypass the agentic loop).

Still safety-gated: the same tier + doctrine checks as AgenticLoop apply.
Source is always HUMAN here, so only CRITICAL tier hits the approval queue.

POST /v1/skill/reload — hot-reload skill plugins (re-import serving.skills.*).
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, HTTPException, Request

from api_gateway.shared.types import SkillInvokeRequest, SkillInvokeResponse
from safety.output_filters.doctrine_enforcer import (
    DoctrineViolation,
    ProposedAction,
    enforce as doctrine_enforce,
)
from safety.output_filters.safety_tier_gate import TaskSource, requires_approval
from serving.skills.execution_context import ExecutionContext
from serving.skills.skill_manager import get_skill_manager

logger = logging.getLogger("nexus.api_gateway.endpoints.skill")

router = APIRouter(tags=["skill"])


def _get_approval_queue(request: Request):
    aq = getattr(request.app.state, "approval_queue", None)
    if aq is not None:
        return aq
    from safety.output_filters.approval_queue import ApprovalQueue
    try:
        from kv_cache.cold.supabase_client import get_supabase
        db = get_supabase()
    except Exception:
        db = None
    aq = ApprovalQueue(db=db)
    request.app.state.approval_queue = aq
    return aq


@router.post("/v1/skill", response_model=SkillInvokeResponse)
async def invoke_skill(req: SkillInvokeRequest, request: Request) -> SkillInvokeResponse:
    mgr = get_skill_manager()
    skill = mgr.get(req.skill)
    if skill is None:
        raise HTTPException(status_code=404, detail=f"skill '{req.skill}' not found")

    source = TaskSource.HUMAN

    if requires_approval(skill.safety_tier, source):
        aq = _get_approval_queue(request)
        qid = await aq.enqueue(
            skill_name=req.skill, action=req.action, params=req.params,
            source=source, request_id=str(uuid.uuid4()),
        )
        return SkillInvokeResponse(
            skill=req.skill, action=req.action,
            result={"success": False, "queued": True, "approval_id": qid},
        )

    valid, err = skill.validate_params(req.params)
    if not valid:
        raise HTTPException(status_code=400, detail=f"invalid params: {err}")

    try:
        doctrine_enforce(ProposedAction(skill=req.skill, action=req.action, params=req.params))
    except DoctrineViolation as exc:
        raise HTTPException(status_code=403, detail={"doctrine_violation": exc.rule, "detail": str(exc)})

    ctx = ExecutionContext(
        skill_name=req.skill, action=req.action, params=req.params,
        source=source, request_id=str(uuid.uuid4()),
    )
    try:
        result = await skill.execute(ctx)
        result.setdefault("success", True)
    except Exception as exc:
        logger.exception("skill '%s.%s' failed", req.skill, req.action)
        raise HTTPException(status_code=500, detail=f"skill execution failed: {exc}")

    return SkillInvokeResponse(skill=req.skill, action=req.action, result=result)


@router.post("/v1/skill/reload")
async def reload_skills() -> dict:
    mgr = get_skill_manager()
    count = mgr.reload()
    logger.info("hot-reloaded %d skills", count)
    return {"reloaded": count, "skills": list(mgr.all().keys())}
