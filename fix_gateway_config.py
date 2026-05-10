"""Fix gateway configuration:
  1. Add PYTHONPATH to start-api-gateway.bat (fixes module import)
  2. Create root-level start_api_gateway.bat (fixes scheduled task path)
  3. Add NEXUS_GATEWAY_URL=http://127.0.0.1:8100 to .env (fixes llm_scr.py port)
  4. Update scheduled task to point to the correct bat

Usage:
    python C:/Users/Nexus/Nexus/fix_gateway_config.py
"""
import sys
import subprocess
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path("C:/Users/Nexus/Nexus")
BAT_REAL = ROOT / ".claude/scripts/start-api-gateway.bat"
BAT_ROOT = ROOT / "start_api_gateway.bat"
ENV_FILE = ROOT / ".env"

print("=" * 55)
print("  Fixing gateway configuration")
print("=" * 55)

# -- 1. Add PYTHONPATH to the real bat file -------------------------
print("\n[1/4] Updating start-api-gateway.bat to set PYTHONPATH...")
content = BAT_REAL.read_text(encoding="utf-8", errors="replace")
if "PYTHONPATH" in content:
    print("  SKIP -- PYTHONPATH already set")
else:
    content = content.replace(
        "set PYTHONUNBUFFERED=1",
        "set PYTHONUNBUFFERED=1\nset PYTHONPATH=C:\\Users\\Nexus\\Nexus"
    )
    BAT_REAL.write_text(content, encoding="utf-8")
    print("  OK -- PYTHONPATH=C:\\Users\\Nexus\\Nexus added")

# -- 2. Create root-level bat that delegates to real bat ------------
print("\n[2/4] Creating root-level start_api_gateway.bat...")
if BAT_ROOT.exists():
    print("  SKIP -- already exists")
else:
    BAT_ROOT.write_text(
        '@echo off\ncall "C:\\Users\\Nexus\\Nexus\\.claude\\scripts\\start-api-gateway.bat"\n',
        encoding="utf-8"
    )
    print("  OK -- start_api_gateway.bat created at Nexus root")

# -- 3. Add NEXUS_GATEWAY_URL to .env -------------------------------
print("\n[3/4] Adding NEXUS_GATEWAY_URL to .env...")
env_text = ENV_FILE.read_text(encoding="utf-8", errors="replace")
if "NEXUS_GATEWAY_URL" in env_text:
    print("  SKIP -- already set")
else:
    env_text = env_text.rstrip() + "\nNEXUS_GATEWAY_URL=http://127.0.0.1:8100\n"
    ENV_FILE.write_text(env_text, encoding="utf-8")
    print("  OK -- NEXUS_GATEWAY_URL=http://127.0.0.1:8100 added")

# -- 4. Update scheduled task ---------------------------------------
print("\n[4/4] Updating Nexus-API-Gateway scheduled task path...")
result = subprocess.run(
    ["schtasks", "/change", "/tn", "Nexus-API-Gateway",
     "/tr", str(BAT_ROOT)],
    capture_output=True, text=True, encoding="utf-8", errors="replace"
)
if result.returncode == 0:
    print(f"  OK -- task updated to: {BAT_ROOT}")
else:
    print(f"  WARN -- schtasks update: {result.stderr.strip()}")
    print(f"  (You can update manually if needed)")

print("\n" + "=" * 55)
print("  Config fix complete")
print("  Restart gateway: python launch_gateway.py")
print("=" * 55)
