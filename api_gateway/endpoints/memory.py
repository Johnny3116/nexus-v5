"""/v1/memory — light Supabase CRUD.

Phase 1 scope: list, add, delete. No RAG, no embeddings, no injection into
chat. Phase 3 circles back with the RAG pipeline wiring memory into
`serving/brain_pool/prompt_builder.py` and the warm cache layer.

Uses the existing `memories` table from V3/V4 Supabase — no migration.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query

from api_gateway.config.features import features
from api_gateway.shared.types import (
    MemoryCategory,
    MemoryRecord,
    MemoryRequest,
    MemoryResponse,
)
from kv_cache.cold.supabase_client import get_supabase

logger = logging.getLogger("nexus.api_gateway.endpoints.memory")

router = APIRouter(tags=["memory"])


def _require_memory_enabled() -> None:
    if not features.memory_enabled:
        raise HTTPException(status_code=503, detail="memory endpoint disabled")


@router.get("/v1/memory", response_model=MemoryResponse)
async def list_memories(
    category: MemoryCategory = Query(MemoryCategory.user),
    identity_id: str = Query("john"),
    limit: int = Query(50, ge=1, le=500),
) -> MemoryResponse:
    _require_memory_enabled()
    try:
        client = get_supabase()
        # Supabase `memories` table (phase 1) has no identity_id column yet —
        # single-user scope. Migration tracked separately.
        q = (
            client.table("memories")
            .select("*")
            .eq("category", category.value)
            .order("created_at", desc=True)
            .limit(limit)
        )
        resp = q.execute()
        rows = resp.data or []
    except Exception as exc:
        logger.exception("memory list failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"supabase read failed: {exc}")

    records = [MemoryRecord(**r) for r in rows]
    return MemoryResponse(memories=records, total=len(records))


@router.post("/v1/memory", response_model=MemoryRecord)
async def add_memory(req: MemoryRequest) -> MemoryRecord:
    _require_memory_enabled()
    try:
        client = get_supabase()
        # identity_id dropped from insert — column not yet in table (see list_memories note)
        resp = (
            client.table("memories")
            .insert(
                {
                    "content": req.content,
                    "category": req.category.value,
                    "metadata": req.metadata,
                }
            )
            .execute()
        )
        row = (resp.data or [None])[0]
        if not row:
            raise HTTPException(status_code=502, detail="supabase insert returned no row")
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("memory insert failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"supabase write failed: {exc}")

    return MemoryRecord(**row)


@router.delete("/v1/memory/{memory_id}")
async def delete_memory(memory_id: str):
    _require_memory_enabled()
    try:
        client = get_supabase()
        client.table("memories").delete().eq("id", memory_id).execute()
    except Exception as exc:
        logger.exception("memory delete failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"supabase delete failed: {exc}")
