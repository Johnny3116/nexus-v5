"""Safety tier definitions and enforcement policy.

Tiers determine whether a skill action can auto-execute or must be routed
through the approval queue. This is a hard gate — not optional.

Tier hierarchy (least to most restrictive):
    READ_ONLY        → auto-execute, no log required (but recommended)
    NON_DESTRUCTIVE  → auto-execute, write to automation_history
    DESTRUCTIVE      → approval queue when triggered by automation sources
    CRITICAL         → always requires explicit human approval

From doctrines.md: DESTRUCTIVE and CRITICAL actions triggered by automation
(cron, heartbeat, reflex) ALWAYS go to the approval queue. Only a human-
initiated request can bypass the queue for DESTRUCTIVE — never CRITICAL.
"""

from __future__ import annotations

from enum import Enum


class SafetyTier(str, Enum):
    READ_ONLY = "READ_ONLY"
    NON_DESTRUCTIVE = "NON_DESTRUCTIVE"
    DESTRUCTIVE = "DESTRUCTIVE"
    CRITICAL = "CRITICAL"


class TaskSource(str, Enum):
    HUMAN = "human"
    HEARTBEAT = "heartbeat"
    CRON = "cron"
    REFLEX = "reflex"
    AUTOMATION = "automation"


AUTOMATED_SOURCES = {
    TaskSource.HEARTBEAT,
    TaskSource.CRON,
    TaskSource.REFLEX,
    TaskSource.AUTOMATION,
}


def requires_approval(tier: SafetyTier, source: TaskSource) -> bool:
    """Return True if this tier + source combination must go through approval."""
    if tier == SafetyTier.CRITICAL:
        return True
    if tier == SafetyTier.DESTRUCTIVE and source in AUTOMATED_SOURCES:
        return True
    return False


def can_auto_execute(tier: SafetyTier, source: TaskSource) -> bool:
    return not requires_approval(tier, source)


TIER_DESCRIPTIONS = {
    SafetyTier.READ_ONLY: "Read-only operation. Auto-executes without logging.",
    SafetyTier.NON_DESTRUCTIVE: "Write operation with no permanent side effects. Auto-executes with audit log.",
    SafetyTier.DESTRUCTIVE: "Modifies or deletes state. Requires approval when triggered by automation.",
    SafetyTier.CRITICAL: "System-critical or irreversible. Always requires explicit human approval.",
}
