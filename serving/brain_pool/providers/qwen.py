"""Qwen provider — local Ollama.

Always available; no external API dependency. Uses Ollama's native /api/chat
(not the /v1 OpenAI shim) because the native endpoint returns richer usage
stats (`eval_count`, `prompt_eval_count`).
"""

from __future__ import annotations

import json
import logging
from typing import AsyncIterator, Optional

import httpx

from api_gateway.config.settings import get_settings
from serving.brain_pool.providers import ProviderResult

logger = logging.getLogger("nexus.brain.qwen")


def _build_options(task_type: Optional[str], temperature: float) -> dict:
    """Per-task Ollama options. Caps output so chat doesn't ramble for 13s."""
    options: dict = {
        "temperature": temperature,
        # Tuned for the 2070 SUPER (8GB). num_ctx covers slim soul + 12-turn
        # history without forcing re-prefill; num_batch speeds prefill itself.
        "num_ctx": 4096,
        "num_batch": 512,
    }
    if task_type == "voice":
        options["num_predict"] = 80
    elif task_type in ("chat", "conversation"):
        options["num_predict"] = 256
    # reasoning/coding/complex stay uncapped — they need the room.
    return options


async def chat(
    messages: list[dict],
    *,
    temperature: float = 0.2,
    client: Optional[httpx.AsyncClient] = None,
    task_type: Optional[str] = None,
    **_: object,
) -> ProviderResult:
    settings = get_settings()
    url = f"{settings.ollama_url.rstrip('/')}/api/chat"
    payload = {
        "model": settings.qwen_model,
        "messages": messages,
        "stream": False,
        "options": _build_options(task_type, temperature),
        # Pin the model in VRAM permanently — avoids 3–8s cold reload between
        # idle periods. Safe on a dedicated box; override with OLLAMA_KEEP_ALIVE
        # env if you ever need to free GPU.
        "keep_alive": -1,
    }

    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=120.0)
    try:
        resp = await client.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()
    finally:
        if owns_client:
            await client.aclose()

    content = data.get("message", {}).get("content", "")
    return ProviderResult(
        content=content,
        model_used=settings.qwen_model,
        tokens_in=int(data.get("prompt_eval_count", 0)),
        tokens_out=int(data.get("eval_count", 0)),
        cost_usd=0.0,
    )


async def chat_stream(
    messages: list[dict],
    *,
    temperature: float = 0.2,
    client: Optional[httpx.AsyncClient] = None,
    task_type: Optional[str] = None,
    **_: object,
) -> AsyncIterator[dict]:
    """Yield {"type": "delta", "content": str} per token, then a final
    {"type": "done", "result": ProviderResult}.

    The caller is responsible for forwarding deltas to the wire and using
    the final ProviderResult for persistence + soul filtering.
    """
    settings = get_settings()
    url = f"{settings.ollama_url.rstrip('/')}/api/chat"
    payload = {
        "model": settings.qwen_model,
        "messages": messages,
        "stream": True,
        "options": _build_options(task_type, temperature),
        "keep_alive": -1,
    }

    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=120.0)
    accumulated: list[str] = []
    tokens_in = 0
    tokens_out = 0
    try:
        async with client.stream("POST", url, json=payload) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line:
                    continue
                try:
                    chunk = json.loads(line)
                except json.JSONDecodeError:
                    logger.debug("qwen stream: non-JSON line skipped")
                    continue
                delta = chunk.get("message", {}).get("content", "")
                if delta:
                    accumulated.append(delta)
                    yield {"type": "delta", "content": delta}
                if chunk.get("done"):
                    tokens_in = int(chunk.get("prompt_eval_count", 0))
                    tokens_out = int(chunk.get("eval_count", 0))
                    break
    finally:
        if owns_client:
            await client.aclose()

    yield {
        "type": "done",
        "result": ProviderResult(
            content="".join(accumulated),
            model_used=settings.qwen_model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=0.0,
        ),
    }


async def health(client: Optional[httpx.AsyncClient] = None) -> bool:
    settings = get_settings()
    url = f"{settings.ollama_url.rstrip('/')}/api/tags"
    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=3.0)
    try:
        resp = await client.get(url)
        if resp.status_code != 200:
            return False
        models = {m.get("name", "").split(":")[0] for m in resp.json().get("models", [])}
        # Accept either the custom nexus-qwen or the base qwen2.5-coder tag.
        return bool(models & {settings.qwen_model.split(":")[0], "qwen2.5-coder", "nexus-qwen"})
    except Exception as exc:
        logger.debug("qwen health probe failed: %s", exc)
        return False
    finally:
        if owns_client:
            await client.aclose()
