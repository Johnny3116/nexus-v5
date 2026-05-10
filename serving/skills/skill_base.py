"""Abstract skill interface — all skills subclass SkillBase.

Safety tiers are defined in `safety.output_filters.safety_tier_gate` (single
source of truth) and imported here for convenience. The engine only calls
`execute()` and `get_capabilities()` — everything else is optional override.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from safety.output_filters.safety_tier_gate import SafetyTier  # noqa: F401 — re-export

if TYPE_CHECKING:
    from serving.skills.execution_context import ExecutionContext


class SkillBase(ABC):
    name: str = ""
    description: str = ""
    safety_tier: SafetyTier = SafetyTier.READ_ONLY
    version: str = "1.0.0"

    @abstractmethod
    async def execute(self, context: "ExecutionContext") -> dict:
        """Execute the skill. Must return at least {"success": bool}."""

    @abstractmethod
    def get_capabilities(self) -> list[dict]:
        """Return actions this skill exposes (for Brain context injection)."""

    def validate_params(self, params: dict) -> tuple[bool, str]:
        return True, ""

    def __repr__(self) -> str:
        return f"<Skill:{self.name} tier={self.safety_tier.value} v{self.version}>"
