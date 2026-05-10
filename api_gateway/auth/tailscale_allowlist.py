"""Tailscale allowlist middleware.

Doctrine 1: Tailscale-only. Rejects any request whose client IP is not in
the Tailscale CGNAT range `100.64.0.0/10` — with loopback carved out for
same-host smoke tests and PM2 internal probes.

Explicit allowlist via env `TAILSCALE_ALLOWLIST` overrides the CGNAT check
for tightly controlled deployments (comma-separated IPs).
"""

from __future__ import annotations

import ipaddress
import logging
import os

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

logger = logging.getLogger("nexus.api_gateway.auth.tailscale")

_TAILSCALE_CGNAT = ipaddress.ip_network("100.64.0.0/10")


def _explicit_allowlist() -> set[str]:
    raw = os.getenv("TAILSCALE_ALLOWLIST", "").strip()
    return {ip.strip() for ip in raw.split(",") if ip.strip()}


class TailscaleAllowlistMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        client_ip = request.client.host if request.client else ""
        try:
            addr = ipaddress.ip_address(client_ip)
        except ValueError:
            return JSONResponse(status_code=403, content={"detail": "bad client address"})

        allowlist = _explicit_allowlist()
        if allowlist:
            if client_ip not in allowlist:
                logger.warning("rejected non-allowlisted client %s", client_ip)
                return JSONResponse(status_code=403, content={"detail": "ip not in allowlist"})
        elif not (addr.is_loopback or addr in _TAILSCALE_CGNAT):
            logger.warning("rejected non-tailscale client %s", client_ip)
            return JSONResponse(status_code=403, content={"detail": "non-tailscale source"})

        return await call_next(request)
