"""RAG retrieval — embed query via Ollama nomic-embed-text, search knowledge_embeddings.

This is the `retrieve()` implementation imported by
`serving.brain_pool.prompt_builder._fetch_rag_chunks`. It degrades silently:
if Ollama is unreachable, or the Supabase RPC fails, it returns [] so the
chat pipeline continues with soul-only context.

knowledge_embeddings uses 768-dim nomic-embed-text vectors.
match_knowledge(query_embedding, match_threshold, match_count) returns:
  id, source, chunk_text, heading, similarity
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

logger = logging.getLogger("nexus.rag")

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
_EMBED_MODEL = os.getenv("RAG_EMBED_MODEL", "nomic-embed-text")
_MATCH_THRESHOLD = float(os.getenv("RAG_MATCH_THRESHOLD", "0.7"))
# Keep the embed timeout tight — RAG adds latency to every chat call.
# If Ollama is slow, we'd rather skip RAG than stall the response.
_HTTP_TIMEOUT = 8.0


async def _embed(text: str) -> list[float] | None:
    """Return a 768-dim embedding from Ollama. None on any failure."""
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            resp = await client.post(
                f"{OLLAMA_URL}/api/embed",
                json={"model": _EMBED_MODEL, "input": text},
            )
            resp.raise_for_status()
            data = resp.json()
            # /api/embed returns {"embeddings": [[...]]} for a single input.
            # Older /api/embeddings (singular) returns {"embedding": [...]}.
            embeddings = data.get("embeddings") or data.get("embedding")
            if isinstance(embeddings, list) and embeddings:
                first = embeddings[0]
                # Nested list → unwrap; flat list of floats → use directly.
                return first if isinstance(first, list) else embeddings
    except Exception as exc:
        logger.debug("embed failed (%s) — RAG will be skipped", exc)
    return None


async def retrieve(question: str, top_k: int = 5) -> list[dict[str, Any]]:
    """Return top-K knowledge chunks semantically relevant to `question`.

    Each chunk is a dict: {source, chunk_text, heading, similarity}.
    Returns [] on any failure — never raises.
    """
    embedding = await _embed(question)
    if embedding is None:
        return []

    try:
        from kv_cache.cold.supabase_client import get_supabase

        resp = (
            get_supabase()
            .rpc(
                "match_knowledge",
                {
                    "query_embedding": embedding,
                    "match_threshold": _MATCH_THRESHOLD,
                    "match_count": top_k,
                },
            )
            .execute()
        )
        return [
            {
                "source": row.get("source", "?"),
                "chunk_text": row.get("chunk_text", ""),
                "heading": row.get("heading", ""),
                "similarity": row.get("similarity", 0.0),
            }
            for row in (resp.data or [])
            if row.get("chunk_text")
        ]
    except Exception as exc:
        logger.warning("knowledge retrieval failed: %s", exc)
        return []
