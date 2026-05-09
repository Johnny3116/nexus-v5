"""Plan schema — the structured output of Nexus's planning phase.

A Plan is generated from a TaskPacket by planner.py and returned to the
user for review before any builder agent touches code. requires_user_approval
is always True in Milestone 2 — no autorun.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import List


@dataclass
class Plan:
    summary: str
    assumptions: List[str]
    target_files: List[str]
    implementation_steps: List[str]
    risks: List[str]
    rollback_plan: str
    acceptance_tests: List[str]
    verification_commands: List[str]
    requires_user_approval: bool = True

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)
