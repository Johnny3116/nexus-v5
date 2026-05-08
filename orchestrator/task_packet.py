"""
TaskPacket — the structured contract between Nexus and planning/build agents.

Every dev task starts as a TaskPacket. Nexus builds it, Codex reads it to produce
a plan, Sonnet reads the approved plan to implement. Nothing moves without one.
"""

from dataclasses import dataclass, field, asdict
from typing import Optional
import json


@dataclass
class TaskPacket:
    goal: str                              # What needs to happen, one sentence
    repo: str                              # Repo name and relevant path
    constraints: list[str] = field(default_factory=list)  # Hard limits
    files_likely_involved: list[str] = field(default_factory=list)
    acceptance_tests: list[str] = field(default_factory=list)  # Binary testable
    do_not_touch: list[str] = field(default_factory=list)
    required_output: str = "PLAN.md"       # PLAN.md | diff | PR | code only
    context: Optional[str] = None          # Extra context for the planner
    task_id: Optional[str] = None          # Auto-assigned by orchestrator

    def to_prompt(self) -> str:
        """Render as a planning prompt for Codex."""
        lines = [
            "# Task Packet",
            "",
            f"**Goal:** {self.goal}",
            f"**Repo:** {self.repo}",
            f"**Required output:** {self.required_output}",
            "",
            "**Constraints:**",
            *[f"- {c}" for c in self.constraints] or ["- None specified"],
            "",
            "**Files likely involved:**",
            *[f"- {f}" for f in self.files_likely_involved] or ["- Unknown — use repo inspection"],
            "",
            "**Acceptance tests:**",
            *[f"- [ ] {t}" for t in self.acceptance_tests] or ["- None specified — define before building"],
            "",
            "**Do not touch:**",
            *[f"- {f}" for f in self.do_not_touch] or ["- None specified"],
        ]
        if self.context:
            lines += ["", "**Additional context:**", self.context]
        return "\n".join(lines)

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)

    @classmethod
    def from_json(cls, data: str) -> "TaskPacket":
        return cls(**json.loads(data))


# Example usage:
if __name__ == "__main__":
    packet = TaskPacket(
        goal="Add memory search to Discord bot",
        repo="Nexus / chat/",
        constraints=[
            "No breaking changes to existing message handling",
            "Must use existing Supabase connection",
        ],
        files_likely_involved=[
            "chat/discord_bot.py",
            "chat/history/",
        ],
        acceptance_tests=[
            "Bot responds with relevant past context when asked about previous topics",
            "Memory search does not add more than 500ms to response time",
            "Existing message flow unchanged for non-memory queries",
        ],
        do_not_touch=[
            "serving/",
            "safety/identity/soul.md",
            "voicebox/",
        ],
        required_output="PLAN.md",
    )
    print(packet.to_prompt())
