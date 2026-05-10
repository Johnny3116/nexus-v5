"""Nexus Supabase client — canonical memory read/write module.

Provides a lazy singleton client and clean wrappers for the two
memory tables:
  - memories       — persistent Nexus memories (category: server/user/system/learned)
  - agent_memories — conversation-derived agent memories (free-form category)

All functions are synchronous (supabase-py sync client).
Callers in async contexts should run these in a thread executor.

Usage:
    from supabase_client import memory_read, memory_upsert
    rows = memory_read(category="learned")
    memory_upsert("my-key", "my content", category="learned")
"""
from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger("nexus.supabase_client")

_client: Any = None


def get_client() -> Any:
    """Return a process-wide Supabase client (lazy singleton).

    Reads SUPABASE_URL and SUPABASE_KEY from environment.
    Raises RuntimeError if either is missing.
    """
    global _client
    if _client is not None:
        return _client

    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")
    if not url or not key:
        raise RuntimeError(
            "SUPABASE_URL or SUPABASE_KEY not set — check .env"
        )

    try:
        from supabase import create_client  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "supabase-py not installed — run: pip install supabase"
        ) from exc

    _client = create_client(url, key)
    logger.info("supabase client initialized (project: %s)", url.split(".")[0].split("//")[-1])
    return _client


# ---------------------------------------------------------------------------
# memories table
# ---------------------------------------------------------------------------

def memory_read(
    *,
    category: str | None = None,
    key: str | None = None,
    limit: int = 100,
) -> list[dict]:
    """Read rows from the `memories` table.

    Args:
        category: Filter by category (server/user/system/learned).
        key: Filter by exact key.
        limit: Max rows to return (default 100).

    Returns:
        List of row dicts with all columns.
    """
    client = get_client()
    q = client.table("memories").select("*").order("updated_at", desc=True).limit(limit)
    if category:
        q = q.eq("category", category)
    if key:
        q = q.eq("key", key)
    resp = q.execute()
    return resp.data or []


def memory_upsert(
    key: str,
    content: str,
    *,
    category: str = "learned",
    metadata: dict | None = None,
) -> dict:
    """Write or update a row in the `memories` table.

    If a row with matching `key` exists, updates it.
    Otherwise inserts a new row.

    Args:
        key: Unique identifier string.
        content: The memory content.
        category: One of server/user/system/learned (default: learned).
        metadata: Optional JSON metadata dict.

    Returns:
        The upserted row dict.
    """
    client = get_client()
    if metadata is None:
        metadata = {}

    # Check if row exists
    existing = client.table("memories").select("id").eq("key", key).execute()
    if existing.data:
        row_id = existing.data[0]["id"]
        resp = (
            client.table("memories")
            .update({"content": content, "category": category, "metadata": metadata})
            .eq("id", row_id)
            .execute()
        )
    else:
        resp = (
            client.table("memories")
            .insert({"key": key, "content": content, "category": category, "metadata": metadata})
            .execute()
        )

    if not resp.data:
        raise RuntimeError(f"memory_upsert({key!r}) returned no data")
    logger.debug("memory_upsert: key=%r category=%r", key, category)
    return resp.data[0]


def memory_delete(key: str) -> int:
    """Delete all memories rows matching `key`. Returns deleted count."""
    client = get_client()
    resp = client.table("memories").delete().eq("key", key).execute()
    return len(resp.data) if resp.data else 0


# ---------------------------------------------------------------------------
# agent_memories table
# ---------------------------------------------------------------------------

def agent_memory_read(
    *,
    category: str | None = None,
    key: str | None = None,
    limit: int = 50,
) -> list[dict]:
    """Read rows from the `agent_memories` table.

    Args:
        category: Filter by category (free-form).
        key: Filter by exact key.
        limit: Max rows to return.

    Returns:
        List of row dicts.
    """
    client = get_client()
    q = (
        client.table("agent_memories")
        .select("*")
        .order("updated_at", desc=True)
        .limit(limit)
    )
    if category:
        q = q.eq("category", category)
    if key:
        q = q.eq("key", key)
    resp = q.execute()
    return resp.data or []


def agent_memory_upsert(
    key: str,
    content: str,
    *,
    category: str,
    metadata: dict | None = None,
) -> dict:
    """Write or update a row in the `agent_memories` table.

    If a row with matching `key` exists, updates it.
    Otherwise inserts a new row.

    Args:
        key: Unique identifier string.
        content: The memory content.
        category: Free-form category string (e.g. 'user_preference', 'game_state').
        metadata: Optional JSON metadata dict.

    Returns:
        The upserted row dict.
    """
    client = get_client()
    if metadata is None:
        metadata = {}

    existing = client.table("agent_memories").select("id").eq("key", key).execute()
    if existing.data:
        row_id = existing.data[0]["id"]
        resp = (
            client.table("agent_memories")
            .update({"content": content, "category": category, "metadata": metadata})
            .eq("id", row_id)
            .execute()
        )
    else:
        resp = (
            client.table("agent_memories")
            .insert({"key": key, "content": content, "category": category, "metadata": metadata})
            .execute()
        )

    if not resp.data:
        raise RuntimeError(f"agent_memory_upsert({key!r}) returned no data")
    logger.debug("agent_memory_upsert: key=%r category=%r", key, category)
    return resp.data[0]


def agent_memory_delete(key: str) -> int:
    """Delete all agent_memories rows matching `key`. Returns deleted count."""
    client = get_client()
    resp = client.table("agent_memories").delete().eq("key", key).execute()
    return len(resp.data) if resp.data else 0
