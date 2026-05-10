"""history_store.py — conversation history I/O, extracted from llm_scr.py.

Previously, load_history() and save_history() lived in llm_scr.py alongside
gateway-era code that opened character_config.yaml at module load time. Any
module importing these helpers would trigger that side effect even if it only
needed history management.

This module is the canonical home for history I/O. llm_scr.py now imports
from here instead of defining them itself.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

_DEFAULT_HISTORY_FILE = str(
    Path(__file__).resolve().parents[1] / "chat" / "history" / "avatar.json"
)
HISTORY_FILE: str = os.getenv("AVATAR_HISTORY_FILE", _DEFAULT_HISTORY_FILE)


def load_history(soul_text: str | None = None) -> list[dict]:
    """Load conversation history. Replaces the system prompt if soul_text provided."""
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                history = json.load(f)
            if soul_text and history and history[0].get("role") == "system":
                history[0] = {"role": "system", "content": soul_text}
            return history
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to load history (%s) — starting fresh", exc)

    system = [{"role": "system", "content": soul_text}] if soul_text else []
    return system


def save_history(history: list[dict]) -> None:
    """Persist conversation history to disk."""
    os.makedirs(os.path.dirname(HISTORY_FILE), exist_ok=True)
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2)
