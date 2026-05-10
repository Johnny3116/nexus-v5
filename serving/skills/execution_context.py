"""Execution context — passed to every skill's execute() method."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from safety.output_filters.safety_tier_gate import TaskSource


@dataclass
class ExecutionContext:
    skill_name: str
    action: str
    params: dict[str, Any] = field(default_factory=dict)
    source: TaskSource = TaskSource.HUMAN
    iteration: int = 1
    conversation_id: Optional[str] = None
    request_id: Optional[str] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)

    def get_param(self, key: str, default: Any = None) -> Any:
        return self.params.get(key, default)

    def require_param(self, key: str) -> Any:
        if key not in self.params:
            raise ValueError(f"Required parameter '{key}' missing")
        return self.params[key]
