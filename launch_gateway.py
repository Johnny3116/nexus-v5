"""Launch the Nexus API gateway as a detached background process.

Uses DETACHED_PROCESS + CREATE_NEW_PROCESS_GROUP so the child survives
after the SSH session (parent) exits. Sets PYTHONPATH explicitly so
uvicorn can find api_gateway and its sibling packages.

Usage:
    python C:/Users/Nexus/Nexus/launch_gateway.py
"""
import sys
import subprocess
import os
import socket
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path("C:/Users/Nexus/Nexus")
PYTHON = r"C:\Users\Nexus\AppData\Local\Programs\Python\Python312\python.exe"
LOG = ROOT / "logs" / "api-gateway.log"
PORT = 8100


def port_in_use(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


if port_in_use(PORT):
    print(f"Port {PORT} already in use -- gateway is running")
    sys.exit(0)

# Ensure logs dir
LOG.parent.mkdir(exist_ok=True)

env = os.environ.copy()
env.update({
    "PYTHONUNBUFFERED": "1",
    "WHISPER_DEVICE": "cpu",
    "WHISPER_COMPUTE_TYPE": "int8",
    "WHISPER_MODEL": "base",
    # Explicitly set PYTHONPATH so uvicorn can find api_gateway and friends
    "PYTHONPATH": str(ROOT),
})

cmd = [
    PYTHON, "-m", "uvicorn",
    "api_gateway.main:app",
    "--host", "127.0.0.1",
    "--port", str(PORT),
]

DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200

with open(LOG, "a", encoding="utf-8") as logfile:
    proc = subprocess.Popen(
        cmd,
        cwd=str(ROOT),
        env=env,
        stdout=logfile,
        stderr=logfile,
        creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP,
        close_fds=True,
    )

print(f"Gateway launched: PID {proc.pid} on 127.0.0.1:{PORT}")
print(f"Log:  {LOG}")
print(f"Test: curl http://127.0.0.1:{PORT}/health")
