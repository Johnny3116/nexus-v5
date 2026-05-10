"""/v1/workspace — browse and read from the Nexus workspace.

Root: C:\\Users\\Nexus-AI\\Workspace (configurable via WORKSPACE_ROOT).
Security: read-only by default. Write operations gated behind
FEATURE_WORKSPACE_WRITE (disabled). Path traversal blocked.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

router = APIRouter(tags=["workspace"])

WORKSPACE_ROOT = Path(os.getenv("WORKSPACE_ROOT", r"C:\Users\Nexus-AI\Workspace"))


def _safe_resolve(subpath: str) -> Path:
    """Resolve subpath within workspace, block traversal."""
    clean = subpath.lstrip("/\\").replace("..", "")
    resolved = (WORKSPACE_ROOT / clean).resolve()
    if not str(resolved).startswith(str(WORKSPACE_ROOT.resolve())):
        raise HTTPException(status_code=403, detail="path traversal blocked")
    return resolved


@router.get("/v1/workspace")
async def list_root():
    """List top-level workspace directories."""
    return await list_dir("")


@router.get("/v1/workspace/tree")
async def workspace_tree(depth: int = Query(2, ge=1, le=4)):
    """Recursive tree of the workspace up to `depth` levels."""
    def walk(p: Path, d: int) -> list[dict]:
        if d <= 0 or not p.is_dir():
            return []
        entries = []
        try:
            for child in sorted(p.iterdir()):
                entry = {
                    "name": child.name,
                    "type": "dir" if child.is_dir() else "file",
                    "path": str(child.relative_to(WORKSPACE_ROOT)).replace("\\", "/"),
                }
                if child.is_dir():
                    entry["children"] = walk(child, d - 1)
                else:
                    entry["size"] = child.stat().st_size
                entries.append(entry)
        except PermissionError:
            pass
        return entries

    if not WORKSPACE_ROOT.exists():
        raise HTTPException(status_code=404, detail="workspace root not found")

    return {"root": str(WORKSPACE_ROOT), "tree": walk(WORKSPACE_ROOT, depth)}


@router.get("/v1/workspace/ls/{subpath:path}")
async def list_dir(subpath: str):
    """List contents of a workspace subdirectory."""
    target = _safe_resolve(subpath)
    if not target.exists():
        raise HTTPException(status_code=404, detail=f"not found: {subpath}")
    if not target.is_dir():
        raise HTTPException(status_code=400, detail="not a directory — use /v1/workspace/read")

    entries = []
    for child in sorted(target.iterdir()):
        stat = child.stat()
        entries.append({
            "name": child.name,
            "type": "dir" if child.is_dir() else "file",
            "path": str(child.relative_to(WORKSPACE_ROOT)).replace("\\", "/"),
            "size": stat.st_size if child.is_file() else None,
            "modified": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
        })
    return {"path": subpath or "/", "entries": entries}


@router.get("/v1/workspace/read/{subpath:path}")
async def read_file(subpath: str, max_lines: int = Query(500, ge=1, le=5000)):
    """Read a workspace file (text only, capped at max_lines)."""
    target = _safe_resolve(subpath)
    if not target.exists():
        raise HTTPException(status_code=404, detail=f"not found: {subpath}")
    if not target.is_file():
        raise HTTPException(status_code=400, detail="not a file")
    if target.stat().st_size > 2_000_000:
        raise HTTPException(status_code=413, detail="file too large (>2MB)")

    try:
        lines = target.read_text(encoding="utf-8", errors="replace").splitlines()[:max_lines]
        return {
            "path": subpath,
            "lines": len(lines),
            "truncated": len(lines) == max_lines,
            "content": "\n".join(lines),
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
