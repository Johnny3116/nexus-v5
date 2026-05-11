"""/v1/connectors - Connector Registry REST API.

All connector logic runs server-side. No secrets reach the browser.
"""

from __future__ import annotations

import logging
import time

from fastapi import APIRouter, HTTPException

from orchestrator.connectors import registry
from orchestrator.connectors.connector_schema import (
    ConnectorRunRequest, ConnectorRunResponse, ConnectorStatus,
)

logger = logging.getLogger("nexus.api_gateway.endpoints.connectors")

router = APIRouter(prefix="/v1/connectors", tags=["connectors"])


@router.get("", response_model=list[ConnectorStatus])
async def list_connectors() -> list[ConnectorStatus]:
    return registry.list_all()


@router.get("/{connector_id}/status", response_model=ConnectorStatus)
async def connector_status(connector_id: str) -> ConnectorStatus:
    for s in registry.list_all():
        if s.id == connector_id:
            return s
    raise HTTPException(status_code=404, detail=f"Connector {connector_id!r} not found")


@router.post("/{connector_id}/enable")
async def enable_connector(connector_id: str):
    if not registry.enable(connector_id):
        raise HTTPException(status_code=404, detail=f"Connector {connector_id!r} not found")
    return {"status": "enabled", "connector_id": connector_id}


@router.post("/{connector_id}/disable")
async def disable_connector(connector_id: str):
    if not registry.disable(connector_id):
        raise HTTPException(status_code=404, detail=f"Connector {connector_id!r} not found")
    return {"status": "disabled", "connector_id": connector_id}


@router.post("/{connector_id}/run", response_model=ConnectorRunResponse)
async def run_connector(connector_id: str, req: ConnectorRunRequest) -> ConnectorRunResponse:
    connector = registry.get(connector_id)
    if connector is None:
        raise HTTPException(status_code=404, detail=f"Connector {connector_id!r} not found")
    if not connector.meta.enabled:
        raise HTTPException(status_code=403, detail=f"Connector {connector_id!r} is disabled")
    if req.action not in [a.value for a in connector.meta.actions]:
        raise HTTPException(status_code=400,
            detail=f"Action {req.action!r} not supported. Available: {[a.value for a in connector.meta.actions]}")

    t0 = time.monotonic()
    result = await connector.run(req.action, req.params)
    elapsed_ms = int((time.monotonic() - t0) * 1000)
    logger.info("connector.run: %s.%s success=%s rows=%s %dms",
                connector_id, req.action, result.success, result.row_count, elapsed_ms)

    try:
        from events.event_bus import publish
        from events.event_types import Event, EventType
        await publish(Event(
            type=EventType.CONNECTOR_CALL,
            data={"connector_id": connector_id, "action": req.action,
                  "success": result.success, "row_count": result.row_count,
                  "elapsed_ms": elapsed_ms, "error": result.error},
        ))
    except Exception:
        pass

    return result
