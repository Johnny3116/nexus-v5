"""BrainPool — the singleton routing brain.

Every LLM call in Nexus flows through here. Responsibilities:
  1. Resolve task_type → primary provider + fallback chain (routing_rules.yaml)
  2. Call primary. On failure, log + alert, then walk the fallback chain.
  3. Return a normalized dict (provider, model_used, response, latency_ms).

What BrainPool does NOT do (intentional — phases 3+):
  - Soul container / personality injection (safety/identity/)
  - RAG / memory retrieval (data_pipeline/rag_pipeline/)
  - Prompt injection scanning (safety/input_filters/)
  - Safety tier gating (safety/output_filters/)

That separation is enforced by the api_gateway request pipeline, not here.
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Any, Awaitable, Callable

import httpx
import yaml

from kv_cache.warm.conversation_cache import cache as conversation_cache
from serving.brain_pool.providers import ProviderResult, claude, codex, qwen

logger = logging.getLogger("nexus.brain.pool")

_RULES_PATH = Path(__file__).resolve().parent / "routing_rules.yaml"

# Each provider module exposes `chat(messages, **kwargs)` and `health(client)`.
_PROVIDERS: dict[str, Any] = {
    "claude": claude,
    "codex": codex,
    "qwen": qwen,
}


class BrainPool:
    def __init__(self) -> None:
        self._rules = self._load_rules()
        self._client = httpx.AsyncClient(timeout=120.0)
        self._claude_over_budget = False  # flipped by claude_budget.py

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def chat(
        self,
        message: str,
        *,
        task_type: str = "chat",
        identity_id: str = "john",
        system_prompt: str = "",
        conversation_id: str | None = None,
    ) -> dict[str, Any]:
        history: list[dict] = []
        if conversation_id:
            history = conversation_cache.get(conversation_id) or []
            # Cold cache (process restart, LRU eviction): hydrate from Supabase
            # so multi-turn context survives across deployments.
            if not history:
                history = await self._hydrate_history(conversation_id)
                if history:
                    conversation_cache.set(conversation_id, history)
        messages = self._build_messages(message, system_prompt, history=history)
        chain = self._resolve_chain(task_type)

        start = time.monotonic()
        last_exc: Exception | None = None
        fallback_used = False

        for idx, provider_name in enumerate(chain):
            provider_mod = _PROVIDERS.get(provider_name)
            if provider_mod is None:
                logger.warning("unknown provider '%s' in chain for '%s'", provider_name, task_type)
                continue
            try:
                result: ProviderResult = await provider_mod.chat(
                    messages,
                    system_prompt=system_prompt,
                    client=self._client,
                    task_type=task_type,
                )
                latency_ms = int((time.monotonic() - start) * 1000)
                if conversation_id and result.content:
                    # Persist turn to warm cache (cap last 12 turns ≈ 6 exchanges).
                    new_history = history + [
                        {"role": "user", "content": message},
                        {"role": "assistant", "content": result.content},
                    ]
                    conversation_cache.set(conversation_id, new_history[-12:])
                    # Cold persistence: fire-and-forget. Supabase outage never
                    # blocks a reply. Skip for voice — high churn, low value.
                    if task_type != "voice":
                        asyncio.create_task(self._persist_turn(
                            conversation_id=conversation_id,
                            identity_id=identity_id,
                            user_message=message,
                            assistant_message=result.content,
                            model=result.model_used,
                            provider=provider_name,
                        ))
                return {
                    "response": result.content,
                    "provider": self._provider_label(provider_name),
                    "model_used": result.model_used,
                    "latency_ms": latency_ms,
                    "tokens_in": result.tokens_in,
                    "tokens_out": result.tokens_out,
                    "fallback_used": fallback_used,
                    "conversation_id": conversation_id,
                }
            except Exception as exc:
                last_exc = exc
                fallback_used = True
                logger.warning(
                    "provider '%s' failed for task_type='%s': type=%s repr=%r str=%r (position %d/%d in chain)",
                    provider_name, task_type, type(exc).__name__, exc, str(exc),
                    idx + 1, len(chain),
                )
                logger.warning("provider '%s' traceback:", provider_name, exc_info=True)
                # TODO: hand off to observability/alerting per routing_rules.yaml.
                #       For now, log only. Alert wiring lands with the alerting module.

        raise RuntimeError(
            f"all providers in chain {chain} failed for task_type='{task_type}': {last_exc}"
        )

    async def chat_stream(
        self,
        message: str,
        *,
        task_type: str = "chat",
        identity_id: str = "john",
        system_prompt: str = "",
        conversation_id: str | None = None,
    ) -> Any:
        """Streaming variant of chat(). Yields:
            {"type": "delta", "content": str}        per token
            {"type": "done",  "meta": {...}}         once at end
            {"type": "error", "message": str}        on total failure

        Currently Qwen-only (the local provider). If Qwen errors before any
        delta is yielded, we fall back to non-streaming chat() and emit the
        full result as a single delta so callers don't need a separate path.
        """
        history: list[dict] = []
        if conversation_id:
            history = conversation_cache.get(conversation_id) or []
            if not history:
                history = await self._hydrate_history(conversation_id)
                if history:
                    conversation_cache.set(conversation_id, history)
        messages = self._build_messages(message, system_prompt, history=history)

        start = time.monotonic()
        provider_name = "qwen"
        provider_mod = _PROVIDERS[provider_name]
        accumulated: list[str] = []
        result: ProviderResult | None = None

        try:
            async for chunk in provider_mod.chat_stream(
                messages,
                client=self._client,
                task_type=task_type,
            ):
                if chunk["type"] == "delta":
                    accumulated.append(chunk["content"])
                    yield {"type": "delta", "content": chunk["content"]}
                elif chunk["type"] == "done":
                    result = chunk["result"]
        except Exception as exc:
            logger.warning("qwen stream failed (%s) — falling back to non-stream chain", exc)

        if result is None or not result.content:
            try:
                fallback = await self.chat(
                    message=message,
                    task_type=task_type,
                    identity_id=identity_id,
                    system_prompt=system_prompt,
                    conversation_id=conversation_id,
                )
            except Exception as exc:
                yield {"type": "error", "message": str(exc)}
                return
            yield {"type": "delta", "content": fallback["response"]}
            yield {
                "type": "done",
                "meta": {
                    "provider": fallback["provider"],
                    "model_used": fallback["model_used"],
                    "latency_ms": fallback["latency_ms"],
                    "tokens_in": fallback.get("tokens_in", 0),
                    "tokens_out": fallback.get("tokens_out", 0),
                    "fallback_used": True,
                    "conversation_id": conversation_id,
                },
            }
            return

        latency_ms = int((time.monotonic() - start) * 1000)
        full_text = result.content

        if conversation_id:
            new_history = history + [
                {"role": "user", "content": message},
                {"role": "assistant", "content": full_text},
            ]
            conversation_cache.set(conversation_id, new_history[-12:])
            if task_type != "voice":
                asyncio.create_task(self._persist_turn(
                    conversation_id=conversation_id,
                    identity_id=identity_id,
                    user_message=message,
                    assistant_message=full_text,
                    model=result.model_used,
                    provider=provider_name,
                ))

        yield {
            "type": "done",
            "meta": {
                "provider": self._provider_label(provider_name),
                "model_used": result.model_used,
                "latency_ms": latency_ms,
                "tokens_in": result.tokens_in,
                "tokens_out": result.tokens_out,
                "fallback_used": False,
                "conversation_id": conversation_id,
            },
        }

    async def health_check(self) -> dict[str, str]:
        """Probe each provider in parallel. Returns {provider: 'ok'|'down'}."""
        probes: dict[str, Awaitable[bool]] = {
            name: mod.health(client=self._client)
            for name, mod in _PROVIDERS.items()
        }
        results_list = await asyncio.gather(*probes.values(), return_exceptions=True)
        out: dict[str, str] = {}
        for name, res in zip(probes.keys(), results_list):
            if isinstance(res, Exception):
                out[name] = "down"
            else:
                out[name] = "ok" if res else "down"
        return out

    def set_claude_over_budget(self, value: bool) -> None:
        """Called by rate_limiter/claude_budget.py to force route overrides."""
        if value != self._claude_over_budget:
            logger.warning("claude_over_budget flipped to %s", value)
        self._claude_over_budget = value

    async def close(self) -> None:
        await self._client.aclose()

    # ------------------------------------------------------------------
    # Cold persistence (Supabase `conversations` + `messages`)
    # ------------------------------------------------------------------

    async def _hydrate_history(self, conversation_id: str, limit: int = 12) -> list[dict]:
        """Pull the last N messages for a conversation from Supabase.

        Silent degrade on any failure — a cold cache and no DB just means
        the LLM sees a shorter context, not a broken reply.
        """
        try:
            from kv_cache.cold.supabase_client import get_supabase
            db = get_supabase()
            resp = (
                db.table("messages")
                .select("role,content")
                .eq("conversation_id", conversation_id)
                .order("timestamp", desc=True)
                .limit(limit)
                .execute()
            )
            rows = list(reversed(resp.data or []))
            return [{"role": r["role"], "content": r["content"]} for r in rows if r.get("content")]
        except Exception as exc:
            logger.debug("history hydrate skipped for %s: %s", conversation_id, exc)
            return []

    async def _persist_turn(
        self,
        *,
        conversation_id: str,
        identity_id: str,
        user_message: str,
        assistant_message: str,
        model: str,
        provider: str,
    ) -> None:
        """Upsert conversation + insert user/assistant rows. Never raises."""
        try:
            from kv_cache.cold.supabase_client import get_supabase
            db = get_supabase()
            # Upsert only fields we own — message_count/created_at/defaults
            # on the table keep their own values for existing rows.
            db.table("conversations").upsert({
                "id": conversation_id,
                "identity_id": identity_id,
                "platform": "api",
            }, on_conflict="id").execute()
            db.table("messages").insert([
                {"conversation_id": conversation_id, "role": "user", "content": user_message,
                 "source": "brain_pool", "platform": "api"},
                {"conversation_id": conversation_id, "role": "assistant", "content": assistant_message,
                 "source": "brain_pool", "platform": "api", "model": model},
            ]).execute()
        except Exception as exc:
            logger.warning("supabase persist skipped for %s: %s", conversation_id, exc)

    # ------------------------------------------------------------------
    # Routing
    # ------------------------------------------------------------------

    def _resolve_chain(self, task_type: str) -> list[str]:
        routes = self._rules.get("routing", {})
        default = self._rules.get("default", {"primary": "codex", "fallback": ["claude"]})

        route = routes.get(task_type, default)

        # Apply budget override if active.
        if self._claude_over_budget:
            overrides = self._rules.get("budget_overrides", {}).get("claude_over_budget", {})
            if task_type in overrides:
                route = {**route, **overrides[task_type]}

        raw_chain = [route["primary"]] + list(route.get("fallback", []))
        # Dedupe while preserving order — budget overrides can collapse
        # primary onto an entry already in fallback.
        seen: set[str] = set()
        chain: list[str] = []
        for p in raw_chain:
            if p not in seen:
                seen.add(p)
                chain.append(p)
        return chain

    @staticmethod
    def _provider_label(name: str) -> str:
        # Codex calls travel via the Nexus-Agent gateway — downstream expects
        # provider="gateway" for those, matching the 4/16 smoke-test contract.
        return "gateway" if name == "codex" else name

    @staticmethod
    def _build_messages(message: str, system_prompt: str, *, history: list[dict] | None = None) -> list[dict]:
        msgs: list[dict] = []
        if system_prompt:
            msgs.append({"role": "system", "content": system_prompt})
        if history:
            msgs.extend(history)
        msgs.append({"role": "user", "content": message})
        return msgs

    @staticmethod
    def _load_rules() -> dict[str, Any]:
        try:
            with _RULES_PATH.open("r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except FileNotFoundError:
            logger.error("routing_rules.yaml missing at %s", _RULES_PATH)
            return {}


# ---------------------------------------------------------------------------
# Module-level singleton (no lru_cache — see settings.py lesson)
# ---------------------------------------------------------------------------

_pool: BrainPool | None = None


def get_brain_pool() -> BrainPool:
    global _pool
    if _pool is None:
        _pool = BrainPool()
    return _pool
