"""Inter-service shared-secret dependency.

Doctrine 1 says Tailscale-only. Doctrine is belt; this is suspenders. If a
compromised device ever joins the mesh, we still want application-layer
auth on any endpoint an internal service calls back into.

Usage:
    from fastapi import Depends
    from api_gateway.auth.inter_service_secret import require_inter_service

    @router.post("/internal/reload", dependencies=[Depends(require_inter_service)])
    async def reload_something(): ...
"""

from __future__ import annotations

from fastapi import HTTPException, Request

from api_gateway.config.settings import get_settings

HEADER = "X-Inter-Service-Secret"


async def require_inter_service(request: Request) -> None:
    expected = get_settings().inter_service_secret
    if not expected:
        raise HTTPException(status_code=500, detail="inter_service_secret not configured")
    if request.headers.get(HEADER, "") != expected:
        raise HTTPException(status_code=401, detail="inter-service auth failed")
