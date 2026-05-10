"""WebSocket relay — fanout hub used by nexus-vtube and the avatar bridge.

Responsibilities:
  - Accept multiple client connections (VRM renderer, Discord bot, UI).
  - Broadcast state updates (vrm state, subtitle lines, audio cues) to all.
  - Route directed messages (tool requests, ASR text) to one client.

Used by avatar-pipeline/server/server.py-style hubs. Keep it generic so
both the Riko bridge and a native nexus-vtube can reuse it.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Iterable

from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger("nexus.serving.ws_relay")


@dataclass
class Hub:
    clients: set[WebSocket] = field(default_factory=set)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self.clients.add(ws)
        logger.info("ws client connected (total=%d)", len(self.clients))

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            self.clients.discard(ws)
        logger.info("ws client disconnected (total=%d)", len(self.clients))

    async def broadcast(self, event: str, data: dict) -> None:
        payload = json.dumps({"event": event, "data": data})
        dead: list[WebSocket] = []
        for c in list(self.clients):
            try:
                await c.send_text(payload)
            except Exception:
                dead.append(c)
        for c in dead:
            await self.disconnect(c)

    async def send_to(self, target: WebSocket, event: str, data: dict) -> None:
        try:
            await target.send_text(json.dumps({"event": event, "data": data}))
        except Exception:
            await self.disconnect(target)

    async def reader(self, ws: WebSocket, handler) -> None:
        """Consume messages from a client and dispatch via `handler(event, data)`."""
        try:
            while True:
                raw = await ws.receive_text()
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    await self.send_to(ws, "error", {"message": "invalid json"})
                    continue
                await handler(msg.get("event"), msg.get("data", {}))
        except WebSocketDisconnect:
            await self.disconnect(ws)
