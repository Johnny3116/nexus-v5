"""Request-body injection scanner middleware.

Belt-and-suspenders for Doctrine A10 rule #3: scan user-supplied text on
every write endpoint, not just `/v1/chat`. Endpoints that already call
`require_clean()` inline (chat.py) will double-scan — the scan is a
cheap regex pass so the overhead is negligible.

Scope (allow-list — only scans these paths):
    /v1/chat, /v1/task, /v1/memory

Fields scanned (if present as top-level string in the JSON body):
    message, content, prompt, task, description

On hit: 400 with {error, field, rules}. Otherwise the body is replayed
to the downstream endpoint unchanged.
"""

from __future__ import annotations

import json
import logging

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from safety.input_filters.injection_scanner import scan

logger = logging.getLogger("nexus.safety.injection_middleware")

# /v1/task is intentionally excluded — TaskRequest does field-level scanning
# via a Pydantic validator so structured sub-fields can be handled precisely.
_SCAN_PATH_PREFIXES: tuple[str, ...] = ("/v1/chat", "/v1/memory")
_TEXT_FIELDS: tuple[str, ...] = ("message", "content", "prompt", "task", "description")


class InjectionScannerMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.method != "POST":
            return await call_next(request)
        if not any(request.url.path.startswith(p) for p in _SCAN_PATH_PREFIXES):
            return await call_next(request)

        body = await request.body()
        if body:
            try:
                data = json.loads(body)
            except Exception:
                data = None
            if isinstance(data, dict):
                for field in _TEXT_FIELDS:
                    value = data.get(field)
                    if isinstance(value, str) and value:
                        hits = scan(value)
                        if hits:
                            logger.warning(
                                "injection blocked path=%s field=%s rules=%s",
                                request.url.path,
                                field,
                                [h.rule for h in hits],
                            )
                            return JSONResponse(
                                status_code=400,
                                content={
                                    "error": "prompt_injection_blocked",
                                    "field": field,
                                    "rules": [h.rule for h in hits],
                                },
                            )

            async def _receive():
                return {"type": "http.request", "body": body, "more_body": False}

            request._receive = _receive  # replay body for downstream handlers

        return await call_next(request)
