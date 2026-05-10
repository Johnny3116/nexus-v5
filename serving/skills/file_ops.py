"""nexus-tools — File Operations Skill

Read, search, write, and manage files across the homelab.

**Boundary model (v2):**
    READ  — anywhere readable by the Nexus user account on NexusBody
            (entire local filesystem + UNC paths to NexusServer via
            ``\\\\nexusserver\\c$\\...`` SMB shares).
    WRITE — only inside ``NEXUS_WORKSPACE`` (default
            ``C:\\Users\\Nexus\\Nexus\\workspace``). Any path that resolves
            outside this root is blocked with WorkspaceBoundaryError.

This split lets Nexus inspect any project on the mesh while keeping a
clean blast radius for writes. Self-modification of her own runtime
(``C:\\Users\\Nexus\\Nexus\\``) is therefore impossible through this
skill — any code edits she makes happen inside ``workspace/`` and have to
be promoted by John (manually or via approval-gated git ops).

Actions:
    read     — read file contents (anywhere)
    list     — list directory contents (anywhere)
    exists   — check if path exists (anywhere)
    glob     — find files by pattern (anywhere)
    grep     — search file contents (anywhere)
    write    — write file (workspace only)
    append   — append to file (workspace only)
    mkdir    — create directory (workspace only)
    delete   — delete file or empty directory (workspace only, DESTRUCTIVE)
    move     — move/rename file (both src & dst must be in workspace, DESTRUCTIVE)
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any

from serving.skills.execution_context import ExecutionContext
from serving.skills.skill_base import SafetyTier, SkillBase

logger = logging.getLogger("nexus.tools.skills.file_ops")


# Where Nexus is allowed to write. Override via env so John can move it
# without editing source.
WORKSPACE_ROOT = Path(
    os.environ.get("NEXUS_WORKSPACE", r"C:\Users\Nexus\Nexus\workspace")
).resolve()

# Read caps so a misfired read doesn't try to slurp a 50GB log into memory.
_MAX_READ_BYTES = int(os.environ.get("NEXUS_FILEOPS_MAX_READ", str(10 * 1024 * 1024)))  # 10 MiB
_MAX_GREP_FILES = int(os.environ.get("NEXUS_FILEOPS_MAX_GREP_FILES", "500"))
_MAX_GREP_HITS = int(os.environ.get("NEXUS_FILEOPS_MAX_GREP_HITS", "200"))
_MAX_GLOB_HITS = int(os.environ.get("NEXUS_FILEOPS_MAX_GLOB_HITS", "1000"))
_MAX_LIST_ENTRIES = 2000

_DESTRUCTIVE_ACTIONS = {"delete", "move"}
_AUTOMATED_SOURCES = {"heartbeat", "cron", "reflex"}
_WRITE_ACTIONS = {"write", "append", "mkdir", "delete", "move"}


class WorkspaceBoundaryError(ValueError):
    """Raised when a write action targets a path outside WORKSPACE_ROOT."""


class FileOpsSkill(SkillBase):
    name = "file_ops"
    description = (
        "Read/search any file on NexusBody (and NexusServer via UNC paths). "
        "Writes restricted to workspace root (default: "
        "C:\\Users\\Nexus\\Nexus\\workspace). Destructive actions blocked "
        "from automated sources."
    )
    safety_tier = SafetyTier.DESTRUCTIVE
    version = "2.0.0"

    async def execute(self, context: ExecutionContext) -> dict:
        action = context.action

        # Block destructive actions from automation — must go through approval.
        if action in _DESTRUCTIVE_ACTIONS and context.source.value in _AUTOMATED_SOURCES:
            return {
                "success": False,
                "error": (
                    f"Action '{action}' is destructive and was blocked from automated source "
                    f"'{context.source.value}'. Route through approval queue."
                ),
            }

        dispatch = {
            "read":   self._read,
            "list":   self._list,
            "exists": self._exists,
            "glob":   self._glob,
            "grep":   self._grep,
            "write":  self._write,
            "append": self._append,
            "mkdir":  self._mkdir,
            "delete": self._delete,
            "move":   self._move,
        }
        handler = dispatch.get(action)
        if handler is None:
            return {"success": False, "error": f"Unknown action '{action}'"}
        return await handler(context)

    def get_capabilities(self) -> list[dict]:
        return [
            {"action": "read",   "description": "Read a file (anywhere readable)",
             "params": {"path": "absolute or UNC path"}},
            {"action": "list",   "description": "List a directory (anywhere)",
             "params": {"path": "directory path (default '.')"}},
            {"action": "exists", "description": "Check if a path exists (anywhere)",
             "params": {"path": "path to test"}},
            {"action": "glob",   "description": "Find files by glob pattern under a root (anywhere)",
             "params": {"root": "directory to search", "pattern": "glob, e.g. '**/*.py'"}},
            {"action": "grep",   "description": "Regex search inside files under a root (anywhere)",
             "params": {"root": "directory to search", "pattern": "regex",
                        "include": "optional glob to limit files (default '**/*')",
                        "ignore_case": "bool (default false)"}},
            {"action": "write",  "description": "Write a file (workspace only)",
             "params": {"path": "path under workspace", "content": "text"}},
            {"action": "append", "description": "Append to a file (workspace only)",
             "params": {"path": "path under workspace", "content": "text"}},
            {"action": "mkdir",  "description": "Create a directory (workspace only)",
             "params": {"path": "path under workspace"}},
            {"action": "delete", "description": "Delete a file or empty dir (workspace only) [DESTRUCTIVE]",
             "params": {"path": "path under workspace"}},
            {"action": "move",   "description": "Rename/move a file (both ends workspace) [DESTRUCTIVE]",
             "params": {"src": "source path", "dst": "destination path"}},
        ]

    # ------------------------------------------------------------------
    # Path resolution & boundary
    # ------------------------------------------------------------------

    def _resolve(self, raw: str) -> Path:
        """Resolve a user-supplied path. Accepts absolute, relative-to-cwd,
        or UNC paths. Symlinks/junctions are resolved so the boundary check
        can't be defeated by a link inside the workspace pointing out.
        """
        try:
            return Path(raw).resolve(strict=False)
        except OSError as exc:
            raise ValueError(f"Cannot resolve path {raw!r}: {exc}") from exc

    def _ensure_in_workspace(self, p: Path, label: str = "path") -> None:
        """Hard-block any write outside WORKSPACE_ROOT."""
        try:
            p.relative_to(WORKSPACE_ROOT)
        except ValueError:
            raise WorkspaceBoundaryError(
                f"{label} {str(p)!r} is outside the workspace root "
                f"{str(WORKSPACE_ROOT)!r}. Writes are not allowed here."
            )

    # ------------------------------------------------------------------
    # Read-side actions (anywhere)
    # ------------------------------------------------------------------

    async def _read(self, context: ExecutionContext) -> dict:
        path_str = context.require_param("path")
        try:
            p = self._resolve(path_str)
            if not p.is_file():
                return {"success": False, "error": f"Not a file: {p}"}
            size = p.stat().st_size
            if size > _MAX_READ_BYTES:
                return {
                    "success": False,
                    "error": f"File too large to read inline ({size} bytes > {_MAX_READ_BYTES}). "
                             "Use grep or read a slice instead.",
                    "size_bytes": size,
                }
            content = p.read_text(encoding="utf-8", errors="replace")
            return {"success": True, "path": str(p), "content": content, "size_bytes": size}
        except Exception as exc:
            return {"success": False, "error": f"Read failed: {exc}"}

    async def _list(self, context: ExecutionContext) -> dict:
        path_str = context.get_param("path", str(WORKSPACE_ROOT))
        try:
            p = self._resolve(path_str)
            if not p.is_dir():
                return {"success": False, "error": f"Not a directory: {p}"}
            entries = []
            for i, e in enumerate(sorted(p.iterdir())):
                if i >= _MAX_LIST_ENTRIES:
                    entries.append({"name": "…", "type": "truncated",
                                    "size_bytes": None, "note": f"more than {_MAX_LIST_ENTRIES} entries"})
                    break
                try:
                    is_dir = e.is_dir()
                    size = e.stat().st_size if e.is_file() else None
                except OSError:
                    is_dir, size = False, None
                entries.append({"name": e.name, "type": "dir" if is_dir else "file", "size_bytes": size})
            return {"success": True, "path": str(p), "entries": entries, "count": len(entries)}
        except Exception as exc:
            return {"success": False, "error": f"List failed: {exc}"}

    async def _exists(self, context: ExecutionContext) -> dict:
        path_str = context.require_param("path")
        try:
            p = self._resolve(path_str)
            kind = "dir" if p.is_dir() else "file" if p.is_file() else "missing"
            return {"success": True, "path": str(p), "exists": p.exists(), "type": kind}
        except Exception as exc:
            return {"success": False, "error": f"Exists check failed: {exc}"}

    async def _glob(self, context: ExecutionContext) -> dict:
        root = context.require_param("root")
        pattern = context.get_param("pattern", "**/*")
        try:
            base = self._resolve(root)
            if not base.is_dir():
                return {"success": False, "error": f"Root is not a directory: {base}"}
            hits: list[str] = []
            for match in base.glob(pattern):
                hits.append(str(match))
                if len(hits) >= _MAX_GLOB_HITS:
                    break
            return {
                "success": True,
                "root": str(base),
                "pattern": pattern,
                "hits": hits,
                "count": len(hits),
                "truncated": len(hits) >= _MAX_GLOB_HITS,
            }
        except Exception as exc:
            return {"success": False, "error": f"Glob failed: {exc}"}

    async def _grep(self, context: ExecutionContext) -> dict:
        root = context.require_param("root")
        pattern = context.require_param("pattern")
        include = context.get_param("include", "**/*")
        ignore_case = bool(context.get_param("ignore_case", False))
        flags = re.IGNORECASE if ignore_case else 0
        try:
            base = self._resolve(root)
            if not base.is_dir():
                return {"success": False, "error": f"Root is not a directory: {base}"}
            regex = re.compile(pattern, flags)
            hits: list[dict] = []
            files_scanned = 0
            for fp in base.glob(include):
                if not fp.is_file():
                    continue
                files_scanned += 1
                if files_scanned > _MAX_GREP_FILES:
                    break
                try:
                    text = fp.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue
                for lineno, line in enumerate(text.splitlines(), start=1):
                    if regex.search(line):
                        hits.append({"path": str(fp), "line": lineno, "text": line[:300]})
                        if len(hits) >= _MAX_GREP_HITS:
                            break
                if len(hits) >= _MAX_GREP_HITS:
                    break
            return {
                "success": True,
                "root": str(base),
                "pattern": pattern,
                "files_scanned": files_scanned,
                "hits": hits,
                "count": len(hits),
                "truncated_files": files_scanned > _MAX_GREP_FILES,
                "truncated_hits": len(hits) >= _MAX_GREP_HITS,
            }
        except re.error as exc:
            return {"success": False, "error": f"Bad regex: {exc}"}
        except Exception as exc:
            return {"success": False, "error": f"Grep failed: {exc}"}

    # ------------------------------------------------------------------
    # Write-side actions (workspace only)
    # ------------------------------------------------------------------

    async def _write(self, context: ExecutionContext) -> dict:
        path_str = context.require_param("path")
        content = context.require_param("content")
        try:
            p = self._resolve(path_str)
            self._ensure_in_workspace(p, "write target")
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
            return {"success": True, "path": str(p), "size_bytes": len(content.encode("utf-8"))}
        except WorkspaceBoundaryError as exc:
            return {"success": False, "error": str(exc), "boundary_violation": True}
        except Exception as exc:
            return {"success": False, "error": f"Write failed: {exc}"}

    async def _append(self, context: ExecutionContext) -> dict:
        path_str = context.require_param("path")
        content = context.require_param("content")
        try:
            p = self._resolve(path_str)
            self._ensure_in_workspace(p, "append target")
            p.parent.mkdir(parents=True, exist_ok=True)
            with p.open("a", encoding="utf-8") as f:
                f.write(content)
            return {"success": True, "path": str(p)}
        except WorkspaceBoundaryError as exc:
            return {"success": False, "error": str(exc), "boundary_violation": True}
        except Exception as exc:
            return {"success": False, "error": f"Append failed: {exc}"}

    async def _mkdir(self, context: ExecutionContext) -> dict:
        path_str = context.require_param("path")
        try:
            p = self._resolve(path_str)
            self._ensure_in_workspace(p, "mkdir target")
            p.mkdir(parents=True, exist_ok=True)
            return {"success": True, "path": str(p)}
        except WorkspaceBoundaryError as exc:
            return {"success": False, "error": str(exc), "boundary_violation": True}
        except Exception as exc:
            return {"success": False, "error": f"mkdir failed: {exc}"}

    async def _delete(self, context: ExecutionContext) -> dict:
        path_str = context.require_param("path")
        try:
            p = self._resolve(path_str)
            self._ensure_in_workspace(p, "delete target")
            if not p.exists():
                return {"success": False, "error": f"Path does not exist: {p}"}
            if p.is_file():
                p.unlink()
                return {"success": True, "deleted": str(p), "type": "file"}
            if p.is_dir():
                p.rmdir()  # only empty dirs
                return {"success": True, "deleted": str(p), "type": "directory"}
            return {"success": False, "error": "Not a file or directory"}
        except WorkspaceBoundaryError as exc:
            return {"success": False, "error": str(exc), "boundary_violation": True}
        except OSError as exc:
            return {"success": False, "error": f"Delete failed: {exc}"}

    async def _move(self, context: ExecutionContext) -> dict:
        src_str = context.require_param("src")
        dst_str = context.require_param("dst")
        try:
            src = self._resolve(src_str)
            dst = self._resolve(dst_str)
            # Both endpoints must be inside the workspace — no exfiltrating
            # files out of (or smuggling files into) the rest of the box.
            self._ensure_in_workspace(src, "move source")
            self._ensure_in_workspace(dst, "move destination")
            if not src.exists():
                return {"success": False, "error": f"Source does not exist: {src}"}
            dst.parent.mkdir(parents=True, exist_ok=True)
            src.rename(dst)
            return {"success": True, "src": str(src), "dst": str(dst)}
        except WorkspaceBoundaryError as exc:
            return {"success": False, "error": str(exc), "boundary_violation": True}
        except Exception as exc:
            return {"success": False, "error": f"Move failed: {exc}"}
