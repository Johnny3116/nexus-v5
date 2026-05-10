"""Warm-tier conversation cache.

In-process LRU of recent (conversation_id, message[]) so we don't hit
Supabase on every brain call. Persistence remains in Supabase —
this cache is ephemeral and safe to drop on restart.
"""

from __future__ import annotations

import logging
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from threading import Lock

logger = logging.getLogger("nexus.kv_cache.warm.conversations")


@dataclass
class CachedConversation:
    conversation_id: str
    messages: list[dict] = field(default_factory=list)
    last_access: float = field(default_factory=time.time)


class ConversationCache:
    def __init__(self, capacity: int = 128, ttl_seconds: int = 3600) -> None:
        self.capacity = capacity
        self.ttl = ttl_seconds
        self._store: OrderedDict[str, CachedConversation] = OrderedDict()
        self._lock = Lock()

    def get(self, conversation_id: str) -> list[dict] | None:
        with self._lock:
            row = self._store.get(conversation_id)
            if not row:
                return None
            if time.time() - row.last_access > self.ttl:
                del self._store[conversation_id]
                return None
            row.last_access = time.time()
            self._store.move_to_end(conversation_id)
            return list(row.messages)

    def set(self, conversation_id: str, messages: list[dict]) -> None:
        with self._lock:
            self._store[conversation_id] = CachedConversation(
                conversation_id=conversation_id, messages=list(messages)
            )
            self._store.move_to_end(conversation_id)
            while len(self._store) > self.capacity:
                evicted, _ = self._store.popitem(last=False)
                logger.debug("evicted conversation %s", evicted)

    def invalidate(self, conversation_id: str) -> None:
        with self._lock:
            self._store.pop(conversation_id, None)


cache = ConversationCache()
