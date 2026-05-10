"""nexus-tools — Ollama Manager Skill

Manage the Ollama instance running on NexusBody.

Safety tiers:
    READ_ONLY:       status, list_models, show
    NON_DESTRUCTIVE: pull (downloads a model)
    DESTRUCTIVE:     restart, throttle, delete_model

Actions:
    status        — Ollama running status and loaded model
    list_models   — list downloaded models
    show          — show details of a specific model
    pull          — pull/download a model from Ollama hub
    restart       — restart the Ollama service [DESTRUCTIVE]
    throttle      — reduce Ollama resource limits (GPU thermal protection) [DESTRUCTIVE]
    delete_model  — delete a downloaded model [DESTRUCTIVE]
"""

from __future__ import annotations

import asyncio
import logging

import httpx

from api_gateway.config.settings import get_settings
from serving.skills.execution_context import ExecutionContext
from serving.skills.skill_base import SafetyTier, SkillBase

logger = logging.getLogger("nexus.tools.skills.ollama_mgr")

_AUTOMATED_SOURCES = {"heartbeat", "cron", "reflex"}
_DESTRUCTIVE_ACTIONS = {"restart", "throttle", "delete_model"}


class OllamaMgrSkill(SkillBase):
    name = "ollama_mgr"
    description = (
        "Manage the Ollama instance on NexusBody: status, model list, pull models. "
        "Destructive operations (restart, throttle, delete) require approval when "
        "triggered by automation."
    )
    safety_tier = SafetyTier.DESTRUCTIVE
    version = "1.0.0"

    async def execute(self, context: ExecutionContext) -> dict:
        action = context.action

        if action in _DESTRUCTIVE_ACTIONS and context.source.value in _AUTOMATED_SOURCES:
            return {
                "success": False,
                "error": (
                    f"ollama_mgr.{action} is destructive and blocked from automated source "
                    f"'{context.source.value}'. Route through approval queue."
                ),
            }

        dispatch = {
            "status": self._status,
            "list_models": self._list_models,
            "show": self._show,
            "pull": self._pull,
            "restart": self._restart,
            "throttle": self._throttle,
            "delete_model": self._delete_model,
        }

        handler = dispatch.get(action)
        if handler is None:
            return {"success": False, "error": f"Unknown action '{action}'"}
        return await handler(context)

    def get_capabilities(self) -> list[dict]:
        return [
            {"action": "status", "description": "Check if Ollama is running and what model is loaded"},
            {"action": "list_models", "description": "List all downloaded Ollama models"},
            {"action": "show", "description": "Show model details", "params": {"model": "model name"}},
            {"action": "pull", "description": "Download a model from Ollama hub", "params": {"model": "model name"}},
            {"action": "restart", "description": "Restart Ollama service [DESTRUCTIVE]"},
            {"action": "throttle", "description": "Reduce GPU usage for thermal protection [DESTRUCTIVE]"},
            {"action": "delete_model", "description": "Delete a downloaded model [DESTRUCTIVE]", "params": {"model": "model name"}},
        ]

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    async def _status(self, context: ExecutionContext) -> dict:
        settings = get_settings()
        url = f"{settings.ollama_host}/api/ps"
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                data = resp.json()
                models = data.get("models", [])
                return {
                    "success": True,
                    "running": True,
                    "loaded_models": [m.get("name") for m in models],
                    "model_count": len(models),
                }
        except httpx.ConnectError:
            return {"success": True, "running": False, "error": "Ollama not reachable"}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    async def _list_models(self, context: ExecutionContext) -> dict:
        settings = get_settings()
        url = f"{settings.ollama_host}/api/tags"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                data = resp.json()
                models = [
                    {
                        "name": m.get("name"),
                        "size_gb": round(m.get("size", 0) / (1024 ** 3), 2),
                        "modified": m.get("modified_at", ""),
                    }
                    for m in data.get("models", [])
                ]
                return {"success": True, "models": models, "count": len(models)}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    async def _show(self, context: ExecutionContext) -> dict:
        model = context.require_param("model")
        settings = get_settings()
        url = f"{settings.ollama_host}/api/show"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(url, json={"name": model})
                resp.raise_for_status()
                data = resp.json()
                return {
                    "success": True,
                    "model": model,
                    "details": {
                        "family": data.get("details", {}).get("family"),
                        "parameter_size": data.get("details", {}).get("parameter_size"),
                        "quantization_level": data.get("details", {}).get("quantization_level"),
                    },
                }
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    async def _pull(self, context: ExecutionContext) -> dict:
        model = context.require_param("model")
        settings = get_settings()
        url = f"{settings.ollama_host}/api/pull"
        try:
            async with httpx.AsyncClient(timeout=300.0) as client:
                resp = await client.post(url, json={"name": model, "stream": False})
                resp.raise_for_status()
                return {"success": True, "model": model, "status": "downloaded"}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    async def _restart(self, context: ExecutionContext) -> dict:
        try:
            proc = await asyncio.create_subprocess_exec(
                "systemctl", "restart", "ollama",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=30)
            if proc.returncode != 0:
                return {"success": False, "error": stderr_b.decode(errors="replace").strip()}
            return {"success": True, "message": "Ollama service restarted"}
        except FileNotFoundError:
            return {"success": False, "error": "systemctl not available (not a systemd host)"}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    async def _throttle(self, context: ExecutionContext) -> dict:
        """Signal Ollama to unload current model to reduce GPU/CPU pressure."""
        settings = get_settings()
        url = f"{settings.ollama_host}/api/generate"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                # Sending keep_alive=0 unloads the model from VRAM
                resp = await client.post(
                    url,
                    json={
                        "model": settings.ollama_model,
                        "prompt": "",
                        "keep_alive": 0,
                    },
                )
                return {
                    "success": resp.status_code < 400,
                    "message": "Requested Ollama model unload (keep_alive=0)",
                }
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    async def _delete_model(self, context: ExecutionContext) -> dict:
        model = context.require_param("model")
        settings = get_settings()
        url = f"{settings.ollama_host}/api/delete"
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.delete(url, json={"name": model})
                return {
                    "success": resp.status_code == 200,
                    "model": model,
                    "deleted": resp.status_code == 200,
                }
        except Exception as exc:
            return {"success": False, "error": str(exc)}
