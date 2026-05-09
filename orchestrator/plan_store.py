"""plan_store.py — in-memory registry of pending Plans awaiting user approval.

Plans are ephemeral session state. They live only while the server is running.
A plan that hasn't been approved or rejected is just a pending intent — nothing
has been executed yet and nothing will be until the user explicitly approves.

Milestone 3 hard limits:
    - Approval does not execute anything
    - No file writes
    - No Codex / Sonnet calls
    - Plans expire on server restart (intentional)
"""

from __future__ import annotations

import logging
import uuid
from typing import Optional

logger = logging.getLogger(__name__)

# plan_id -> {"plan": dict, "task_packet": dict, "route": str, "confidence": float}
_pending: dict[str, dict] = {}


def register(plan: dict, task_packet: dict, route: str, confidence: float, revision_round: int = 0) -> str:
    """Store a pending plan and return its plan_id."""
    plan_id = str(uuid.uuid4())
    _pending[plan_id] = {
        "plan_id": plan_id,
        "plan": plan,
        "task_packet": task_packet,
        "route": route,
        "confidence": confidence,
        "revision_round": revision_round,
    }
    logger.info("Plan registered: %s | goal=%.60s", plan_id, task_packet.get("goal", ""))
    return plan_id


def get(plan_id: str) -> Optional[dict]:
    """Return a pending plan entry or None if not found / already decided."""
    return _pending.get(plan_id)


def consume(plan_id: str) -> Optional[dict]:
    """Remove and return a pending plan (used when user approves or rejects)."""
    entry = _pending.pop(plan_id, None)
    if entry is None:
        logger.warning("plan_decision for unknown plan_id: %s", plan_id)
    return entry


def pending_count() -> int:
    return len(_pending)
