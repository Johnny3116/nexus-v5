"""Test gateway startup: run uvicorn for 10 seconds and capture output.

Shows the first errors (if any) so we can fix them iteratively.

Usage:
    python C:/Users/Nexus/Nexus/test_gateway_start.py
"""
import sys
import os
import subprocess
import time
import socket
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path("C:/Users/Nexus/Nexus")
PYTHON = r"C:\Users\Nexus\AppData\Local\Programs\Python\Python312\python.exe"
PORT = 8100

env = os.environ.copy()
env["PYTHONPATH"] = str(ROOT)
env["PYTHONUNBUFFERED"] = "1"
env["WHISPER_DEVICE"] = "cpu"
env["WHISPER_COMPUTE_TYPE"] = "int8"

cmd = [PYTHON, "-m", "uvicorn", "api_gateway.main:app",
       "--host", "127.0.0.1", "--port", str(PORT)]

print(f"Launching: {' '.join(cmd)}")
print(f"PYTHONPATH: {ROOT}")
print()

proc = subprocess.Popen(
    cmd,
    cwd=str(ROOT),
    env=env,
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    text=True,
    encoding="utf-8",
    errors="replace",
)

# Collect output for 10 seconds
start = time.time()
lines = []
while time.time() - start < 10:
    if proc.poll() is not None:
        break
    try:
        line = proc.stdout.readline()
        if line:
            lines.append(line.rstrip())
            print(line.rstrip())
    except Exception:
        break

time.sleep(0.5)

# Check if it's running
def port_open(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0

if proc.poll() is None:
    if port_open(PORT):
        print(f"\nGateway is UP on port {PORT}")
    else:
        print(f"\nProcess running but port {PORT} not open yet")
    proc.terminate()
else:
    print(f"\nProcess exited with code: {proc.returncode}")
    # Read remaining output
    remaining = proc.stdout.read()
    if remaining:
        print(remaining)
