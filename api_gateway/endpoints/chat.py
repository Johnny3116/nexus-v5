"""POST /v1/chat — primary chat endpoint with Phase 4 safety wired.

Pipeline:
  1. injection_scanner.require_clean(user_message) — 400 on detection
  2. BrainPool.chat(...) — provider routing + LLM call
  3. soul_container.enforce(response) — strip assistant-isms, tool leaks
  4. return ChatResponse

Doctrine §10 ordering: input filter → brain → output filter.
"""

from __future__ import annotations

import logging
from typing import AsyncIterator

from fastapi import APIRouter, HTTPException
from starlette.responses import StreamingResponse

from api_gateway.config.features import features
from api_gateway.rate_limiter.claude_budget import is_over_budget
from api_gateway.shared.types import ChatRequest, ChatResponse, Provider
from safety.identity.soul_container import enforce as soul_enforce
from safety.input_filters.injection_scanner import (
    PromptInjectionDetected,
    require_clean,
)
from serving.brain_pool.brain_pool import get_brain_pool
from serving.brain_pool.prompt_builder import assemble_system_prompt
from serving.streaming.sse_handler import sse_format

logger = logging.getLogger("nexus.api_gateway.endpoints.chat")

router = APIRouter(tags=["chat"])


@router.post("/v1/chat", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    if not features.chat_enabled:
        raise HTTPException(status_code=503, detail="chat endpoint disabled")

    # ── Input filter (doctrine §10 rule #3) ────────────────────────────────
    try:
        require_clean(req.message)
    except PromptInjectionDetected as exc:
        logger.warning(
            "injection blocked for identity=%s rules=%s",
            req.identity_id,
            [h.rule for h in exc.hits],
        )
        raise HTTPException(
            status_code=400,
            detail={
                "error": "prompt_injection_blocked",
                "rules": [h.rule for h in exc.hits],
            },
        )

    pool = get_brain_pool()

    # Budget-driven re-routing: flag BrainPool before the call so the
    # chain resolution picks up the override.
    pool.set_claude_over_budget(await is_over_budget())

    # Soul + memories + RAG → system prompt. Retrieval failures degrade
    # silently to soul-only (see assemble_system_prompt).
    system_prompt = await assemble_system_prompt(
        req.message,
        task_type=req.task_type.value,
        identity_id=req.identity_id,
    )

    try:
        result = await pool.chat(
            message=req.message,
            task_type=req.task_type.value,
            identity_id=req.identity_id,
            system_prompt=system_prompt,
            conversation_id=req.conversation_id,
        )
    except Exception as exc:
        logger.exception("chat call failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"brain call failed: {exc}")

    # ── Output filter (doctrine §6 identity integrity) ────────────────────
    cleaned_response = soul_enforce(result["response"])

    return ChatResponse(
        response=cleaned_response,
        provider=Provider(result["provider"]),
        model_used=result["model_used"],
        latency_ms=result["latency_ms"],
        conversation_id=result.get("conversation_id"),
        tokens_in=result.get("tokens_in", 0),
        tokens_out=result.get("tokens_out", 0),
        fallback_used=result.get("fallback_used", False),
    )


@router.post("/v1/chat/stream")
async def chat_stream(req: ChatRequest):
    """SSE streaming variant of /v1/chat. Same pipeline, token-by-token wire.

    Events:
      event: token   data: {"delta": "..."}        per token
      event: done    data: {"provider": ..., "model_used": ..., "latency_ms": ...,
                            "fallback_used": bool, "conversation_id": ...}
      event: error   data: {"message": "..."}
    """
    if not features.chat_enabled:
        raise HTTPException(status_code=503, detail="chat endpoint disabled")

    try:
        require_clean(req.message)
    except PromptInjectionDetected as exc:
        logger.warning(
            "injection blocked for identity=%s rules=%s",
            req.identity_id,
            [h.rule for h in exc.hits],
        )
        raise HTTPException(
            status_code=400,
            detail={
                "error": "prompt_injection_blocked",
                "rules": [h.rule for h in exc.hits],
            },
        )

    pool = get_brain_pool()
    pool.set_claude_over_budget(await is_over_budget())

    system_prompt = await assemble_system_prompt(
        req.message,
        task_type=req.task_type.value,
        identity_id=req.identity_id,
    )

    async def _event_source() -> AsyncIterator[bytes]:
        try:
            async for chunk in pool.chat_stream(
                message=req.message,
                task_type=req.task_type.value,
                identity_id=req.identity_id,
                system_prompt=system_prompt,
                conversation_id=req.conversation_id,
            ):
                kind = chunk.get("type")
                if kind == "delta":
                    # Soul filter is full-text only (regex with anchors); we
                    # forward raw deltas and let the client display live, then
                    # final cleanup happens in non-stream consumers.
                    yield sse_format("token", {"delta": chunk["content"]})
                elif kind == "done":
                    yield sse_format("done", chunk["meta"])
                elif kind == "error":
                    yield sse_format("error", {"message": chunk["message"]})
        except Exception as exc:
            logger.exception("chat stream failed: %s", exc)
            yield sse_format("error", {"message": str(exc)})

    return StreamingResponse(
        _event_source(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
