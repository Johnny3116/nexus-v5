"""Supabase Connector - read/write access to Nexus Supabase tables.

All credentials stay server-side. Table allowlist prevents arbitrary access.
"""

from __future__ import annotations

import logging
from typing import Any

from orchestrator.connectors.connector_schema import (
    ConnectorAction, ConnectorMeta, ConnectorRunResponse, DangerLevel,
)
from orchestrator.connectors.registry import register

logger = logging.getLogger("nexus.connectors.supabase")

_ALLOWED_TABLES = {
    "memories", "agent_memories", "session_summaries", "tasks",
    "incidents", "decisions", "entity_facts", "relationships",
    "projects", "pinned_memories",
    "game_notes", "game_builds", "game_currencies", "games",
    "anime_series", "anime_notes", "anime_characters",
}

_MAX_LIMIT = 100


def _validate_table(table: str) -> None:
    if table not in _ALLOWED_TABLES:
        raise ValueError(f"Table {table!r} not in allowlist. Allowed: {sorted(_ALLOWED_TABLES)}")


def _get_client():
    from kv_cache.cold.supabase_client import get_supabase
    return get_supabase()


class SupabaseConnector:
    meta = ConnectorMeta(
        id="supabase", name="Supabase Memory",
        description="Read/write access to Nexus Supabase tables.",
        enabled=True,
        actions=[ConnectorAction.search, ConnectorAction.read,
                 ConnectorAction.write, ConnectorAction.list],
        danger_level=DangerLevel.medium, requires_confirmation=False,
    )

    def health_check(self) -> bool:
        try:
            client = _get_client()
            resp = client.table("memories").select("id").limit(1).execute()
            return resp.data is not None
        except Exception:
            return False

    async def run(self, action: str, params: dict[str, Any]) -> ConnectorRunResponse:
        try:
            if action == "search":
                return await self._search(params)
            elif action == "read":
                return await self._read(params)
            elif action == "write":
                return await self._write(params)
            elif action == "list":
                return await self._list_tables(params)
            else:
                return ConnectorRunResponse(
                    connector_id="supabase", action=action,
                    success=False, error=f"Unknown action: {action}",
                )
        except ValueError as exc:
            return ConnectorRunResponse(
                connector_id="supabase", action=action,
                success=False, error=str(exc),
            )
        except Exception as exc:
            logger.exception("Supabase connector error: %s", exc)
            return ConnectorRunResponse(
                connector_id="supabase", action=action,
                success=False, error=f"Supabase error: {exc}",
            )

    async def _search(self, params: dict[str, Any]) -> ConnectorRunResponse:
        table = params.get("table", "memories")
        query = params.get("query", "")
        limit = min(params.get("limit", 20), _MAX_LIMIT)
        columns = params.get("columns", "*")
        search_col = params.get("search_column", "content")
        if not query:
            return ConnectorRunResponse(
                connector_id="supabase", action="search",
                success=False, error="Missing query parameter",
            )
        _validate_table(table)
        client = _get_client()
        resp = (client.table(table).select(columns)
                .ilike(search_col, f"%{query}%")
                .order("created_at", desc=True).limit(limit).execute())
        rows = resp.data or []
        return ConnectorRunResponse(
            connector_id="supabase", action="search",
            success=True, data=rows, row_count=len(rows),
        )

    async def _read(self, params: dict[str, Any]) -> ConnectorRunResponse:
        table = params.get("table", "memories")
        columns = params.get("columns", "*")
        filters = params.get("filters", {})
        order_by = params.get("order_by", "created_at")
        order_desc = params.get("order_desc", True)
        limit = min(params.get("limit", 20), _MAX_LIMIT)
        _validate_table(table)
        client = _get_client()
        q = client.table(table).select(columns)
        for col, val in filters.items():
            if isinstance(val, list):
                q = q.in_(col, val)
            else:
                q = q.eq(col, val)
        q = q.order(order_by, desc=order_desc).limit(limit)
        resp = q.execute()
        rows = resp.data or []
        return ConnectorRunResponse(
            connector_id="supabase", action="read",
            success=True, data=rows, row_count=len(rows),
        )

    async def _write(self, params: dict[str, Any]) -> ConnectorRunResponse:
        table = params.get("table")
        rows = params.get("rows")
        upsert = params.get("upsert", False)
        if not table:
            return ConnectorRunResponse(
                connector_id="supabase", action="write",
                success=False, error="Missing table parameter",
            )
        if not rows or not isinstance(rows, list):
            return ConnectorRunResponse(
                connector_id="supabase", action="write",
                success=False, error="rows must be a non-empty list of dicts",
            )
        if len(rows) > 50:
            return ConnectorRunResponse(
                connector_id="supabase", action="write",
                success=False, error="Max 50 rows per write",
            )
        _validate_table(table)
        client = _get_client()
        if upsert:
            resp = client.table(table).upsert(rows).execute()
        else:
            resp = client.table(table).insert(rows).execute()
        written = resp.data or []
        return ConnectorRunResponse(
            connector_id="supabase", action="write",
            success=True, data=written, row_count=len(written),
        )

    async def _list_tables(self, params: dict[str, Any]) -> ConnectorRunResponse:
        client = _get_client()
        table_info = []
        for t in sorted(_ALLOWED_TABLES):
            try:
                resp = client.table(t).select("id", count="exact").limit(0).execute()
                count = resp.count if hasattr(resp, "count") and resp.count is not None else "unknown"
                table_info.append({"table": t, "accessible": True, "row_count": count})
            except Exception as exc:
                table_info.append({"table": t, "accessible": False, "error": str(exc)})
        return ConnectorRunResponse(
            connector_id="supabase", action="list",
            success=True, data=table_info, row_count=len(table_info),
        )


_instance = SupabaseConnector()
register(_instance)
