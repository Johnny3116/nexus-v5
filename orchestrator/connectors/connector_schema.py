"""Connector schema - Pydantic models for the connector registry."""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class DangerLevel(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"


class ConnectorAction(str, Enum):
    search = "search"
    read = "read"
    write = "write"
    delete = "delete"
    list = "list"
    execute = "execute"


class ConnectorMeta(BaseModel):
    id: str
    name: str
    description: str = ""
    enabled: bool = True
    actions: list[ConnectorAction] = Field(default_factory=list)
    danger_level: DangerLevel = DangerLevel.low
    requires_confirmation: bool = False


class ConnectorStatus(BaseModel):
    id: str
    name: str
    enabled: bool
    healthy: bool
    actions: list[str]
    danger_level: str
    requires_confirmation: bool
    error: Optional[str] = None


class ConnectorRunRequest(BaseModel):
    action: str
    params: dict[str, Any] = Field(default_factory=dict)


class ConnectorRunResponse(BaseModel):
    connector_id: str
    action: str
    success: bool
    data: Any = None
    error: Optional[str] = None
    row_count: Optional[int] = None
