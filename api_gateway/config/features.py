"""Runtime feature flags.

Env-var driven so a flag flip is a restart, not a deploy. Defaults are the
safe position — opt-in to anything that could send real traffic, real
money, or real alerts.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


def _flag(name: str, default: bool = False) -> bool:
    return os.getenv(name, "1" if default else "0").lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Features:
    # Provider availability — flip off to force fallback chain
    claude_enabled: bool = _flag("FEATURE_CLAUDE_ENABLED", True)
    codex_enabled: bool = _flag("FEATURE_CODEX_ENABLED", True)
    qwen_enabled: bool = _flag("FEATURE_QWEN_ENABLED", True)

    # Endpoints
    chat_enabled: bool = _flag("FEATURE_CHAT_ENABLED", True)
    memory_enabled: bool = _flag("FEATURE_MEMORY_ENABLED", True)
    task_enabled: bool = _flag("FEATURE_TASK_ENABLED", False)      # phase 5
    skill_enabled: bool = _flag("FEATURE_SKILL_ENABLED", False)    # phase 5

    # Safety layers (phase 3/4 — wired but not enforced until flipped on)
    injection_scanner_enabled: bool = _flag("FEATURE_INJECTION_SCANNER", False)
    soul_container_enabled: bool = _flag("FEATURE_SOUL_CONTAINER", False)


features = Features()
