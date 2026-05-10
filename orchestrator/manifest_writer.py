"""orchestrator/manifest_writer.py — Workspace manifest persistence.

Writes one JSON manifest per build to workspace/manifests/{plan_id}.json.
Records what was produced, what the verification found, and what can be rolled back.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

_NEXUS_ROOT = Path(__file__).resolve().parent.parent
_MANIFESTS_DIR = _NEXUS_ROOT / "workspace" / "manifests"

SCHEMA_VERSION = "1"


def _ensure_dir() -> None:
    _MANIFESTS_DIR.mkdir(parents=True, exist_ok=True)


def _verification_status(verify_result: dict, written_files: list) -> str:
    if not written_files:
        return "no_files"
    return "passed" if verify_result.get("passed", False) else "failed"


def _test_status(test_result: dict) -> str:
    if test_result.get("tests_run", 0) == 0:
        return "skipped"
    return "passed" if test_result.get("passed", False) else "failed"


def write_manifest(
    plan_id: str,
    goal: str,
    builder_used: str,
    written_files: list,
    verify_result: dict,
    test_result: dict,
    attempt_count: int,
    success: bool,
    error: str | None = None,
) -> Path:
    """Write a build manifest for plan_id. Returns the path written."""
    _ensure_dir()

    tests_created = [f for f in written_files if Path(f).stem.startswith("test_")]
    rollback_targets = [f for f in written_files if f not in tests_created]

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "plan_id": plan_id,
        "goal": goal,
        "builder": builder_used,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "attempt_count": attempt_count,
        "success": success,
        "files_written": written_files,
        "tests_created": tests_created,
        "rollback_targets": rollback_targets,
        "verification_status": _verification_status(verify_result, written_files),
        "test_status": _test_status(test_result),
        "verify_summary": verify_result.get("summary", ""),
        "test_summary": test_result.get("summary", ""),
        "errors": [error] if error else [],
    }

    path = _MANIFESTS_DIR / f"{plan_id}.json"
    path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return path


def read_manifest(plan_id: str) -> dict | None:
    """Return the manifest for plan_id, or None if not found."""
    path = _MANIFESTS_DIR / f"{plan_id}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def list_manifests(n: int = 20) -> list[dict]:
    """Return up to n manifests sorted newest-first by file mtime."""
    if not _MANIFESTS_DIR.exists():
        return []
    paths = sorted(
        _MANIFESTS_DIR.glob("*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    results = []
    for p in paths[:n]:
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            results.append(data)
        except Exception:
            pass
    return results
