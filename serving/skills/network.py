"""nexus-tools — Network Skill

Check Tailscale peer connectivity and general network health on NexusBody.
All operations are read-only.

Actions:
    check_peers    — list Tailscale peers and their reachability
    ping           — ping a specific host (Tailscale IP only)
    service_health — HTTP health check against a nexus service URL
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import subprocess

import httpx

from api_gateway.config.settings import get_settings
from serving.skills.execution_context import ExecutionContext
from serving.skills.skill_base import SafetyTier, SkillBase

logger = logging.getLogger("nexus.tools.skills.network")

# Only Tailscale IP ranges are allowed for ping (100.x.x.x)
_TAILSCALE_PREFIX = "100."


class NetworkSkill(SkillBase):
    name = "network"
    description = (
        "Check Tailscale peer connectivity and nexus service health. "
        "All read-only. Ping restricted to Tailscale IPs only."
    )
    safety_tier = SafetyTier.READ_ONLY
    version = "1.0.0"

    async def execute(self, context: ExecutionContext) -> dict:
        action = context.action
        dispatch = {
            "check_peers": self._check_peers,
            "ping": self._ping,
            "service_health": self._service_health,
        }
        handler = dispatch.get(action)
        if handler is None:
            return {"success": False, "error": f"Unknown action '{action}'"}
        return await handler(context)

    def get_capabilities(self) -> list[dict]:
        return [
            {"action": "check_peers", "description": "List all Tailscale peers and reachability"},
            {
                "action": "ping",
                "description": "Ping a Tailscale host",
                "params": {"host": "Tailscale IP (100.x.x.x)"},
            },
            {
                "action": "service_health",
                "description": "HTTP health check a nexus service",
                "params": {"service": "core|chat|coding|vtube|tools"},
            },
        ]

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    async def _check_peers(self, context: ExecutionContext) -> dict:
        """Run 'tailscale status' and parse peer list."""
        if not shutil.which("tailscale"):
            return {"success": False, "error": "tailscale CLI not found"}
        try:
            result = subprocess.run(
                ["tailscale", "status", "--json"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode != 0:
                return {"success": False, "error": result.stderr.strip()}
            import json
            data = json.loads(result.stdout)
            peers = {
                name: {
                    "ip": info.get("TailscaleIPs", [None])[0],
                    "online": info.get("Online", False),
                    "hostname": info.get("HostName", ""),
                }
                for name, info in data.get("Peer", {}).items()
            }
            return {"success": True, "peers": peers, "peer_count": len(peers)}
        except Exception as exc:
            logger.error("tailscale status failed: %s", exc)
            return {"success": False, "error": str(exc)}

    async def _ping(self, context: ExecutionContext) -> dict:
        """Ping a Tailscale IP. Blocked for non-Tailscale addresses."""
        host = context.get_param("host", "")
        if not host:
            return {"success": False, "error": "Missing required param: host"}

        # Security: only allow Tailscale IP range
        if not str(host).startswith(_TAILSCALE_PREFIX):
            logger.warning("SECURITY: Ping blocked for non-Tailscale host: %s", host)
            return {
                "success": False,
                "error": f"Ping is restricted to Tailscale IPs (100.x.x.x). Blocked: {host}",
            }

        try:
            result = subprocess.run(
                ["ping", "-c", "3", "-W", "2", host],
                capture_output=True, text=True, timeout=15,
            )
            reachable = result.returncode == 0
            return {
                "success": True,
                "host": host,
                "reachable": reachable,
                "output": result.stdout.strip().splitlines()[-1] if result.stdout else "",
            }
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    async def _service_health(self, context: ExecutionContext) -> dict:
        """HTTP GET /health on a named nexus service."""
        service = context.get_param("service", "")
        settings = get_settings()

        service_map = {
            "core": f"http://{settings.nexus_body_ip}:{settings.core_port}/health",
            "chat": f"http://{settings.nexus_body_ip}:{settings.chat_port}/health",
            "coding": f"http://{settings.nexus_body_ip}:{settings.coding_port}/health",
            "vtube": f"http://{settings.nexus_server_ip}:{settings.vtube_port}/health",
            "tools": f"http://{settings.nexus_body_ip}:{settings.tools_port}/health",
        }

        if service not in service_map:
            return {
                "success": False,
                "error": f"Unknown service '{service}'. Options: {list(service_map.keys())}",
            }

        url = service_map[service]
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(url)
                return {
                    "success": True,
                    "service": service,
                    "url": url,
                    "status_code": resp.status_code,
                    "healthy": resp.status_code == 200,
                }
        except Exception as exc:
            return {
                "success": False,
                "service": service,
                "healthy": False,
                "error": str(exc),
            }
