"""memory/assembler.py — builds a PlanningContext from all local memory layers.

Drop-in replacement for:
    context_reader.gather_context(task_packet)  +  format_context_for_prompt(ctx)

Usage:
    from memory import build_planning_context
    ctx = build_planning_context(task_goal="build a calculator")
    context_text = ctx.to_context_text()
    context_summary = ctx.summary()

Hard limits (inherited from M6 context_reader):
  - Read-only: no file writes, no shell execution, no external calls
  - Max context: ~2 KB injected into planner prompt
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from .layers import PlanningContext, RecentManifest, WorkspaceFile, WorkspaceState

logger = logging.getLogger(__name__)

_NEXUS_ROOT = Path(__file__).resolve().parents[1]
_WORKSPACE_OUTPUT = _NEXUS_ROOT / "workspace" / "output"
_WORKSPACE_MANIFESTS = _NEXUS_ROOT / "workspace" / "manifests"
_BUILD_LOG = _NEXUS_ROOT / "workspace" / "build_log.json"

_MAX_FILE_CHARS = 800
_MAX_LOG_ENTRIES = 3
_MAX_MANIFESTS = 3
_MAX_SNIPPETS = 3


def _read_workspace_state() -> WorkspaceState:
    """Snapshot workspace/output/ files and recent manifests."""
    output_files: list[WorkspaceFile] = []
    if _WORKSPACE_OUTPUT.exists():
        for p in sorted(_WORKSPACE_OUTPUT.rglob("*")):
            if p.is_file():
                try:
                    output_files.append(WorkspaceFile(name=p.name, size_bytes=p.stat().st_size))
                except Exception:
                    output_files.append(WorkspaceFile(name=p.name, size_bytes=0))

    recent_manifests: list[RecentManifest] = []
    manifest_count = 0
    if _WORKSPACE_MANIFESTS.exists():
        paths = sorted(
            _WORKSPACE_MANIFESTS.glob("*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        manifest_count = len(paths)
        for mp in paths[:_MAX_MANIFESTS]:
            try:
                m = json.loads(mp.read_text(encoding="utf-8"))
                recent_manifests.append(RecentManifest(
                    plan_id=m.get("plan_id", ""),
                    goal=m.get("goal", ""),
                    success=bool(m.get("success", False)),
                    attempt_count=int(m.get("attempt_count", 1)),
                    builder=m.get("builder", "?"),
                    verification_status=m.get("verification_status", "?"),
                    test_status=m.get("test_status", "?"),
                ))
            except Exception:
                pass

    return WorkspaceState(
        output_files=output_files,
        recent_manifests=recent_manifests,
        manifest_count=manifest_count,
    )


def _read_build_history() -> list[dict]:
    """Return the last N raw build_log entries."""
    try:
        if not _BUILD_LOG.exists():
            return []
        entries = json.loads(_BUILD_LOG.read_text(encoding="utf-8"))
        return entries[-_MAX_LOG_ENTRIES:]
    except Exception:
        return []


def _read_nexus_structure() -> list[str]:
    """Top-level directory listing of _NEXUS_ROOT."""
    items: list[str] = []
    try:
        skip = {"__pycache__", "workspace", "voicebox", "model-registry"}
        detail = {"orchestrator", "history", "serving", "agents", "events", "memory"}
        for p in sorted(_NEXUS_ROOT.iterdir()):
            if p.name.startswith(".") or p.name in skip:
                continue
            if p.is_dir():
                if p.name in detail:
                    sub = [c.name for c in sorted(p.iterdir()) if not c.name.startswith("_")]
                    items.append(f"{p.name}/  [{', '.join(sub[:8])}]")
                else:
                    items.append(f"{p.name}/")
            elif p.suffix == ".py":
                items.append(p.name)
    except Exception as e:
        logger.debug("assembler: dir listing failed (%s)", e)
    return items


def _find_related_snippets(goal: str, files: list[WorkspaceFile]) -> list[tuple[str, str]]:
    """Find workspace files relevant to goal and return (path, snippet) pairs."""
    goal_words = set(goal.lower().split())
    related_names = []
    for f in files:
        stem_words = set(f.name.replace("_", " ").replace("-", " ").replace(".py", "").lower().split())
        if stem_words & goal_words:
            related_names.append(f.name)

    snippets: list[tuple[str, str]] = []
    for name in related_names[:_MAX_SNIPPETS]:
        abs_path = _WORKSPACE_OUTPUT / name
        try:
            abs_path.resolve().relative_to(_WORKSPACE_OUTPUT.resolve())
            content = abs_path.read_text(encoding="utf-8", errors="replace")
            if len(content) > _MAX_FILE_CHARS:
                content = content[:_MAX_FILE_CHARS] + f"\n... [truncated, {len(content)} chars]"
            rel = f"workspace/output/{name}"
            snippets.append((rel, content))
        except Exception:
            pass
    return snippets


def build_planning_context(task_goal: str = "") -> PlanningContext:
    """Build a structured PlanningContext from all local memory layers.

    This replaces the two-call pattern:
        context = gather_context(task_packet)
        context_text = format_context_for_prompt(context)

    With a single typed result:
        ctx = build_planning_context(task_goal=task_packet.get("goal", ""))
        context_text = ctx.to_context_text()
        context_summary = ctx.summary()
    """
    workspace = _read_workspace_state()
    build_history = _read_build_history()
    nexus_structure = _read_nexus_structure()
    related_snippets = _find_related_snippets(task_goal, workspace.output_files)

    ctx = PlanningContext(
        workspace=workspace,
        build_history=build_history,
        nexus_structure=nexus_structure,
        related_snippets=related_snippets,
    )
    logger.info("Planning context: %s", ctx.summary())
    return ctx
