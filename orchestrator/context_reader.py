"""context_reader.py — gathers local workspace context before planning.

Read-only. Never writes files, never executes code, never calls external services.

Context sources (in order of relevance):
  1. workspace/output/ — files previously built by the build loop
  2. build_log.json   — recent build history (goal, files, verify status)
  3. Nexus dir listing — top-level module structure (orchestrator/, history/, etc.)

Output is a context_block dict the planner injects into its prompt so it
can avoid re-implementing existing work and can reference existing modules.

Milestone 6 hard limits:
  - No file writes
  - No shell execution
  - No external calls
  - Max context: ~2 KB of text (keeps planning prompt lean)
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_NEXUS_ROOT = Path(__file__).resolve().parents[1]
_WORKSPACE_OUTPUT = _NEXUS_ROOT / "workspace" / "output"
_BUILD_LOG = _NEXUS_ROOT / "workspace" / "build_log.json"

# Max characters of any single file to include in context
_MAX_FILE_CHARS = 800
# Max number of recent build log entries to include
_MAX_LOG_ENTRIES = 3
# Max total context characters before truncation
_MAX_CONTEXT_CHARS = 2000


def _list_workspace_files() -> list[str]:
    """Return relative paths of all files in workspace/output/."""
    if not _WORKSPACE_OUTPUT.exists():
        return []
    files = []
    for p in sorted(_WORKSPACE_OUTPUT.rglob("*")):
        if p.is_file():
            try:
                files.append(str(p.relative_to(_NEXUS_ROOT)))
            except ValueError:
                files.append(str(p))
    return files


def _read_file_snippet(rel_path: str, max_chars: int = _MAX_FILE_CHARS) -> Optional[str]:
    """Read up to max_chars of a file relative to NEXUS_ROOT. Returns None on error."""
    try:
        abs_path = (_NEXUS_ROOT / rel_path).resolve()
        # Safety: must be under NEXUS_ROOT
        abs_path.relative_to(_NEXUS_ROOT)
        content = abs_path.read_text(encoding="utf-8", errors="replace")
        if len(content) > max_chars:
            return content[:max_chars] + f"\n... [truncated, {len(content)} total chars]"
        return content
    except Exception as e:
        logger.debug("context_reader: skip %s (%s)", rel_path, e)
        return None


def _recent_build_log(n: int = _MAX_LOG_ENTRIES) -> list[dict]:
    """Return the n most recent build log entries."""
    try:
        if not _BUILD_LOG.exists():
            return []
        entries = json.loads(_BUILD_LOG.read_text(encoding="utf-8"))
        return entries[-n:]
    except Exception:
        return []


def _nexus_dir_listing() -> list[str]:
    """Top-level directory and .py file listing of _NEXUS_ROOT."""
    items = []
    try:
        for p in sorted(_NEXUS_ROOT.iterdir()):
            if p.name.startswith(".") or p.name in ("__pycache__", "workspace", "voicebox", "model-registry"):
                continue
            if p.is_dir():
                # Include immediate children of key subdirs
                if p.name in ("orchestrator", "history", "serving", "skills", "agents"):
                    sub = [c.name for c in sorted(p.iterdir()) if not c.name.startswith("_")]
                    items.append(f"{p.name}/  [{', '.join(sub[:8])}]")
                else:
                    items.append(f"{p.name}/")
            elif p.suffix == ".py":
                items.append(p.name)
    except Exception as e:
        logger.debug("context_reader: dir listing failed (%s)", e)
    return items


def _find_related_files(goal: str, workspace_files: list[str]) -> list[str]:
    """Return workspace files whose names are semantically close to the goal.

    Simple heuristic: file name words that appear in the goal string.
    """
    goal_words = set(goal.lower().split())
    related = []
    for f in workspace_files:
        stem = Path(f).stem.lower().replace("_", " ").replace("-", " ")
        stem_words = set(stem.split())
        if stem_words & goal_words:
            related.append(f)
    return related[:3]  # cap at 3


def gather_context(task_packet: dict) -> dict:
    """Build a context_block from local workspace state.

    Returns:
        {
            "workspace_files": [str, ...],         # all previously built files
            "related_files": {path: content, ...}, # snippets of files close to goal
            "recent_builds": [dict, ...],           # last N build log entries
            "nexus_structure": [str, ...],          # dir listing of NEXUS_ROOT
            "summary": str,                         # one-line summary for logging
        }
    """
    goal = task_packet.get("goal", "")

    workspace_files = _list_workspace_files()
    recent_builds = _recent_build_log()
    nexus_structure = _nexus_dir_listing()
    related_file_paths = _find_related_files(goal, workspace_files)

    related_files: dict[str, str] = {}
    for rel_path in related_file_paths:
        snippet = _read_file_snippet(rel_path)
        if snippet:
            related_files[rel_path] = snippet

    summary_parts = []
    if workspace_files:
        summary_parts.append(f"{len(workspace_files)} file(s) in workspace/output/")
    if recent_builds:
        summary_parts.append(f"{len(recent_builds)} recent build(s)")
    if related_files:
        summary_parts.append(f"{len(related_files)} related file(s) found")
    summary = ", ".join(summary_parts) if summary_parts else "no prior workspace context"

    logger.info("Context gathered: %s", summary)

    return {
        "workspace_files": workspace_files,
        "related_files": related_files,
        "recent_builds": recent_builds,
        "nexus_structure": nexus_structure,
        "summary": summary,
    }


def format_context_for_prompt(context: dict) -> str:
    """Render the context_block as a prompt-injectable text section.

    Kept under _MAX_CONTEXT_CHARS to avoid bloating the planning prompt.
    """
    parts: list[str] = []

    if context["workspace_files"]:
        parts.append("=== Previously Built Files (workspace/output/) ===")
        parts.append("\n".join(context["workspace_files"]))

    if context["related_files"]:
        parts.append("\n=== Related Existing Code ===")
        for path, content in context["related_files"].items():
            parts.append(f"--- {path} ---")
            parts.append(content)

    if context["recent_builds"]:
        parts.append("\n=== Recent Build History ===")
        for entry in context["recent_builds"]:
            status = "PASS" if entry.get("verify_passed") else "FAIL"
            parts.append(
                f"[{entry.get('ts', '')[:10]}] {status} | {entry.get('builder', '?')} | "
                f"goal: {entry.get('goal', '')[:80]} | "
                f"files: {entry.get('files', [])}"
            )

    if context["nexus_structure"]:
        parts.append("\n=== Nexus Module Structure ===")
        parts.append("\n".join(context["nexus_structure"]))

    text = "\n".join(parts)
    if len(text) > _MAX_CONTEXT_CHARS:
        text = text[:_MAX_CONTEXT_CHARS] + "\n... [context truncated]"
    return text
