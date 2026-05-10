"""Claude provider — direct Anthropic API (no gateway).

Reads defaults from `model-registry/claude-sonnet-4-6/config.json` when the
file is available; otherwise falls back to settings.
"""

from __future__ import annotations

import logging
from typing import Optional

import httpx

from api_gateway.config.settings import get_settings
from serving.brain_pool.providers import ProviderResult

logger = logging.getLogger("nexus.brain.claude")

# Per-1M-token pricing (USD) — used by brain_cost_tracker; keep aligned with
# model-registry/claude-sonnet-4-6/rate-limits.yaml when that file is authoritative.
_PRICE_IN_PER_M = 3.00
_PRICE_OUT_PER_M = 15.00


async def chat(
    messages: list[dict],
    *,
    system_prompt: str = "",
    max_tokens: int = 4096,
    temperature: float = 0.7,
    client: Optional[httpx.AsyncClient] = None,
) -> ProviderResult:
    settings = get_settings()
    api_key = settings.anthropic_api_key or settings.anthropic_oauth_token
    if not api_key:
        raise RuntimeError("anthropic_api_key / anthropic_oauth_token not configured")

    # Anthropic wants system separate from the messages list.
    system = system_prompt
    non_system: list[dict] = []
    for m in messages:
        if m.get("role") == "system":
            system = (system + "\n\n" + m["content"]).strip() if system else m["content"]
        else:
            non_system.append({"role": m["role"], "content": m["content"]})

    payload = {
        "model": settings.claude_model,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "messages": non_system,
    }
    if system:
        payload["system"] = system

    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }

    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=60.0)
    try:
        resp = await client.post(
            "https://api.anthropic.com/v1/messages", headers=headers, json=payload
        )
        resp.raise_for_status()
        data = resp.json()
    finally:
        if owns_client:
            await client.aclose()

    content = data["content"][0]["text"]
    usage = data.get("usage", {})
    tokens_in = int(usage.get("input_tokens", 0))
    tokens_out = int(usage.get("output_tokens", 0))
    cost = (tokens_in / 1_000_000) * _PRICE_IN_PER_M + (tokens_out / 1_000_000) * _PRICE_OUT_PER_M

    return ProviderResult(
        content=content,
        model_used=settings.claude_model,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cost_usd=cost,
    )


async def health(client: Optional[httpx.AsyncClient] = None) -> bool:
    """Cheap reachability probe — verifies API key + Anthropic connectivity."""
    settings = get_settings()
    api_key = settings.anthropic_api_key or settings.anthropic_oauth_token
    if not api_key:
        return False
    # A zero-cost probe: ask for 1 token with a trivial prompt.
    try:
        result = await chat(
            [{"role": "user", "content": "ok"}],
            max_tokens=1,
            client=client,
        )
        return bool(result.content)
    except Exception as exc:
        logger.debug("claude health probe failed: %s", exc)
        return False
