"""Skill manager — plugin loader and registry.

Discovers skills by importing every .py in `serving/skills/` that defines
a SkillBase subclass. Hot-reload via `reload()`.
"""

from __future__ import annotations

import importlib
import inspect
import logging
import pkgutil
import sys
from pathlib import Path
from typing import Optional

from serving.skills.skill_base import SkillBase

logger = logging.getLogger("nexus.skills.manager")

_SKILLS_PKG = "serving.skills"
_SKILLS_DIR = Path(__file__).resolve().parent


class SkillManager:
    def __init__(self) -> None:
        self._registry: dict[str, SkillBase] = {}

    def load(self) -> int:
        self._registry.clear()
        loaded = 0
        for mod_info in pkgutil.iter_modules([str(_SKILLS_DIR)]):
            if mod_info.name.startswith("_") or mod_info.name in (
                "skill_base", "skill_manager", "execution_context", "task_parser", "agentic_loop",
            ):
                continue
            module_name = f"{_SKILLS_PKG}.{mod_info.name}"
            try:
                module = importlib.import_module(module_name)
                skill = self._find_skill(module)
                if skill is None:
                    continue
                if not skill.name:
                    logger.warning("skill in %s has no name", module_name)
                    continue
                self._registry[skill.name] = skill
                logger.debug("loaded skill: %s (tier=%s)", skill.name, skill.safety_tier.value)
                loaded += 1
            except Exception as exc:
                logger.error("failed to import %s: %s", module_name, exc, exc_info=True)
        logger.info("SkillManager: %d skill(s) loaded: %s", loaded, list(self._registry.keys()))
        return loaded

    def reload(self) -> int:
        # Preserve skill_base / skill_manager / support modules — if we evict
        # skill_base, freshly-imported skills subclass a *new* SkillBase and
        # issubclass(obj, SkillBase) returns False against our cached ref.
        _PRESERVE = {
            f"{_SKILLS_PKG}",
            f"{_SKILLS_PKG}.skill_base",
            f"{_SKILLS_PKG}.skill_manager",
            f"{_SKILLS_PKG}.execution_context",
            f"{_SKILLS_PKG}.task_parser",
            f"{_SKILLS_PKG}.agentic_loop",
        }
        to_remove = [k for k in sys.modules if k.startswith(_SKILLS_PKG) and k not in _PRESERVE]
        for key in to_remove:
            del sys.modules[key]
        return self.load()

    def get(self, name: str) -> Optional[SkillBase]:
        return self._registry.get(name)

    def require(self, name: str) -> SkillBase:
        skill = self._registry.get(name)
        if skill is None:
            raise KeyError(f"skill '{name}' not found. available: {list(self._registry.keys())}")
        return skill

    def all(self) -> dict[str, SkillBase]:
        return dict(self._registry)

    def count(self) -> int:
        return len(self._registry)

    def list_capabilities(self) -> list[dict]:
        caps = []
        for skill in self._registry.values():
            for cap in skill.get_capabilities():
                caps.append({"skill": skill.name, "safety_tier": skill.safety_tier.value, **cap})
        return caps

    @staticmethod
    def _find_skill(module) -> Optional[SkillBase]:
        for _, obj in inspect.getmembers(module, inspect.isclass):
            if issubclass(obj, SkillBase) and obj is not SkillBase and not inspect.isabstract(obj):
                try:
                    return obj()
                except Exception as exc:
                    logger.warning("could not instantiate %s: %s", obj.__name__, exc)
        return None


_manager: Optional[SkillManager] = None


def get_skill_manager() -> SkillManager:
    global _manager
    if _manager is None:
        _manager = SkillManager()
        _manager.load()
    return _manager
