"""verifier.py — post-build syntax and sanity checks on generated files.

Runs immediately after the builder writes files. Does not execute code.
Checks:
  .py  → py_compile (syntax only)
  .json → json.loads
  .js/.ts → heuristic (balanced braces, no obvious syntax traps)
  other → existence check only

Returns a verify_result dict, never raises.
Milestone 5 hard limit: no shell execution of user code.
"""

from __future__ import annotations

import json
import logging
import py_compile
import tempfile
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_NEXUS_ROOT = Path(__file__).resolve().parents[1]


def _check_python(path: Path) -> Optional[str]:
    try:
        py_compile.compile(str(path), doraise=True)
        return None
    except py_compile.PyCompileError as e:
        return str(e)


def _check_json(path: Path) -> Optional[str]:
    try:
        json.loads(path.read_text(encoding="utf-8"))
        return None
    except json.JSONDecodeError as e:
        return str(e)


def _check_js(path: Path) -> Optional[str]:
    """Heuristic: check brace balance and file is non-empty."""
    try:
        content = path.read_text(encoding="utf-8")
        if not content.strip():
            return "file is empty"
        opens = content.count("{")
        closes = content.count("}")
        if abs(opens - closes) > 5:
            return f"brace imbalance: {opens} open, {closes} close"
        return None
    except Exception as e:
        return str(e)


def verify_files(written_files: list[str]) -> dict:
    """Check each written file and return a verify_result dict.

    Returns:
        {
            "passed": bool,
            "results": [{"file": str, "ok": bool, "error": str|None}],
            "summary": str,
        }
    """
    results = []
    for rel_path in written_files:
        abs_path = (_NEXUS_ROOT / rel_path).resolve()
        error: Optional[str] = None

        if not abs_path.exists():
            error = "file not found after build"
        else:
            suffix = abs_path.suffix.lower()
            if suffix == ".py":
                error = _check_python(abs_path)
            elif suffix == ".json":
                error = _check_json(abs_path)
            elif suffix in (".js", ".ts", ".jsx", ".tsx"):
                error = _check_js(abs_path)
            # All other extensions: existence check already passed

        results.append({"file": rel_path, "ok": error is None, "error": error})
        if error:
            logger.warning("Verify FAIL %s: %s", rel_path, error)
        else:
            logger.info("Verify OK  %s", rel_path)

    passed = all(r["ok"] for r in results)
    ok_count = sum(1 for r in results if r["ok"])
    summary = f"{ok_count}/{len(results)} files passed verification"
    return {"passed": passed, "results": results, "summary": summary}
