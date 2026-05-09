"""Shared dataclasses for V5 orchestration layer."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Literal, Optional

RouteType = Literal[
    "chat",
    "avatar",
    "skill",
    "code_plan",
    "code_build",
    "memory",
    "admin",
    "unknown",
]


@dataclass
class RouteDecision:
    route: RouteType
    confidence: float
    reason: str
    requires_task_packet: bool = False


@dataclass
class TaskPacketInput:
    user_message: str
    repo_name: Optional[str] = None
    current_context: Optional[str] = None


@dataclass
class TaskPacket:
    goal: str
    request_type: str
    repo: Optional[str]
    constraints: list[str]
    likely_files: list[str]
    acceptance_tests: list[str]
    do_not_touch: list[str]
    required_output: str
    verification_steps: list[str]

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)
