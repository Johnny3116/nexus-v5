"""memory/ — Typed memory layers for the Nexus planning pipeline.

Exports the public API; import from here, not from submodules.

Usage:
    from memory import build_planning_context, PlanningContext, WorkspaceState
    ctx = build_planning_context(task_goal="build X")
    ctx.to_context_text()   # inject into planner prompt
    ctx.summary()           # log / plan_response context_summary
"""

from .assembler import build_planning_context
from .layers import PlanningContext, RecentManifest, WorkspaceFile, WorkspaceState

__all__ = [
    "build_planning_context",
    "PlanningContext",
    "WorkspaceState",
    "WorkspaceFile",
    "RecentManifest",
]
