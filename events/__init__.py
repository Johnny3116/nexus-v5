"""Nexus event bus — publish/subscribe for build pipeline events.

Usage:
    from events import publish, subscribe, Event, EventType

    subscribe(EventType.BUILD_COMPLETE, my_handler)
    await publish(Event(type=EventType.BUILD_COMPLETE, plan_id="...", data={...}))
"""
from events.event_bus import publish, subscribe, subscribe_all, clear
from events.event_types import Event, EventType

__all__ = ["publish", "subscribe", "subscribe_all", "clear", "Event", "EventType"]
