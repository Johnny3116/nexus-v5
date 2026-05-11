"""Connector Registry - central catalog of all available connectors."""

from __future__ import annotations

import logging
from typing import Any, Protocol

from orchestrator.connectors.connector_schema import (
    ConnectorAction, ConnectorMeta, ConnectorRunResponse, ConnectorStatus,
)

logger = logging.getLogger("nexus.connectors.registry")


class Connector(Protocol):
    meta: ConnectorMeta
    def health_check(self) -> bool: ...
    async def run(self, action: str, params: dict[str, Any]) -> ConnectorRunResponse: ...


_connectors: dict[str, Connector] = {}


def register(connector: Connector) -> None:
    cid = connector.meta.id
    if cid in _connectors:
        logger.warning("Connector %r already registered - overwriting", cid)
    _connectors[cid] = connector
    logger.info("Connector registered: %s (%s) actions=%s",
                cid, connector.meta.name, [a.value for a in connector.meta.actions])


def get(connector_id: str) -> Connector | None:
    return _connectors.get(connector_id)


def list_all() -> list[ConnectorStatus]:
    results = []
    for c in _connectors.values():
        healthy = False
        error = None
        if c.meta.enabled:
            try:
                healthy = c.health_check()
            except Exception as exc:
                error = str(exc)
        results.append(ConnectorStatus(
            id=c.meta.id, name=c.meta.name, enabled=c.meta.enabled,
            healthy=healthy, actions=[a.value for a in c.meta.actions],
            danger_level=c.meta.danger_level.value,
            requires_confirmation=c.meta.requires_confirmation, error=error,
        ))
    return results


def enable(connector_id: str) -> bool:
    c = _connectors.get(connector_id)
    if c is None:
        return False
    c.meta.enabled = True
    return True


def disable(connector_id: str) -> bool:
    c = _connectors.get(connector_id)
    if c is None:
        return False
    c.meta.enabled = False
    return True
