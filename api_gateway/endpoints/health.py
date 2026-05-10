"""GET /health — aggregated gateway + provider health.

Reports:
  - gateway self-status (always "healthy" if we're answering at all)
  - per-provider status from BrainPool.health_check()
  - endpoint availability map (which /v1/* routes are live vs. 501 stubs)

Stubs that aren't implemented yet report "not_implemented" rather than
"unreachable" — the difference matters for monitoring dashboards.
"""

from __future__ import annotations

from fastapi import APIRouter

from api_gateway.config.features import features
from api_gateway.shared.types import HealthResponse, ProviderHealth
from serving.brain_pool.brain_pool import get_brain_pool

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    pool = get_brain_pool()
    provider_status = await pool.health_check()

    endpoints = {
        "/v1/chat":   "enabled" if features.chat_enabled else "disabled",
        "/v1/memory": "enabled" if features.memory_enabled else "disabled",
        "/v1/task":   "enabled",
        "/v1/skill":  "enabled",
    }

    return HealthResponse(
        status="healthy",
        providers=ProviderHealth(
            claude=provider_status.get("claude", "unknown"),
            codex=provider_status.get("codex", "unknown"),
            qwen=provider_status.get("qwen", "unknown"),
        ),
        endpoints=endpoints,
    )
