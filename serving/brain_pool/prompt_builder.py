"""Prompt builder — soul + memories + RAG → system prompt.

Called by api_gateway endpoints (e.g. /v1/chat) before every LLM call to
assemble the system prompt. Soul injection is the Phase 1 floor; memories
and RAG layer in on top (Phase 3, 2026-04-21).

The builder is intentionally separated from BrainPool so personality
logic doesn't leak into routing logic.
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger("nexus.brain.prompt_builder")

# Phase 3 retrieval budgets. Keep small so we don't blow the context or
# add seconds of latency to every chat call.
_MEMORY_LIMIT = 8
_RAG_TOP_K = 5

# Hard character budgets — Qwen2.5-coder:7b has 32k tokens (~128k chars).
# Soul block is ~15k chars; we keep the rest bounded so retrieval can't
# overflow the model and cause degraded output or fallback storms.
# Rough rule of thumb: ~4 chars/token.
_PER_MEMORY_CHARS = 400       # one memory item
_PER_RAG_CHUNK_CHARS = 800    # one RAG chunk (incl. [source] prefix)
_MEMORY_BLOCK_CHARS = 2_000   # whole "## Relevant Memories" section
_RAG_BLOCK_CHARS = 4_000      # whole "## Retrieved Context" section
_TOTAL_PROMPT_CHARS = 24_000  # final safety rail — ~6k tokens


def _truncate(s: str, limit: int, suffix: str = "…") -> str:
    """Return `s` clipped to `limit` chars, appending `suffix` when cut."""
    if len(s) <= limit:
        return s
    return s[: max(0, limit - len(suffix))] + suffix


def _pack_block(items: list[str], per_item: int, total: int, sep: str) -> list[str]:
    """Truncate each item, then drop items from the tail until under `total`."""
    clipped = [_truncate(item, per_item) for item in items]
    # Greedy pack: keep items from the front (most relevant / most recent)
    # until the joined total would exceed budget.
    packed: list[str] = []
    used = 0
    sep_cost = len(sep)
    for item in clipped:
        cost = len(item) + (sep_cost if packed else 0)
        if used + cost > total:
            break
        packed.append(item)
        used += cost
    return packed


def build_system_prompt(
    task_type: str = "chat",
    *,
    identity_id: str = "john",
    memories: Optional[list[str]] = None,
    rag_chunks: Optional[list[str]] = None,
) -> str:
    """Assemble the full system prompt for a BrainPool call.

    Layers (in order):
      1. Soul identity block (always)
      2. Relevant memories (phase 3 — currently empty)
      3. RAG context chunks (phase 3 — currently empty)
      4. Runtime context (task type, timestamp)

    Returns:
        Complete system prompt string.
    """
    parts: list[str] = []

    # Layer 1: Soul identity (loads soul.md + condensed doctrines).
    try:
        from safety.identity.soul_container import get_identity_block
        parts.append(get_identity_block(task_type))
    except Exception as exc:
        logger.warning("soul_container unavailable: %s — using fallback identity", exc)
        parts.append("You are Nexus, a personal AI assistant. Be direct and technically fluent.")

    # Voice brevity rule — spoken replies over 2 sentences feel painfully slow.
    if task_type == "voice":
        parts.append(
            "\n## Voice Reply Rules\n"
            "You are speaking out loud, not writing. Reply in 1–2 short sentences, "
            "~20 words max. No lists, no markdown, no code blocks. If John asks "
            "for detail, offer to expand — don't dump it upfront."
        )


    # Avatar chat: concise but expressive (personality > brevity).
    if task_type == "avatar":
        parts.append(
            "\n## Avatar Chat Rules\n"
            "Keep replies to 2-3 sentences. Be concise but let your personality "
            "show -- slang, energy, references are all good. No markdown, no "
            "code blocks, no lists. This goes to TTS so keep it speakable."
        )

    # Layer 2: Memories (phase 3). Char-budgeted to protect small-context models.
    if memories:
        packed_mem = _pack_block(
            [f"- {m}" for m in memories],
            per_item=_PER_MEMORY_CHARS,
            total=_MEMORY_BLOCK_CHARS,
            sep="\n",
        )
        if packed_mem:
            if len(packed_mem) < len(memories):
                logger.info(
                    "memory block truncated: kept %d/%d items",
                    len(packed_mem),
                    len(memories),
                )
            parts.append("\n## Relevant Memories\n\n" + "\n".join(packed_mem))

    # Layer 3: RAG chunks (phase 3). Same treatment.
    if rag_chunks:
        packed_rag = _pack_block(
            rag_chunks,
            per_item=_PER_RAG_CHUNK_CHARS,
            total=_RAG_BLOCK_CHARS,
            sep="\n---\n",
        )
        if packed_rag:
            if len(packed_rag) < len(rag_chunks):
                logger.info(
                    "RAG block truncated: kept %d/%d chunks",
                    len(packed_rag),
                    len(rag_chunks),
                )
            parts.append("\n## Retrieved Context\n\n" + "\n---\n".join(packed_rag))

    prompt = "\n".join(parts)

    # Final safety rail: if the prompt is still over budget (e.g. soul block
    # grew or an unusually large memory slipped through), clip the tail.
    if len(prompt) > _TOTAL_PROMPT_CHARS:
        logger.warning(
            "system prompt exceeds %d chars (got %d) — hard-truncating",
            _TOTAL_PROMPT_CHARS,
            len(prompt),
        )
        prompt = _truncate(prompt, _TOTAL_PROMPT_CHARS)

    return prompt


async def _fetch_memories(category: str = "user", limit: int = _MEMORY_LIMIT) -> list[str]:
    """Top-N recent memories, newest first. Never raises — degrades to []."""
    try:
        from kv_cache.cold.supabase_client import get_supabase

        resp = (
            get_supabase()
            .table("memories")
            .select("content")
            .eq("category", category)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return [r["content"] for r in (resp.data or []) if r.get("content")]
    except Exception as exc:
        logger.warning("memory fetch skipped: %s", exc)
        return []


async def _fetch_rag_chunks(question: str, top_k: int = _RAG_TOP_K) -> list[str]:
    """Top-K RAG chunks formatted one-per-string. Never raises — degrades to []."""
    try:
        from data_pipeline.rag_pipeline.rag import retrieve

        chunks = await retrieve(question, top_k=top_k)
        formatted: list[str] = []
        for c in chunks:
            src = c.get("source", "?")
            # RPC column is `chunk_text`; support `text` for other shapers.
            txt = (c.get("chunk_text") or c.get("text") or "").strip()
            if txt:
                formatted.append(f"[{src}]\n{txt}")
        return formatted
    except Exception as exc:
        logger.warning("rag retrieve skipped: %s", exc)
        return []


async def assemble_system_prompt(
    message: str,
    *,
    task_type: str = "chat",
    identity_id: str = "john",
) -> str:
    """One-shot async assembly for request-path callers (/v1/chat, /v1/task).

    Fetches memories + RAG in parallel, then composes via build_system_prompt.
    Both fetches degrade silently — a Supabase outage never breaks chat.
    """
    import asyncio

    # Voice turns prioritize latency: skip memory/RAG retrieval (soul-only prompt).
    # Each retrieval adds ~3-5s via nomic-embed + Supabase round-trips.
    if task_type == "voice":
        return build_system_prompt(task_type=task_type, identity_id=identity_id)

    # Avatar chat: load memories (personality continuity) but skip RAG (latency).
    if task_type == "avatar":
        memories = await _fetch_memories()
        return build_system_prompt(task_type=task_type, identity_id=identity_id, memories=memories)

    memories, rag_chunks = await asyncio.gather(
        _fetch_memories(),
        _fetch_rag_chunks(message),
    )
    return build_system_prompt(
        task_type=task_type,
        identity_id=identity_id,
        memories=memories,
        rag_chunks=rag_chunks,
    )