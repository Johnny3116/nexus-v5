"""test_runner.py — runs generated Python test files in sandbox.

Executes immediately after verifier confirms syntax is OK. Discovers test
files from the written_files list (matching test_*.py / *_test.py pattern)
and runs each with the system Python interpreter.

Milestone 9 hard limits:
    - Only runs .py files inside workspace/output/ (path traversal blocked)
    - Working directory set to workspace/output/ for each run
    - 15-second per-file timeout
    - Output capped at 4KB to prevent WS payload bloat
    - No pytest dependency — uses plain `python <file>` (stdlib unittest works)
"""

from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

_NEXUS_ROOT = Path(__file__).resolve().parents[1]
_WORKSPACE = _NEXUS_ROOT / "workspace" / "output"
_TIMEOUT = 15      # seconds per test file
_MAX_OUTPUT = 4096  # characters, total across all test files


def _is_test_file(rel_path: str) -> bool:
    stem = Path(rel_path).stem
    suffix = Path(rel_path).suffix.lower()
    return suffix == ".py" and (stem.startswith("test_") or stem.endswith("_test"))


def _safe_abs(rel_path: str) -> "Path | None":
    """Resolve rel_path under workspace/output/ — returns None if traversal detected."""
    try:
        abs_path = (_WORKSPACE / Path(rel_path).name).resolve()
        abs_path.relative_to(_WORKSPACE.resolve())
        return abs_path
    except (ValueError, Exception):
        return None


def run_tests(written_files: list) -> dict:
    """Run Python test files from written_files and return a test_result dict.

    Args:
        written_files: list of relative file paths produced by the builder.
                       Only entries matching the test file pattern are run.

    Returns:
        {
            "passed": bool,
            "tests_run": int,
            "output": str,      # combined stdout+stderr, capped at 4KB
            "summary": str,
        }
    """
    test_files = [f for f in written_files if _is_test_file(f)]

    if not test_files:
        return {
            "passed": True,
            "tests_run": 0,
            "output": "",
            "summary": "no test files",
        }

    combined: list = []
    all_passed = True
    tests_run = 0

    for rel_path in test_files:
        abs_path = _safe_abs(rel_path)
        if abs_path is None or not abs_path.exists():
            logger.warning("Test runner: %s not found in workspace/output/", rel_path)
            combined.append(f"[SKIP] {rel_path}: not found in workspace/output/")
            continue

        tests_run += 1
        combined.append(f"--- {rel_path} ---")

        try:
            proc = subprocess.run(
                [sys.executable, str(abs_path)],
                cwd=str(_WORKSPACE),
                capture_output=True,
                text=True,
                timeout=_TIMEOUT,
            )
            out = (proc.stdout + proc.stderr).strip()
            combined.append(out if out else "(no output)")
            if proc.returncode == 0:
                logger.info("Test PASS  %s", rel_path)
            else:
                all_passed = False
                logger.warning("Test FAIL  %s (exit code %d)", rel_path, proc.returncode)
        except subprocess.TimeoutExpired:
            combined.append(f"TIMEOUT: exceeded {_TIMEOUT}s")
            all_passed = False
            logger.warning("Test TIMEOUT %s", rel_path)
        except Exception as exc:
            combined.append(f"ERROR: {exc}")
            all_passed = False
            logger.error("Test runner error for %s: %s", rel_path, exc)

    output = "\n".join(combined)
    if len(output) > _MAX_OUTPUT:
        output = output[:_MAX_OUTPUT] + "\n... (truncated)"

    status = "all passed" if all_passed else "some failed"
    summary = f"{tests_run} test file(s) run — {status}"

    return {
        "passed": all_passed,
        "tests_run": tests_run,
        "output": output,
        "summary": summary,
    }
