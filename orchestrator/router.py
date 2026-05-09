"""Nexus V5 Router — classifies incoming messages into intent types.

Phase 1: rule-based matching. Phase 2 will replace this with an
Ollama-backed classifier so Nexus can reason about intent herself.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

logger = logging.getLogger(__name__)

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


# --- Trigger word lists ---

_CODE_PLAN_TRIGGERS = [
    "plan", "implement", "build", "refactor", "add feature",
    "wire", "create", "repo", "github", "task packet",
    "fix bug", "fix the", "add a", "add to", "update the",
    "integrate", "migrate", "write a", "write the",
]

_ADMIN_TRIGGERS = [
    "restart", "status", "health check", "is it running",
    "check the bot", "service", "scheduled task",
    "avatar server", "discord bot", "telegram bot", "ollama",
]

_MEMORY_TRIGGERS = [
    "remember", "forget", "recall", "memory", "memorize",
    "store this", "save this", "look up what", "what did",
    "last time", "you said", "we discussed",
]

_AVATAR_TRIGGERS = [
    "animate", "animation", "pose", "expression",
    "lipsync", "say out loud", "speak out loud",
]

_SKILL_TRIGGERS = [
    "run skill", "use skill", "invoke skill", "call skill",
    "execute skill",
]

_CODE_BUILD_TRIGGERS = [
    "implement from", "build from", "execute plan",
    "run the plan", "apply plan", "plan approved", "plan.md",
]


def classify_message(message: str) -> RouteDecision:
    """Classify a message into a route type.

    Returns RouteDecision with route, confidence, and reason.
    First match wins — order of checks encodes priority.
    """
    text = message.lower().strip()

    if any(t in text for t in _ADMIN_TRIGGERS):
        return RouteDecision(
            route="admin",
            confidence=0.80,
            reason="Message contains admin/system-status keywords.",
        )

    if any(t in text for t in _MEMORY_TRIGGERS):
        return RouteDecision(
            route="memory",
            confidence=0.80,
            reason="Message contains memory operation keywords.",
        )

    if any(t in text for t in _AVATAR_TRIGGERS):
        return RouteDecision(
            route="avatar",
            confidence=0.80,
            reason="Message contains avatar control keywords.",
        )

    if any(t in text for t in _CODE_BUILD_TRIGGERS):
        return RouteDecision(
            route="code_build",
            confidence=0.80,
            reason="Message references an existing plan to execute.",
        )

    if any(t in text for t in _SKILL_TRIGGERS):
        return RouteDecision(
            route="skill",
            confidence=0.80,
            reason="Message requests skill invocation by name.",
        )

    if any(t in text for t in _CODE_PLAN_TRIGGERS):
        return RouteDecision(
            route="code_plan",
            confidence=0.75,
            reason="Message appears to request planning or implementation work.",
            requires_task_packet=True,
        )

    return RouteDecision(
        route="chat",
        confidence=0.60,
        reason="No specific intent pattern matched — defaulting to chat.",
    )


if __name__ == "__main__":
    tests = [
        "Add memory search to the Discord bot",
        "What's the status of the avatar server?",
        "Can you remember that I prefer short responses?",
        "Implement from the approved plan",
        "Build a router that classifies requests",
        "What do you think about spiders?",
        "Fix the bug in telegram_bot.py where messages get cut off",
        "Wire router.py into the avatar server",
    ]
    for t in tests:
        r = classify_message(t)
        print(f"[{r.route:<12}] ({r.confidence:.2f}) {t}")
