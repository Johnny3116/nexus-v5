"""nexus-tools — System Monitor Skill

Read CPU, RAM, disk, and GPU telemetry from NexusBody.
All operations are read-only. No side effects.

Actions:
    check_resources  — full snapshot: CPU, RAM, disk, GPU
    cpu              — CPU percent only
    ram              — RAM usage only
    disk             — Disk usage only
    gpu_temp         — GPU temperature (requires pynvml or nvidia-smi)
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from typing import Any

import psutil

from serving.skills.execution_context import ExecutionContext
from serving.skills.skill_base import SafetyTier, SkillBase

logger = logging.getLogger("nexus.tools.skills.system_monitor")


class SystemMonitorSkill(SkillBase):
    name = "system_monitor"
    description = (
        "Read system telemetry from NexusBody: CPU percent, RAM usage, "
        "disk usage, and GPU temperature. All read-only."
    )
    safety_tier = SafetyTier.READ_ONLY
    version = "1.0.0"

    async def execute(self, context: ExecutionContext) -> dict:
        action = context.action

        dispatch = {
            "check_resources": self._check_resources,
            "cpu": self._cpu,
            "ram": self._ram,
            "disk": self._disk,
            "gpu_temp": self._gpu_temp,
        }

        handler = dispatch.get(action)
        if handler is None:
            return {"success": False, "error": f"Unknown action '{action}'"}

        return await handler(context)

    def get_capabilities(self) -> list[dict]:
        return [
            {"action": "check_resources", "description": "Full system snapshot: CPU, RAM, disk, GPU"},
            {"action": "cpu", "description": "CPU utilization percentage"},
            {"action": "ram", "description": "RAM usage (used/total/percent)"},
            {"action": "disk", "description": "Disk usage for the root filesystem"},
            {"action": "gpu_temp", "description": "GPU temperature in Celsius (requires nvidia-smi)"},
        ]

    # ------------------------------------------------------------------
    # Action handlers
    # ------------------------------------------------------------------

    async def _check_resources(self, context: ExecutionContext) -> dict:
        cpu = psutil.cpu_percent(interval=0.5)
        ram = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        gpu_temp = self._read_gpu_temp()

        return {
            "success": True,
            "cpu_percent": cpu,
            "ram_used_gb": round(ram.used / (1024 ** 3), 2),
            "ram_total_gb": round(ram.total / (1024 ** 3), 2),
            "ram_percent": ram.percent,
            "disk_used_gb": round(disk.used / (1024 ** 3), 2),
            "disk_total_gb": round(disk.total / (1024 ** 3), 2),
            "disk_percent": disk.percent,
            "gpu_temp_c": gpu_temp,
        }

    async def _cpu(self, context: ExecutionContext) -> dict:
        return {"success": True, "cpu_percent": psutil.cpu_percent(interval=0.5)}

    async def _ram(self, context: ExecutionContext) -> dict:
        ram = psutil.virtual_memory()
        return {
            "success": True,
            "used_gb": round(ram.used / (1024 ** 3), 2),
            "total_gb": round(ram.total / (1024 ** 3), 2),
            "percent": ram.percent,
        }

    async def _disk(self, context: ExecutionContext) -> dict:
        disk = psutil.disk_usage("/")
        return {
            "success": True,
            "used_gb": round(disk.used / (1024 ** 3), 2),
            "total_gb": round(disk.total / (1024 ** 3), 2),
            "percent": disk.percent,
        }

    async def _gpu_temp(self, context: ExecutionContext) -> dict:
        temp = self._read_gpu_temp()
        if temp is None:
            return {"success": False, "error": "nvidia-smi not available or no GPU detected"}
        return {"success": True, "gpu_temp_c": temp}

    @staticmethod
    def _read_gpu_temp() -> Any:
        """Read GPU temperature via nvidia-smi. Returns float or None."""
        if not shutil.which("nvidia-smi"):
            return None
        try:
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=temperature.gpu", "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                return float(result.stdout.strip())
        except Exception as exc:
            logger.debug("nvidia-smi failed: %s", exc)
        return None
