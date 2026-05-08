"""
Nexus Router — classifies incoming requests into intent types.

Intent types:
  chat        → respond directly, no delegation
  skill       → invoke named skill from registry
  code-plan   → build TaskPacket, send to Codex
  code-build  → take approved PLAN.md, send to Sonnet
  memory      → query or store Supabase memory
  avatar      → trigger animation or speech
  admin       → system status, restart, config

Phase 1: rule-based classification using keywords + patterns.
Phase 2+: replace with LLM-based classification via Nexus itself.
"""

import re
from dataclasses import dataclass
from typing import Literal

IntentType = Literal["chat", "skill", "code-plan", "code-build", "memory", "avatar", "admin"]


@dataclass
class ClassifiedRequest:
    intent: IntentType
    confidence: float          # 0.0 - 1.0
    raw_input: str
    extracted_skill: str | None = None    # For intent=skill
    notes: str | None = None              # Why this classification


# Keyword patterns per intent (order matters — first match wins)
_PATTERNS: list[tuple[IntentType, list[str]]] = [
    ("admin", [
        r"\b(restart|status|service|health|task scheduler|scheduled task|is .* running|check .*bot)\b",
        r"\b(ollama|voicebox|avatar server|discord bot|telegram bot)\b.*(up|down|running|offline|broken)",
    ]),
    ("memory", [
        r"\b(remember|forget|recall|memory|memorize|store this|save this|look up what)\b",
        r"\b(what did (i|we|you) (say|discuss|talk about|work on))\b",
    ]),
    ("avatar", [
        r"\b(animate|animation|pose|expression|lipsync|speak out loud|say out loud|avatar)\b",
    ]),
    ("code-build", [
        r"\b(implement|build from|execute plan|run the plan|apply plan|plan approved)\b",
        r"PLAN\.md",
    ]),
    ("code-plan", [
        r"\b(add|implement|fix|refactor|create|build|wire|integrate|update).{0,40}\b(to|in|for|into)\b.{0,40}\b(bot|server|skill|api|endpoint|file|module|function|class)\b",
        r"\b(feature|bug|issue|task|ticket|PR|pull request|change|update)\b.{0,40}\b(in|to|for)\b.{0,40}\b(repo|code|codebase|project)\b",
    ]),
    ("skill", [
        r"\b(run|use|invoke|execute|call)\b.{0,20}\bskill\b",
    ]),
]


def classify(text: str) -> ClassifiedRequest:
    """
    Classify a request into an intent type.
    Returns ClassifiedRequest with intent, confidence, and notes.
    """
    lowered = text.lower().strip()

    for intent, patterns in _PATTERNS:
        for pattern in patterns:
            if re.search(pattern, lowered, re.IGNORECASE):
                return ClassifiedRequest(
                    intent=intent,
                    confidence=0.8,
                    raw_input=text,
                    notes=f"Matched pattern for {intent}",
                )

    # Default: chat
    return ClassifiedRequest(
        intent="chat",
        confidence=0.9,
        raw_input=text,
        notes="No specific intent pattern matched — treating as conversation",
    )


if __name__ == "__main__":
    test_cases = [
        "Add memory search to the Discord bot",
        "What's the status of the avatar server?",
        "Can you remember that I prefer short responses?",
        "Implement from the approved plan",
        "What do you think about spiders?",
        "Fix the bug in telegram_bot.py where long messages get cut off",
    ]
    for t in test_cases:
        r = classify(t)
        print(f"[{r.intent:12}] ({r.confidence:.1f}) {t[:60]}")
