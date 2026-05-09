"""event_bus.py -- in-process async publish/subscribe event bus.

Design:
  - Module-level subscription registry (dict of EventType -> list[Handler])
  - Handlers are async coroutines: async def my_handler(event: Event) -> None
  - publish() fan-outs to all handlers; exceptions are caught per-handler
    so one broken subscriber never blocks others or the publisher
  - No persistence, no external broker, no threads — pure asyncio

Usage:
    from events.event_bus import subscribe, publish
    from events.event_types import Event, EventType

    async def my_handler(event: Event) -> None:
        print(event.type, event.plan_id)

    subscribe(EventType.BUILD_COMPLETE, my_handler)
    await publish(Event(type=EventType.BUILD_COMPLETE, plan_id="abc"))
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Awaitable, Callable

from events.event_types import Event, EventType

logger = logging.getLogger(__name__)

Handler = Callable[[Event], Awaitable[None]]

# Per-type handlers
_handlers: dict[str, list[Handler]] = defaultdict(list)

# Global handlers — receive every event regardless of type
_global_handlers: list[Handler] = []


def subscribe(event_type: EventType | str, handler: Handler) -> None:
    """Register handler for a specific event type."""
    key = event_type.value if isinstance(event_type, EventType) else str(event_type)
    _handlers[key].append(handler)
    logger.debug("Subscribed %s to %s", getattr(handler, "__name__", repr(handler)), key)


def subscribe_all(handler: Handler) -> None:
    """Register handler for ALL event types."""
    _global_handlers.append(handler)
    logger.debug("Subscribed %s to ALL events", getattr(handler, "__name__", repr(handler)))


async def publish(event: Event) -> None:
    """Publish an event to all registered handlers.

    Handler exceptions are caught and logged — they never propagate to the publisher.
    Handlers are called sequentially in registration order.
    """
    key = event.type.value if isinstance(event.type, EventType) else str(event.type)
    handlers = _handlers.get(key, []) + _global_handlers

    for handler in handlers:
        try:
            await handler(event)
        except Exception as exc:
            logger.error(
                "Event handler %s raised on %s (plan=%s): %s",
                getattr(handler, "__name__", repr(handler)),
                event.type,
                event.plan_id,
                exc,
            )


def clear() -> None:
    """Clear all subscriptions. Primarily for testing."""
    _handlers.clear()
    _global_handlers.clear()
    logger.debug("Event bus cleared")
