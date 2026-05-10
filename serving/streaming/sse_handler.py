"""Server-Sent Events helper for streaming brain responses.

Chat clients (nexus-chat web UI, avatar-pipeline bridge) consume token
deltas via SSE so the UI feels live. This helper wraps an async token
generator into a `text/event-stream` response.
"""

from __future__ import annotations

import json
from typing import AsyncIterator

from fastapi import Response
from starlette.responses import StreamingResponse


def sse_format(event: str, data: dict | str) -> bytes:
    payload = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)
    # SSE wire format: `event: name\ndata: payload\n\n`
    return f"event: {event}\ndata: {payload}\n\n".encode("utf-8")


async def stream_tokens(tokens: AsyncIterator[str]) -> AsyncIterator[bytes]:
    try:
        async for tok in tokens:
            yield sse_format("token", {"delta": tok})
        yield sse_format("done", {"ok": True})
    except Exception as exc:  # pragma: no cover — defensive
        yield sse_format("error", {"message": str(exc)})


def sse_response(tokens: AsyncIterator[str]) -> Response:
    return StreamingResponse(
        stream_tokens(tokens),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
