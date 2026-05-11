"""Workstation skill — lets Nexus call tools on WorkstationPrime.

Calls the Nexus Desktop tool server (Express HTTP on port 8889) over Tailscale.

Requires in .env (on NexusBody):
    WORKSTATION_TOOL_URL=http://100.99.219.91:8889
    WORKSTATION_TOOL_TOKEN=<same token as WorkstationPrime .env>

Safety tiers (per action):
    READ_ONLY:       get_info, list_dir, get_clipboard, screenshot
    NON_DESTRUCTIVE: read_file, open_path
    DESTRUCTIVE:     write_file, set_clipboard, run_command
                     (blocked from automated sources — requires human approval)

Part C (proactive):
    Heartbeat/cron/reflex can call READ_ONLY and NON_DESTRUCTIVE actions freely.
    DESTRUCTIVE actions from automation go to the approval queue.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import httpx

from serving.skills.execution_context import ExecutionContext
from serving.skills.skill_base import SafetyTier, SkillBase

logger = logging.getLogger("nexus.skills.workstation")

# ── Load .env from Nexus root ────────────────────────────────────────────────
_ROOT = Path(__file__).resolve().parent.parent.parent
_env_file = _ROOT / ".env"
if _env_file.exists():
    for _line in _env_file.read_text(encoding="utf-8", errors="replace").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _, _v = _line.partition("=")
            os.environ.setdefault(_k.strip(), _v.strip())

# ── Config ───────────────────────────────────────────────────────────────────
_URL     = os.getenv("WORKSTATION_TOOL_URL",   "http://100.99.219.91:8889")
_TOKEN   = os.getenv("WORKSTATION_TOOL_TOKEN", "dev-token-change-me")
_TIMEOUT = 60

_AUTOMATED_SOURCES = {"heartbeat", "cron", "reflex", "automation"}

# Actions that must not run from automated sources without human approval
_DESTRUCTIVE_ACTIONS = {"run_command", "write_file", "set_clipboard"}

# Actions that return potentially large payloads — log at debug, not info
_QUIET_ACTIONS = {"screenshot", "read_file"}


# ── HTTP caller ───────────────────────────────────────────────────────────────

def _call(tool: str, params: dict[str, Any]) -> dict:
    headers = {
        "Authorization": f"Bearer {_TOKEN}",
        "Content-Type": "application/json",
    }
    try:
        resp = httpx.post(
            f"{_URL}/tool/{tool}",
            json=params,
            headers=headers,
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        if not data.get("ok"):
            raise RuntimeError(data.get("error", "tool returned ok=false"))
        return data["result"]
    except httpx.ConnectError:
        raise RuntimeError(
            f"Cannot reach WorkstationPrime at {_URL} — is Nexus Desktop running?"
        )


# ── Skill ─────────────────────────────────────────────────────────────────────

class WorkstationSkill(SkillBase):
    name = "workstation"
    description = (
        "Control WorkstationPrime over Tailscale via the Nexus Desktop tool server. "
        "Read/write files, run shell commands, take screenshots, manage clipboard, "
        "open paths, get system info."
    )
    safety_tier = SafetyTier.DESTRUCTIVE
    version = "1.0.0"

    async def execute(self, context: ExecutionContext) -> dict:
        action = context.action

        # Block destructive actions from automated sources
        if action in _DESTRUCTIVE_ACTIONS and context.source.value in _AUTOMATED_SOURCES:
            return {
                "success": False,
                "error": (
                    f"workstation.{action} is blocked from automated source "
                    f"'{context.source.value}'. Route through approval queue."
                ),
            }

        handlers = {
            "get_info":      self._get_info,
            "list_dir":      self._list_dir,
            "read_file":     self._read_file,
            "write_file":    self._write_file,
            "run_command":   self._run_command,
            "get_clipboard": self._get_clipboard,
            "set_clipboard": self._set_clipboard,
            "screenshot":    self._screenshot,
            "open_path":     self._open_path,
        }

        handler = handlers.get(action)
        if handler is None:
            return {"success": False, "error": f"Unknown action '{action}'. Available: {list(handlers)}"}

        try:
            result = await handler(context)
            if action not in _QUIET_ACTIONS:
                logger.info("workstation.%s OK (source=%s)", action, context.source.value)
            else:
                logger.debug("workstation.%s OK", action)
            return {"success": True, **result}
        except Exception as exc:
            logger.error("workstation.%s failed: %s", action, exc)
            return {"success": False, "error": str(exc)}

    def get_capabilities(self) -> list[dict]:
        return [
            {
                "action": "get_info",
                "description": "Get WorkstationPrime system info (hostname, RAM, CPU, etc.)",
                "params": {},
                "tier": "READ_ONLY",
            },
            {
                "action": "list_dir",
                "description": "List files in a directory on WorkstationPrime",
                "params": {"dir_path": "path (~ supported)", "recursive": "bool (default false)"},
                "tier": "READ_ONLY",
            },
            {
                "action": "read_file",
                "description": "Read a file from WorkstationPrime",
                "params": {"file_path": "path (~ supported)", "max_bytes": "int (default 524288)"},
                "tier": "NON_DESTRUCTIVE",
            },
            {
                "action": "write_file",
                "description": "Write content to a file on WorkstationPrime [DESTRUCTIVE]",
                "params": {"file_path": "path", "content": "string", "create_dirs": "bool (default true)"},
                "tier": "DESTRUCTIVE",
            },
            {
                "action": "run_command",
                "description": "Run a shell command on WorkstationPrime [DESTRUCTIVE]",
                "params": {"command": "string", "cwd": "path (optional)", "timeout_ms": "int (default 30000)"},
                "tier": "DESTRUCTIVE",
            },
            {
                "action": "get_clipboard",
                "description": "Read the clipboard on WorkstationPrime",
                "params": {},
                "tier": "READ_ONLY",
            },
            {
                "action": "set_clipboard",
                "description": "Write text to the clipboard on WorkstationPrime [DESTRUCTIVE]",
                "params": {"text": "string"},
                "tier": "DESTRUCTIVE",
            },
            {
                "action": "screenshot",
                "description": "Take a screenshot of WorkstationPrime's screen",
                "params": {"output_path": "path to save PNG (optional — returns base64 if omitted)"},
                "tier": "READ_ONLY",
            },
            {
                "action": "open_path",
                "description": "Open a file or URL in its default app on WorkstationPrime",
                "params": {"target_path": "path or URL"},
                "tier": "NON_DESTRUCTIVE",
            },
        ]

    # ── Action handlers ───────────────────────────────────────────────────────

    async def _get_info(self, _ctx: ExecutionContext) -> dict:
        return _call("get_info", {})

    async def _list_dir(self, ctx: ExecutionContext) -> dict:
        return _call("list_dir", {
            "dir_path":   ctx.require_param("dir_path"),
            "recursive":  ctx.get_param("recursive", False),
            "show_hidden": ctx.get_param("show_hidden", False),
        })

    async def _read_file(self, ctx: ExecutionContext) -> dict:
        return _call("read_file", {
            "file_path": ctx.require_param("file_path"),
            "max_bytes": ctx.get_param("max_bytes", 524288),
        })

    async def _write_file(self, ctx: ExecutionContext) -> dict:
        return _call("write_file", {
            "file_path":   ctx.require_param("file_path"),
            "content":     ctx.require_param("content"),
            "create_dirs": ctx.get_param("create_dirs", True),
        })

    async def _run_command(self, ctx: ExecutionContext) -> dict:
        return _call("run_command", {
            "command":    ctx.require_param("command"),
            "cwd":        ctx.get_param("cwd"),
            "timeout_ms": ctx.get_param("timeout_ms", 30000),
        })

    async def _get_clipboard(self, _ctx: ExecutionContext) -> dict:
        return _call("get_clipboard", {})

    async def _set_clipboard(self, ctx: ExecutionContext) -> dict:
        return _call("set_clipboard", {"text": ctx.require_param("text")})

    async def _screenshot(self, ctx: ExecutionContext) -> dict:
        params = {}
        if ctx.get_param("output_path"):
            params["output_path"] = ctx.get_param("output_path")
        return _call("screenshot", params)

    async def _open_path(self, ctx: ExecutionContext) -> dict:
        return _call("open_path", {"target_path": ctx.require_param("target_path")})


# ── Standalone smoke test ─────────────────────────────────────────────────────
if __name__ == "__main__":
    import asyncio
    import json
    import sys

    async def _smoke():
        skill = WorkstationSkill()
        print(f"Skill: {skill!r}")
        print(f"Capabilities: {len(skill.get_capabilities())}")
        print()

        from safety.output_filters.safety_tier_gate import TaskSource

        ctx = ExecutionContext(
            skill_name="workstation",
            action="get_info",
            source=TaskSource.HUMAN,
        )
        result = await skill.execute(ctx)
        if result["success"]:
            print("get_info OK:", json.dumps({k: v for k, v in result.items() if k != "success"}, indent=2))
        else:
            print("FAIL:", result["error"])
            sys.exit(1)

        ctx2 = ExecutionContext(
            skill_name="workstation",
            action="list_dir",
            params={"dir_path": "~"},
            source=TaskSource.HUMAN,
        )
        result2 = await skill.execute(ctx2)
        if result2["success"]:
            print(f"list_dir ~ OK: {result2['count']} entries")
        else:
            print("FAIL:", result2["error"])
            sys.exit(1)

        print("\nAll OK.")

    asyncio.run(_smoke())
