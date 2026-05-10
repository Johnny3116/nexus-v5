"""nexus-tools — Shell Command Skill

Execute shell commands on NexusBody with strict safety controls.

Safety tiers:
    NON_DESTRUCTIVE: run_safe (allowlisted commands only)
    DESTRUCTIVE:     run (any command — approval required from automation)

SECURITY:
    - run_safe uses a strict command allowlist. Commands not in the list are blocked.
    - run requires DESTRUCTIVE approval when triggered by automation.
    - All commands run with a timeout (default 30s, max 300s).
    - No interactive TTY. stdout/stderr captured.
    - Shell=False to prevent injection. Commands are split into argv lists.

Actions:
    run_safe  — execute an allowlisted command (NON_DESTRUCTIVE)
    run       — execute any command (DESTRUCTIVE, requires approval from automation)
"""

from __future__ import annotations

import asyncio
import logging
import shlex
from typing import Optional

from serving.skills.execution_context import ExecutionContext
from serving.skills.skill_base import SafetyTier, SkillBase

logger = logging.getLogger("nexus.tools.skills.shell_cmd")

_DEFAULT_TIMEOUT = 30
_MAX_TIMEOUT = 300

# Commands allowed for run_safe (non-destructive operations)
SAFE_COMMAND_PREFIXES = {
    "git status", "git log", "git branch", "git diff",
    "ls", "pwd", "echo", "cat", "head", "tail",
    "ps", "top -b -n 1", "df -h", "free -h", "uname",
    "python --version", "python3 --version", "pip list", "pip show",
    "ollama list", "ollama show",
    "docker ps", "docker images", "docker stats --no-stream",
    "systemctl status", "journalctl -n",
    "tailscale status",
    "nvidia-smi",
    "uptime", "date", "hostname",
}

_AUTOMATED_SOURCES = {"heartbeat", "cron", "reflex"}


class ShellCmdSkill(SkillBase):
    name = "shell_cmd"
    description = (
        "Execute shell commands on NexusBody. "
        "run_safe: allowlisted read-only commands only. "
        "run: any command — requires approval when triggered by automation. "
        "Commands run with timeout, no interactive TTY."
    )
    safety_tier = SafetyTier.DESTRUCTIVE
    version = "1.0.0"

    async def execute(self, context: ExecutionContext) -> dict:
        action = context.action

        if action == "run_safe":
            return await self._run_safe(context)
        elif action == "run":
            if context.source.value in _AUTOMATED_SOURCES:
                return {
                    "success": False,
                    "error": (
                        "shell_cmd.run is blocked from automated source "
                        f"'{context.source.value}'. Use approval queue."
                    ),
                }
            return await self._run(context)
        else:
            return {"success": False, "error": f"Unknown action '{action}'"}

    def get_capabilities(self) -> list[dict]:
        return [
            {
                "action": "run_safe",
                "description": "Run an allowlisted read-only shell command",
                "params": {"command": "command string", "timeout": "seconds (default 30)"},
            },
            {
                "action": "run",
                "description": "Run any shell command [DESTRUCTIVE — approval required from automation]",
                "params": {"command": "command string", "timeout": "seconds (default 30, max 300)"},
            },
        ]

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    async def _run_safe(self, context: ExecutionContext) -> dict:
        command = context.require_param("command")
        timeout = min(int(context.get_param("timeout", _DEFAULT_TIMEOUT)), _MAX_TIMEOUT)

        # Allowlist check
        if not self._is_safe_command(command):
            logger.warning("SECURITY: run_safe blocked command: %r", command)
            return {
                "success": False,
                "error": f"Command not in safe allowlist: {command!r}",
                "allowed_prefixes": sorted(SAFE_COMMAND_PREFIXES),
            }

        return await self._execute_command(command, timeout)

    async def _run(self, context: ExecutionContext) -> dict:
        command = context.require_param("command")
        timeout = min(int(context.get_param("timeout", _DEFAULT_TIMEOUT)), _MAX_TIMEOUT)
        return await self._execute_command(command, timeout)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _is_safe_command(command: str) -> bool:
        """Check if the command starts with an allowed prefix."""
        cmd_lower = command.strip().lower()
        return any(cmd_lower.startswith(prefix.lower()) for prefix in SAFE_COMMAND_PREFIXES)

    @staticmethod
    async def _execute_command(command: str, timeout: int) -> dict:
        """Execute the command and return captured output."""
        try:
            argv = shlex.split(command)
        except ValueError as exc:
            return {"success": False, "error": f"Command parse error: {exc}"}

        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            stdout = stdout_b.decode(errors="replace").strip()
            stderr = stderr_b.decode(errors="replace").strip()
            return {
                "success": proc.returncode == 0,
                "returncode": proc.returncode,
                "stdout": stdout,
                "stderr": stderr,
                "command": command,
            }
        except asyncio.TimeoutError:
            return {"success": False, "error": f"Command timed out after {timeout}s", "command": command}
        except FileNotFoundError:
            argv0 = shlex.split(command)[0] if command else ""
            return {"success": False, "error": f"Command not found: {argv0!r}"}
        except Exception as exc:
            return {"success": False, "error": str(exc), "command": command}
