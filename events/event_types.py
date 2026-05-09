"""event_types.py -- EventType enum and Event dataclass for the Nexus event bus."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum


class EventType(str, Enum):
    """All event types emitted by the Nexus pipeline.

    Naming: <domain>.<action>  (dot-separated, lowercase)
    """
    # Planning
    PLAN_CREATED = "plan.created"     # new plan generated, awaiting approval
    PLAN_REVISED = "plan.revised"     # user requested revision, new plan produced
    PLAN_APPROVED = "plan.approved"   # user approved a plan, builder launching
    PLAN_REJECTED = "plan.rejected"   # user rejected a plan

    # Build attempts
    BUILD_STARTED = "build.started"           # builder selected, first attempt beginning
    BUILD_ATTEMPT_FAILED = "build.attempt_failed"  # single attempt failed (not final)
    BUILD_RETRIED = "build.retried"           # retrying after a failure
    BUILD_COMPLETE = "build.complete"         # final result (success or failure)

    # Test execution
    TEST_PASSED = "test.passed"   # tests ran and passed
    TEST_FAILED = "test.failed"   # tests ran and failed (attempt-level)

    # Workspace
    WORKSPACE_WRITTEN = "workspace.written"  # files committed to workspace/output/

    # Future (defined now, subscribers wired when needed)
    MEMORY_PROMOTED = "memory.promoted"  # a memory candidate was promoted
    AGENT_TIMEOUT = "agent.timeout"      # an agent call exceeded its timeout


@dataclass
class Event:
    """A single event emitted on the Nexus event bus.

    Attributes:
        type:     EventType enum value identifying the event.
        plan_id:  Associated plan UUID (empty string if not plan-related).
        data:     Event-specific payload dict. Schema varies per EventType.
        ts:       Unix timestamp (float, seconds since epoch). Set automatically.
    """
    type: EventType
    plan_id: str = ""
    data: dict = field(default_factory=dict)
    ts: float = field(default_factory=time.time)
