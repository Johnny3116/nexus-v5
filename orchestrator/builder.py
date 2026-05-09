"""builder.py — generates code from an approved Plan using local Ollama.

Milestone 4 hard limits:
    - Writes ONLY to workspace/output/ (path-validated, no traversal)
    - No Codex, no Sonnet, no MCP, no shell execution, no git operations
    - Every output path is validated before writing
    - If any path is invalid, the whole build is aborted (no partial writes)
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import httpx

from .build_prompt import SYSTEM_PROMPT, build_implementation_prompt

logger = logging.getLogger(__name__)

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5-coder:7b")

# Workspace sandbox — builder may ONLY write inside this directory
_NEXUS_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = _NEXUS_ROOT / "workspace" / "output"


def _validate_output_paths(files: list[dict]) -> list[str]:
    """Return list of error strings for any file with an unsafe path.

    A safe path:
    - Is relative (no leading slash or drive letter)
    - Resolves inside WORKSPACE_ROOT (no ../ traversal)
    - Has a recognisable code/text extension
    """
    errors = []
    allowed_exts = {
        ".py", ".js", ".ts", ".jsx", ".tsx", ".json", ".yaml", ".yml",
        ".toml", ".md", ".txt", ".sh", ".bat", ".html", ".css", ".sql",
        ".env.example", ".cfg", ".ini", ".rs", ".go", ".java", ".rb",
    }
    for entry in files:
        raw = entry.get("path", "")
        if not raw:
            errors.append("file entry missing 'path' field")
            continue
        # No absolute paths
        if Path(raw).is_absolute():
            errors.append(f"absolute path rejected: {raw!r}")
            continue
        # Resolve against workspace root and check containment
        resolved = (WORKSPACE_ROOT / raw).resolve()
        try:
            resolved.relative_to(WORKSPACE_ROOT.resolve())
        except ValueError:
            errors.append(f"path traversal rejected: {raw!r} -> {resolved}")
            continue
        # Extension check
        suffix = resolved.suffix.lower()
        if suffix not in allowed_exts and ".env.example" not in raw:
            errors.append(f"extension not allowed: {raw!r} ({suffix})")
    return errors


def _write_files(files: list[dict]) -> list[str]:
    """Write validated files to WORKSPACE_ROOT. Returns list of written paths."""
    WORKSPACE_ROOT.mkdir(parents=True, exist_ok=True)
    written = []
    for entry in files:
        dest = (WORKSPACE_ROOT / entry["path"]).resolve()
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(entry.get("content", ""), encoding="utf-8")
        written.append(str(dest.relative_to(_NEXUS_ROOT)))
        logger.info("Builder wrote: %s (%d chars)", dest.name, len(entry.get("content", "")))
    return written


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
    if text.endswith("```"):
        text = text.rsplit("```", 1)[0]
    return text.strip()


async def build_from_plan(plan: dict, task_packet: dict, error_context: str = "") -> dict:
    """Call Ollama to generate code from an approved plan.

    Returns a build_result dict:
        {
            "success": bool,
            "written_files": [str],   # relative paths within Nexus root
            "notes": str,
            "error": str | None,
        }

    On validation failure: returns error without writing anything.
    On Ollama failure: returns error without writing anything.
    """
    user_message = build_implementation_prompt(plan, task_packet, error_context=error_context)

    payload = {
        "model": OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
        "stream": False,
        "options": {
            "temperature": 0.15,
            "num_predict": 2000,
        },
        "keep_alive": -1,
        "format": "json",
    }

    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=5.0)) as client:
        resp = await client.post(f"{OLLAMA_URL}/api/chat", json=payload)
        resp.raise_for_status()
        data = resp.json()

    raw_text = data.get("message", {}).get("content", "").strip()
    if not raw_text:
        raise ValueError("Ollama returned empty build response")

    raw_text = _strip_fences(raw_text)
    build_dict = json.loads(raw_text)

    files = build_dict.get("files", [])
    notes = build_dict.get("notes", "")

    if not files:
        return {
            "success": False,
            "written_files": [],
            "notes": notes,
            "error": "Builder returned no files",
        }

    # Validate all paths before writing anything
    errors = _validate_output_paths(files)
    if errors:
        logger.error("Build aborted — path validation failed: %s", errors)
        return {
            "success": False,
            "written_files": [],
            "notes": notes,
            "error": f"Path validation failed: {'; '.join(errors)}",
        }

    written = _write_files(files)
    logger.info("Build complete: %d file(s) written to workspace/output/", len(written))

    return {
        "success": True,
        "written_files": written,
        "notes": notes,
        "error": None,
    }
