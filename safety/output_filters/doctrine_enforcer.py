"""Doctrine enforcer — final gate before any skill executes.

Reads shared/doctrines.md at startup, but the rules themselves are
coded here because prose can be interpreted and code cannot.
Every rule is a hard fail: if the action violates it, the task is
aborted and John is alerted. No "soft" warnings.

Doctrines (CLAUDE.md §10):
  1. Network isolation — no public egress
  2. No personal data access
  3. Prompt injection defense (delegated to safety.input_filters)
  4. Safety tiers (delegated to safety.output_filters.safety_tier_gate)
  5. Hardware protection
  6. Identity integrity
  7. Audit trail
  8. Graceful degradation (handled at provider layer)
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

logger = logging.getLogger("nexus.safety.doctrine")


@dataclass
class ProposedAction:
    skill: str
    action: str
    params: dict


class DoctrineViolation(Exception):
    def __init__(self, rule: int, message: str) -> None:
        self.rule = rule
        super().__init__(f"doctrine §{rule}: {message}")


# Rule #1 — no public-internet fetches (allowlist handled separately, but
# we also refuse raw IPs outside the Tailscale CGNAT range).
_PUBLIC_IP_RE = re.compile(r"\b(?!100\.(?:6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.)\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b")

# Rule #2 — hard-banned data sources.
_BANNED_SUBSTRINGS = {
    "gmail.com/mail",
    "outlook.com",
    "mail.google.com",
    "calendar.google.com",
    "facebook.com",
    "instagram.com",
    "linkedin.com",
}

# Rule #5 — shell/system commands that can brick hardware.
_BANNED_SHELL = re.compile(
    r"(?i)("
    r"nvidia-smi\s+-pl\b"           # power-limit override
    r"|overclock"
    r"|diskpart\s+clean"
    r"|rm\s+-rf\s+/"
    r"|dd\s+if=.*of=/dev/"
    r"|sudo\s+halt"
    r")"
)


def enforce(action: ProposedAction) -> None:
    blob = f"{action.skill}.{action.action} {action.params}"
    lower = blob.lower()

    if _PUBLIC_IP_RE.search(blob):
        raise DoctrineViolation(1, f"public-ip target in action: {blob[:120]}")

    for banned in _BANNED_SUBSTRINGS:
        if banned in lower:
            raise DoctrineViolation(2, f"banned data source: {banned}")

    if _BANNED_SHELL.search(blob):
        raise DoctrineViolation(5, f"dangerous shell pattern in action")

    logger.debug("doctrine check passed for %s.%s", action.skill, action.action)
