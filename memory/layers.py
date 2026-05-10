"""memory/layers.py — Typed memory layer dataclasses.

Three layers, three concerns:
  WorkspaceFile      — one file in workspace/output/
  RecentManifest     — summarized view of a past build (from workspace/manifests/)
  WorkspaceState     — live snapshot: what exists right now
  PlanningContext    — everything the planner needs, with clear section boundaries
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class WorkspaceFile:
    """A file that exists in workspace/output/."""
    name: str
    size_bytes: int

    def display(self) -> str:
        if self.size_bytes >= 1024:
            return f"{self.name} ({self.size_bytes / 1024:.1f}KB)"
        return f"{self.name} ({self.size_bytes}B)"


@dataclass
class RecentManifest:
    """Summarized view of a past build from workspace/manifests/."""
    plan_id: str
    goal: str
    success: bool
    attempt_count: int
    builder: str
    verification_status: str  # "passed" / "failed" / "no_files"
    test_status: str          # "passed" / "failed" / "skipped"


@dataclass
class WorkspaceState:
    """Live snapshot of workspace/output/ and recent build manifests.

    This is the 'what exists right now' layer — distinct from build history
    (what happened) and planning context (what the planner needs to know).
    """
    output_files: list[WorkspaceFile] = field(default_factory=list)
    recent_manifests: list[RecentManifest] = field(default_factory=list)
    manifest_count: int = 0

    def summary(self) -> str:
        """One-line summary for logging and plan_response.context_summary."""
        parts = []
        if self.output_files:
            parts.append(f"{len(self.output_files)} file(s) in workspace/output/")
        if self.manifest_count:
            parts.append(f"{self.manifest_count} manifest(s)")
        return ", ".join(parts) if parts else "empty workspace"


@dataclass
class PlanningContext:
    """All context layers the planner needs, clearly separated.

    Replace the flat context dict from context_reader with typed fields so:
    - each layer is independently inspectable
    - the rendering boundary is explicit (to_context_text())
    - future layers (long_term_memory, runtime_memory) can be added without
      changing how the planner consumes context

    Usage:
        ctx = build_planning_context(task_goal="build X")
        context_text = ctx.to_context_text()   # inject into prompt
        context_summary = ctx.summary()        # log / plan_response field
    """
    workspace: WorkspaceState
    build_history: list[dict]                    # raw build_log entries, last 3
    nexus_structure: list[str]                   # top-level dir listing
    related_snippets: list[tuple[str, str]]      # [(path, content), ...]

    _MAX_CONTEXT_CHARS: int = field(default=2000, repr=False)

    def summary(self) -> str:
        """One-line summary for logging and plan_response.context_summary."""
        ws = self.workspace.summary()
        extras = []
        if self.build_history:
            extras.append(f"{len(self.build_history)} recent build(s)")
        if self.related_snippets:
            extras.append(f"{len(self.related_snippets)} related file(s)")
        if extras:
            ws = f"{ws}, {', '.join(extras)}" if ws != "empty workspace" else ", ".join(extras)
        return ws or "no prior context"

    def to_context_text(self) -> str:
        """Render all layers as labeled sections for prompt injection.

        Kept under _MAX_CONTEXT_CHARS to avoid bloating the planning prompt.
        Section order: workspace state → recent manifests → related code →
                       build history → nexus structure
        """
        parts: list[str] = []

        # --- Layer 1: Workspace State ---
        if self.workspace.output_files:
            parts.append("=== Workspace (output/) ===")
            file_list = ", ".join(f.display() for f in self.workspace.output_files[:10])
            if len(self.workspace.output_files) > 10:
                file_list += f" ... ({len(self.workspace.output_files)} total)"
            parts.append(file_list)

        # --- Layer 2: Recent Manifests (M13 data) ---
        if self.workspace.recent_manifests:
            parts.append("\n=== Recent Builds (from manifests) ===")
            for m in self.workspace.recent_manifests:
                icon = "\u2713" if m.success else "\u2717"
                parts.append(
                    f"  [{icon}] {m.goal[:60]} | attempt {m.attempt_count} | "
                    f"{m.builder} | verify={m.verification_status} | tests={m.test_status}"
                )

        # --- Layer 3: Related Code Snippets ---
        if self.related_snippets:
            parts.append("\n=== Related Existing Code ===")
            for path, content in self.related_snippets:
                parts.append(f"--- {path} ---")
                parts.append(content)

        # --- Layer 4: Build History (raw log fallback if no manifests) ---
        if self.build_history and not self.workspace.recent_manifests:
            parts.append("\n=== Recent Build History ===")
            for entry in self.build_history:
                status = "PASS" if entry.get("verify_passed") else "FAIL"
                parts.append(
                    f"[{entry.get('ts', '')[:10]}] {status} | "
                    f"{entry.get('builder', '?')} | "
                    f"goal: {entry.get('goal', '')[:60]}"
                )

        # --- Layer 5: Nexus Structure (truncated if needed) ---
        if self.nexus_structure:
            parts.append("\n=== Nexus Module Structure ===")
            parts.append("\n".join(self.nexus_structure))

        text = "\n".join(parts)
        if len(text) > self._MAX_CONTEXT_CHARS:
            text = text[:self._MAX_CONTEXT_CHARS] + "\n... [context truncated]"
        return text
