"""Minimal Supabase client — shared by api_gateway and observability.

Wraps `supabase-py` so callers get a lazily-constructed singleton without
each module re-reading env vars. Phase 3 replaces this with a proper async
wrapper (supabase-py's official async client when it stabilizes).
"""

from __future__ import annotations

import logging
from typing import Any

from api_gateway.config.settings import get_settings

logger = logging.getLogger("nexus.kv_cache.cold.supabase")


_client: Any = None


def get_supabase() -> Any:
    """Return a process-wide Supabase client instance.

    Raises RuntimeError if Supabase is not configured. Callers in
    hot paths should catch + log + degrade rather than crash.
    """
    global _client
    if _client is not None:
        return _client

    settings = get_settings()
    if not (settings.supabase_url and settings.supabase_service_key):
        raise RuntimeError("supabase_url / supabase_service_key not configured")

    try:
        from supabase import create_client  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "supabase-py not installed — add `supabase` to requirements.txt"
        ) from exc

    _client = create_client(settings.supabase_url, settings.supabase_service_key)
    logger.info("supabase client initialized")
    return _client
