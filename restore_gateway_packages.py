"""Restore all gateway dependencies from safe-to-delete/archive.

Run this multiple times — each run fixes the next error and shows the next missing piece.
"""
import sys
import shutil
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path("C:/Users/Nexus/Nexus")
ARCHIVE = ROOT / "safe-to-delete" / "archive"

# -- Direct archive/ -> root/ restores --
root_ops = [
    ("api_gateway",    "api_gateway"),
    ("kv_cache",       "kv_cache"),
    ("orchestration",  "orchestration"),
]

# -- archive/ -> serving/ restores --
serving_ops = [
    ("brain_pool",  "serving/brain_pool"),
    ("skills",      "serving/skills"),
    ("streaming",   "serving/streaming"),
]

# -- safety package: archive dirs -> safety/subpkg --
safety_ops = [
    ("safety-input_filters",  "safety/input_filters"),
    ("safety-output_filters", "safety/output_filters"),
]


def restore(src_name, dst_rel, label=None):
    src = ARCHIVE / src_name
    dst = ROOT / dst_rel
    label = label or dst_rel
    if not src.exists():
        print(f"  [MISS]  {src_name} not in archive")
        return False
    if dst.exists():
        print(f"  [EXIST] {label}")
        return True
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    print(f"  [OK]    {src_name} -> {label}")
    return True


def ensure_init(dir_path):
    init = dir_path / "__init__.py"
    if not init.exists():
        init.write_text("")
        print(f"  [INIT]  {init.relative_to(ROOT)}")


print("=" * 55)
print("  Restoring gateway packages")
print("=" * 55)

for src, dst in root_ops:
    restore(src, dst)

for src, dst in serving_ops:
    restore(src, dst)

# safety package
safety_dir = ROOT / "safety"
if not safety_dir.exists():
    safety_dir.mkdir()
ensure_init(safety_dir)

for archive_name, subpkg_rel in safety_ops:
    restore(archive_name, subpkg_rel)
    subpkg_dir = ROOT / subpkg_rel
    if subpkg_dir.exists():
        ensure_init(subpkg_dir)

# Check for safety/identity (soul_container)
# It may live inside safety-input_filters or a separate archive
identity_dir = ROOT / "safety" / "identity"
if not identity_dir.exists():
    # Check if soul_container.py is anywhere in archive
    candidates = list(ARCHIVE.rglob("soul_container.py"))
    if candidates:
        src_file = candidates[0]
        identity_dir.mkdir(parents=True, exist_ok=True)
        ensure_init(identity_dir)
        shutil.copy2(src_file, identity_dir / "soul_container.py")
        print(f"  [OK]    soul_container.py -> safety/identity/")
    else:
        print(f"  [MISS]  soul_container.py not found in archive -- safety.identity.soul_container will fail")

print()
print("Testing import...")
import subprocess, sys as _sys
result = subprocess.run(
    [r"C:\Users\Nexus\AppData\Local\Programs\Python\Python312\python.exe",
     "-c", "import api_gateway.main; print('IMPORT OK')"],
    cwd=str(ROOT),
    capture_output=True, text=True
)
if result.stdout:
    print(result.stdout.strip())
if result.returncode != 0:
    # Show just the last error line
    err = result.stderr.strip()
    last_lines = err.split("\n")[-3:]
    for l in last_lines:
        print(l)
