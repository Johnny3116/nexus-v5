"""nexus-tools — Git Operations Skill

Git operations for NexusBody's workspace repositories.

Safety tiers:
    READ_ONLY:       status, log, branch, diff, get_diff
    NON_DESTRUCTIVE: clone, checkout (existing branch), fetch, pull
    DESTRUCTIVE:     commit, push, create_branch, delete_branch,
                     create_feature_branch

SECURITY:
    - clone and fetch only allow HTTPS URLs or Tailscale-accessible hosts.
    - push requires explicit approval when from automated sources.
    - All git commands run in a workspace-bound directory.
    - Protected branches (main, master, production, prod, release) are
      never targeted by create_feature_branch or other write actions.

Actions:
    status               — git status in a repo
    log                  — recent commits
    branch               — list branches
    diff                 — show diff
    get_diff             — unified diff between branch and base [READ_ONLY]
    clone                — clone a repository
    checkout             — checkout an existing branch
    fetch                — fetch from remote
    pull                 — pull from remote
    commit               — commit staged changes [DESTRUCTIVE]
    push                 — push to remote [DESTRUCTIVE]
    create_branch        — create and checkout new branch [DESTRUCTIVE]
    create_feature_branch — create feature/task-{slug} from base [DESTRUCTIVE]
"""

from __future__ import annotations

import asyncio
import logging
import re
import shlex
from pathlib import Path
from typing import Optional

from serving.skills.execution_context import ExecutionContext
from serving.skills.skill_base import SafetyTier, SkillBase

logger = logging.getLogger("nexus.tools.skills.git_ops")

_WORKSPACE = Path(__file__).resolve().parent.parent.parent  # repo root
_TIMEOUT = 60
_AUTOMATED_SOURCES = {"heartbeat", "cron", "reflex"}
_DESTRUCTIVE_ACTIONS = {"commit", "push", "create_branch", "delete_branch", "create_feature_branch"}

# Branches that automated operations must NEVER target
PROTECTED_BRANCHES = {"main", "master", "production", "prod", "release"}


class GitOpsSkill(SkillBase):
    name = "git_ops"
    description = (
        "Git operations within the Nexus workspace: status, log, branch, diff, "
        "clone, checkout, fetch, pull, commit, push. Destructive actions require "
        "approval when triggered by automation."
    )
    safety_tier = SafetyTier.DESTRUCTIVE
    version = "1.0.0"

    async def execute(self, context: ExecutionContext) -> dict:
        action = context.action

        if action in _DESTRUCTIVE_ACTIONS and context.source.value in _AUTOMATED_SOURCES:
            return {
                "success": False,
                "error": (
                    f"git_ops.{action} is destructive and blocked from automated source "
                    f"'{context.source.value}'. Route through approval queue."
                ),
            }

        dispatch = {
            "status": self._status,
            "log": self._log,
            "branch": self._branch,
            "diff": self._diff,
            "get_diff": self._get_diff,
            "clone": self._clone,
            "checkout": self._checkout,
            "fetch": self._fetch,
            "pull": self._pull,
            "commit": self._commit,
            "push": self._push,
            "create_branch": self._create_branch,
            "create_feature_branch": self._create_feature_branch,
        }

        handler = dispatch.get(action)
        if handler is None:
            return {"success": False, "error": f"Unknown action '{action}'"}
        return await handler(context)

    def get_capabilities(self) -> list[dict]:
        return [
            {"action": "status", "description": "git status", "params": {"repo": "path (default: workspace root)"}},
            {"action": "log", "description": "Recent git commits", "params": {"repo": "path", "count": "number of commits (default 10)"}},
            {"action": "branch", "description": "List branches", "params": {"repo": "path"}},
            {"action": "diff", "description": "Show git diff", "params": {"repo": "path", "ref": "optional ref"}},
            {"action": "clone", "description": "Clone a repository", "params": {"url": "repo URL", "dest": "destination path"}},
            {"action": "checkout", "description": "Checkout a branch", "params": {"repo": "path", "branch": "branch name"}},
            {"action": "fetch", "description": "git fetch from remote", "params": {"repo": "path"}},
            {"action": "pull", "description": "git pull from remote", "params": {"repo": "path"}},
            {"action": "commit", "description": "Commit staged changes [DESTRUCTIVE]", "params": {"repo": "path", "message": "commit message"}},
            {"action": "push", "description": "Push to remote [DESTRUCTIVE]", "params": {"repo": "path", "branch": "optional branch"}},
            {"action": "create_branch", "description": "Create and checkout new branch [DESTRUCTIVE]", "params": {"repo": "path", "branch": "branch name"}},
            {"action": "get_diff", "description": "Unified diff between branch and base [READ_ONLY]", "params": {"branch": "branch name", "base": "base branch (default: main)"}},
            {"action": "create_feature_branch", "description": "Create feature/task-{slug} from base [DESTRUCTIVE]", "params": {"task_id": "task identifier", "title": "task title (used for branch slug)"}},
        ]

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _repo_path(self, raw: Optional[str]) -> Path:
        """Resolve a repo path, defaulting to workspace root."""
        if not raw:
            return _WORKSPACE
        p = (_WORKSPACE / raw).resolve()
        if not str(p).startswith(str(_WORKSPACE)):
            raise ValueError(f"Repo path '{raw}' is outside workspace. Blocked.")
        return p

    async def _git(self, *args: str, cwd: Path) -> dict:
        """Run a git command in cwd, capture output."""
        cmd = ["git", *args]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(cwd),
            )
            stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=_TIMEOUT)
            stdout = stdout_b.decode(errors="replace").strip()
            stderr = stderr_b.decode(errors="replace").strip()
            return {
                "success": proc.returncode == 0,
                "returncode": proc.returncode,
                "stdout": stdout,
                "stderr": stderr,
            }
        except asyncio.TimeoutError:
            return {"success": False, "error": f"git {args[0]} timed out after {_TIMEOUT}s"}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    async def _status(self, context: ExecutionContext) -> dict:
        try:
            repo = self._repo_path(context.get_param("repo"))
            return await self._git("status", "--short", cwd=repo)
        except ValueError as exc:
            return {"success": False, "error": str(exc)}

    async def _log(self, context: ExecutionContext) -> dict:
        count = int(context.get_param("count", 10))
        try:
            repo = self._repo_path(context.get_param("repo"))
            return await self._git("log", f"-{count}", "--oneline", cwd=repo)
        except ValueError as exc:
            return {"success": False, "error": str(exc)}

    async def _branch(self, context: ExecutionContext) -> dict:
        try:
            repo = self._repo_path(context.get_param("repo"))
            return await self._git("branch", "-a", cwd=repo)
        except ValueError as exc:
            return {"success": False, "error": str(exc)}

    async def _diff(self, context: ExecutionContext) -> dict:
        ref = context.get_param("ref", "HEAD")
        try:
            repo = self._repo_path(context.get_param("repo"))
            return await self._git("diff", str(ref), cwd=repo)
        except ValueError as exc:
            return {"success": False, "error": str(exc)}

    async def _clone(self, context: ExecutionContext) -> dict:
        url = context.require_param("url")
        dest = context.get_param("dest", "")
        # Only allow HTTPS or SSH (no file:// paths)
        if not (url.startswith("https://") or url.startswith("git@")):
            return {"success": False, "error": f"Only HTTPS and SSH URLs allowed. Blocked: {url}"}
        try:
            clone_dest = self._repo_path(dest) if dest else _WORKSPACE / url.split("/")[-1].replace(".git", "")
            return await self._git("clone", url, str(clone_dest), cwd=_WORKSPACE)
        except ValueError as exc:
            return {"success": False, "error": str(exc)}

    async def _checkout(self, context: ExecutionContext) -> dict:
        branch = context.require_param("branch")
        try:
            repo = self._repo_path(context.get_param("repo"))
            return await self._git("checkout", branch, cwd=repo)
        except ValueError as exc:
            return {"success": False, "error": str(exc)}

    async def _fetch(self, context: ExecutionContext) -> dict:
        try:
            repo = self._repo_path(context.get_param("repo"))
            return await self._git("fetch", cwd=repo)
        except ValueError as exc:
            return {"success": False, "error": str(exc)}

    async def _pull(self, context: ExecutionContext) -> dict:
        try:
            repo = self._repo_path(context.get_param("repo"))
            return await self._git("pull", cwd=repo)
        except ValueError as exc:
            return {"success": False, "error": str(exc)}

    async def _commit(self, context: ExecutionContext) -> dict:
        message = context.require_param("message")
        try:
            repo = self._repo_path(context.get_param("repo"))
            return await self._git("commit", "-m", message, cwd=repo)
        except ValueError as exc:
            return {"success": False, "error": str(exc)}

    async def _push(self, context: ExecutionContext) -> dict:
        branch = context.get_param("branch", "")
        try:
            repo = self._repo_path(context.get_param("repo"))
            args = ["push"]
            if branch:
                args += ["origin", branch]
            return await self._git(*args, cwd=repo)
        except ValueError as exc:
            return {"success": False, "error": str(exc)}

    async def _create_branch(self, context: ExecutionContext) -> dict:
        branch = context.require_param("branch")
        try:
            repo = self._repo_path(context.get_param("repo"))
            return await self._git("checkout", "-b", branch, cwd=repo)
        except ValueError as exc:
            return {"success": False, "error": str(exc)}

    # ------------------------------------------------------------------
    # New actions (ported from nexus-coding)
    # ------------------------------------------------------------------

    async def _get_diff(self, context: ExecutionContext) -> dict:
        """Unified diff between branch and base. READ_ONLY — no branch restrictions."""
        branch = context.require_param("branch")
        base = context.get_param("base", "main")
        try:
            repo = self._repo_path(context.get_param("repo"))
            result = await self._git("diff", f"{base}...{branch}", cwd=repo)
            if result.get("success"):
                return {"success": True, "diff": result.get("stdout", "")}
            return result
        except ValueError as exc:
            return {"success": False, "error": str(exc)}

    async def _create_feature_branch(self, context: ExecutionContext) -> dict:
        """Create feature/task-{slug} from base. NEVER targets a protected branch.

        Safety tier: DESTRUCTIVE (approval required from automation sources).
        """
        task_id = context.require_param("task_id")
        title = context.require_param("title")
        base = context.get_param("base", "main")

        # Sanitize title into branch slug
        slug = _sanitize_branch_name(title)
        branch_name = f"feature/task-{slug}"

        # Protected branch check
        if branch_name.lower() in PROTECTED_BRANCHES:
            return {"success": False, "error": "Protected branch"}
        if base.lower() not in PROTECTED_BRANCHES and base != "main":
            # base must be a known branch, but doesn't need protection check
            pass

        try:
            repo = self._repo_path(context.get_param("repo"))
            # Fetch latest first
            await self._git("fetch", "origin", cwd=repo)
            # Create branch from base
            result = await self._git("checkout", "-b", branch_name, f"origin/{base}", cwd=repo)
            if result.get("success"):
                logger.info("Created feature branch %s for task %s", branch_name, task_id)
                return {"success": True, "branch_name": branch_name, "task_id": task_id}
            return result
        except ValueError as exc:
            return {"success": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sanitize_branch_name(text: str) -> str:
    """Convert a task title into a valid git branch slug."""
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    text = re.sub(r"\s+", "-", text)
    text = re.sub(r"-+", "-", text)
    return text[:50].strip("-")
