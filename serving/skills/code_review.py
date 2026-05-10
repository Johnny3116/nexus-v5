"""nexus-tools — Code Review Skill

Read git diffs and generate structured code review notes.
Flags secrets, debug prints, bare excepts, eval/exec, TODOs.
Returns a verdict: LOOKS_CLEAN, REVIEW_SUGGESTED, or NEEDS_REVIEW.

Ported from nexus-coding review module (diff_reader, issue_checker,
review_notes) — fully self-contained, no nexus_coding imports.

Actions:
    review_diff    — Review a diff string directly
    review_branch  — Get diff between branch and base, then review
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from serving.skills.execution_context import ExecutionContext
from serving.skills.skill_base import SafetyTier, SkillBase

logger = logging.getLogger("nexus.tools.skills.code_review")

_WORKSPACE = Path(__file__).resolve().parent.parent.parent


# ---------------------------------------------------------------------------
# Internal data structures (ported from nexus_coding/review/diff_reader.py)
# ---------------------------------------------------------------------------

@dataclass
class _DiffHunk:
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    lines: list[str] = field(default_factory=list)


@dataclass
class _FileDiff:
    old_path: str
    new_path: str
    is_new: bool
    is_deleted: bool
    hunks: list[_DiffHunk] = field(default_factory=list)

    @property
    def added_lines(self) -> list[str]:
        return [l[1:] for h in self.hunks for l in h.lines if l.startswith("+")]

    @property
    def removed_lines(self) -> list[str]:
        return [l[1:] for h in self.hunks for l in h.lines if l.startswith("-")]

    @property
    def changed_line_count(self) -> int:
        return len(self.added_lines) + len(self.removed_lines)


@dataclass
class _CodeIssue:
    severity: str    # "warning" | "info" | "error"
    category: str
    description: str
    file_path: str
    line_hint: str | None = None


_HUNK_HEADER = re.compile(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")

# Issue-checker patterns (ported from nexus_coding/review/issue_checker.py)
_CHECKS: list[tuple[str, str, str, re.Pattern]] = [
    ("error", "secret", "Possible hardcoded credential in added line",
     re.compile(r'(?i)(api_?key|secret|password|token)\s*[=:]\s*["\'][^"\']{8,}["\']')),
    ("warning", "debug", "print() statement left in added code",
     re.compile(r'^\+\s*print\(')),
    ("warning", "debug", "console.log() statement left in added code",
     re.compile(r'^\+\s*console\.log\(')),
    ("warning", "debug", "breakpoint() left in added code",
     re.compile(r'^\+\s*breakpoint\(\)')),
    ("warning", "debug", "pdb.set_trace() left in added code",
     re.compile(r'^\+.*pdb\.set_trace\(\)')),
    ("warning", "error-handling", "Bare except clause (catches all exceptions silently)",
     re.compile(r'^\+\s*except\s*:')),
    ("info", "todo", "TODO/FIXME comment in added code",
     re.compile(r'^\+.*\b(TODO|FIXME|HACK|XXX)\b')),
    ("warning", "security", "exec() or eval() call in added code",
     re.compile(r'^\+.*\b(exec|eval)\s*\(')),
    ("warning", "security", "subprocess call with shell=True",
     re.compile(r'^\+.*subprocess\.\w+\([^)]*shell\s*=\s*True')),
    ("info", "style", "Overly long added line (>120 chars)",
     re.compile(r'^\+.{120,}')),
]


# ---------------------------------------------------------------------------
# Skill class
# ---------------------------------------------------------------------------

class CodeReviewSkill(SkillBase):
    name = "code_review"
    description = (
        "Read git diffs and generate structured code review notes. "
        "Flags secrets, debug prints, bare excepts, eval/exec, TODOs. "
        "Returns a verdict: LOOKS_CLEAN, REVIEW_SUGGESTED, or NEEDS_REVIEW."
    )
    safety_tier = SafetyTier.READ_ONLY
    version = "1.0.0"

    async def execute(self, context: ExecutionContext) -> dict:
        action = context.action
        dispatch = {
            "review_diff": self._review_diff,
            "review_branch": self._review_branch,
        }
        handler = dispatch.get(action)
        if handler is None:
            return {"success": False, "error": f"Unknown action '{action}'"}
        return await handler(context)

    def get_capabilities(self) -> list[dict]:
        return [
            {
                "action": "review_diff",
                "description": "Review a unified diff string for code issues",
                "params": {"diff_text": "Unified diff string to review"},
            },
            {
                "action": "review_branch",
                "description": "Get diff between branch and base, then review",
                "params": {
                    "branch": "Branch to review",
                    "base": "Base branch (default: main)",
                },
            },
        ]

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    async def _review_diff(self, context: ExecutionContext) -> dict:
        diff_text = context.require_param("diff_text")
        file_diffs = self._parse_diff(diff_text)
        issues = self._check_issues(file_diffs)
        verdict = self._compute_verdict(issues)
        notes = self._generate_notes("(direct diff)", "(direct diff)", file_diffs, issues)
        return {
            "success": True,
            "verdict": verdict,
            "issue_count": len(issues),
            "files_changed": len(file_diffs),
            "notes": notes,
            "issues": [
                {
                    "severity": i.severity,
                    "category": i.category,
                    "description": i.description,
                    "file": i.file_path,
                    "hint": i.line_hint,
                }
                for i in issues
            ],
        }

    async def _review_branch(self, context: ExecutionContext) -> dict:
        branch = context.require_param("branch")
        base = context.get_param("base", "main")

        diff_text = await self._git_diff(branch, base)
        if diff_text is None:
            return {"success": False, "error": f"Failed to get diff for {branch}...{base}"}

        file_diffs = self._parse_diff(diff_text)
        issues = self._check_issues(file_diffs)
        verdict = self._compute_verdict(issues)
        notes = self._generate_notes(branch, base, file_diffs, issues)
        return {
            "success": True,
            "verdict": verdict,
            "branch": branch,
            "base": base,
            "issue_count": len(issues),
            "files_changed": len(file_diffs),
            "notes": notes,
            "issues": [
                {
                    "severity": i.severity,
                    "category": i.category,
                    "description": i.description,
                    "file": i.file_path,
                    "hint": i.line_hint,
                }
                for i in issues
            ],
        }

    # ------------------------------------------------------------------
    # Diff parser (from nexus_coding/review/diff_reader.py)
    # ------------------------------------------------------------------

    def _parse_diff(self, diff_text: str) -> list[_FileDiff]:
        files: list[_FileDiff] = []
        current_file: _FileDiff | None = None
        current_hunk: _DiffHunk | None = None

        for line in diff_text.splitlines():
            if line.startswith("diff --git"):
                if current_file and current_hunk:
                    current_file.hunks.append(current_hunk)
                if current_file:
                    files.append(current_file)
                current_file = None
                current_hunk = None

            elif line.startswith("--- "):
                old_path = line[4:].strip().removeprefix("a/")
                if current_file is None:
                    current_file = _FileDiff(
                        old_path=old_path,
                        new_path="",
                        is_new=(old_path == "/dev/null"),
                        is_deleted=False,
                    )
                else:
                    current_file.old_path = old_path

            elif line.startswith("+++ ") and current_file is not None:
                new_path = line[4:].strip().removeprefix("b/")
                current_file.new_path = new_path
                current_file.is_deleted = (new_path == "/dev/null")

            elif line.startswith("@@") and current_file is not None:
                if current_hunk:
                    current_file.hunks.append(current_hunk)
                match = _HUNK_HEADER.search(line)
                if match:
                    current_hunk = _DiffHunk(
                        old_start=int(match.group(1)),
                        old_count=int(match.group(2) or 1),
                        new_start=int(match.group(3)),
                        new_count=int(match.group(4) or 1),
                    )

            elif current_hunk is not None and (
                line.startswith("+") or line.startswith("-") or line.startswith(" ")
            ):
                current_hunk.lines.append(line)

        if current_file and current_hunk:
            current_file.hunks.append(current_hunk)
        if current_file:
            files.append(current_file)

        return files

    # ------------------------------------------------------------------
    # Issue checker (from nexus_coding/review/issue_checker.py)
    # ------------------------------------------------------------------

    def _check_issues(self, file_diffs: list[_FileDiff]) -> list[_CodeIssue]:
        issues: list[_CodeIssue] = []
        for fd in file_diffs:
            for hunk in fd.hunks:
                for line in hunk.lines:
                    if not line.startswith("+"):
                        continue
                    for severity, category, description, pattern in _CHECKS:
                        if pattern.search(line):
                            issues.append(_CodeIssue(
                                severity=severity,
                                category=category,
                                description=description,
                                file_path=fd.new_path,
                                line_hint=line[1:80].strip(),
                            ))
        return issues

    # ------------------------------------------------------------------
    # Verdict logic
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_verdict(issues: list[_CodeIssue]) -> str:
        error_count = sum(1 for i in issues if i.severity == "error")
        warning_count = sum(1 for i in issues if i.severity == "warning")
        if error_count > 0:
            return "NEEDS_REVIEW"
        if warning_count > 3:
            return "REVIEW_SUGGESTED"
        return "LOOKS_CLEAN"

    # ------------------------------------------------------------------
    # Review notes generator (from nexus_coding/review/review_notes.py)
    # ------------------------------------------------------------------

    def _generate_notes(
        self,
        branch: str,
        base: str,
        file_diffs: list[_FileDiff],
        issues: list[_CodeIssue],
    ) -> str:
        lines: list[str] = []
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

        lines.append(f"# Code Review: `{branch}` vs `{base}`")
        lines.append(f"> Generated by nexus-tools/code_review · {now}")
        lines.append("")

        total_added = sum(len(fd.added_lines) for fd in file_diffs)
        total_removed = sum(len(fd.removed_lines) for fd in file_diffs)
        new_files = [fd for fd in file_diffs if fd.is_new]
        deleted_files = [fd for fd in file_diffs if fd.is_deleted]

        lines.append("## Diff Summary")
        lines.append(f"- **Files changed:** {len(file_diffs)}")
        lines.append(f"- **Lines added:** +{total_added}")
        lines.append(f"- **Lines removed:** -{total_removed}")
        if new_files:
            lines.append(f"- **New files:** {len(new_files)}")
        if deleted_files:
            lines.append(f"- **Deleted files:** {len(deleted_files)}")
        lines.append("")

        lines.append("## Files Changed")
        for fd in file_diffs:
            marker = " (new)" if fd.is_new else " (deleted)" if fd.is_deleted else ""
            lines.append(f"- `{fd.new_path or fd.old_path}`{marker} +{len(fd.added_lines)}/-{len(fd.removed_lines)}")
        lines.append("")

        if issues:
            errors = [i for i in issues if i.severity == "error"]
            warnings = [i for i in issues if i.severity == "warning"]
            infos = [i for i in issues if i.severity == "info"]

            lines.append("## Issues Found")
            if errors:
                lines.append(f"\n### Errors ({len(errors)})")
                for issue in errors:
                    lines.append(f"- **[{issue.file_path}]** {issue.description}")
                    if issue.line_hint:
                        lines.append(f"  ```\n  {issue.line_hint}\n  ```")

            if warnings:
                lines.append(f"\n### Warnings ({len(warnings)})")
                for issue in warnings:
                    lines.append(f"- **[{issue.file_path}]** {issue.description}")

            if infos:
                lines.append(f"\n### Notes ({len(infos)})")
                for issue in infos:
                    lines.append(f"- **[{issue.file_path}]** {issue.description}")
        else:
            lines.append("## Issues Found")
            lines.append("No automated issues detected.")

        lines.append("")

        verdict = self._compute_verdict(issues)
        verdict_text = {
            "NEEDS_REVIEW": f"NEEDS REVIEW — {sum(1 for i in issues if i.severity == 'error')} error(s) found. Human review required before merge.",
            "REVIEW_SUGGESTED": f"REVIEW SUGGESTED — {sum(1 for i in issues if i.severity == 'warning')} warnings found.",
            "LOOKS_CLEAN": "LOOKS CLEAN — No blocking issues detected. John should still review before merging.",
        }
        lines.append(f"## Verdict\n**{verdict_text[verdict]}**")
        lines.append("")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Git helper
    # ------------------------------------------------------------------

    async def _git_diff(self, branch: str, base: str) -> Optional[str]:
        try:
            proc = await asyncio.create_subprocess_exec(
                "git", "diff", f"{base}...{branch}",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(_WORKSPACE),
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
            if proc.returncode != 0:
                logger.error("git diff failed: %s", stderr.decode(errors="replace"))
                return None
            return stdout.decode(errors="replace")
        except Exception as exc:
            logger.error("git diff error: %s", exc)
            return None
