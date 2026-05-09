"""LLM adapter — routes through nexus-gateway at :8000/v1/chat.

Uses our own api_gateway which handles Codex SSH transport internally.
Injects character_files/soul.md as the system prompt so the pipeline
speaks as Nexus.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import logging
import sys

import httpx
import yaml
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

load_dotenv()

_ROOT = Path(__file__).resolve().parents[3]

GATEWAY_URL = os.getenv("NEXUS_GATEWAY_URL", "http://127.0.0.1:8000")
# Only verify TLS when actually talking HTTPS. Loopback HTTP doesn't need it,
# and an HTTPS gateway must not silently skip verification.
_VERIFY_TLS = GATEWAY_URL.lower().startswith("https")

with open(_ROOT / "character_config.yaml", "r", encoding="utf-8") as f:
    char_config = yaml.safe_load(f)

HISTORY_FILE = char_config["history_file"]


def _load_soul() -> str:
    """Load the canonical soul prompt from safety/identity/soul.md.

    There is exactly one soul file. If it's missing, that's a fatal config
    error — we raise rather than silently fall back to a stale copy.
    """
    canonical = _ROOT.parent.parent / "safety" / "identity" / "soul.md"
    if not canonical.exists():
        raise FileNotFoundError(
            f"Canonical soul.md not found at {canonical}. "
            "There is only one soul file — restore it before starting the avatar."
        )
    return canonical.read_text(encoding="utf-8")


SYSTEM_PROMPT_TEXT = _load_soul()
SYSTEM_PROMPT = [{"role": "system", "content": SYSTEM_PROMPT_TEXT}]


def load_history():
    # Re-read soul.md every call so identity edits hot-reload without an
    # avatar restart (matches the streaming path's get_identity_block flow).
    try:
        soul = _load_soul()
    except FileNotFoundError:
        logger.exception("soul.md missing on hot-reload; using cached copy")
        soul = SYSTEM_PROMPT_TEXT
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            history = json.load(f)
            if history and history[0].get("role") == "system":
                history[0] = {"role": "system", "content": soul}
            return history
    return [{"role": "system", "content": soul}]


def save_history(history):
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2)


def _normalize(messages):
    out = []
    for m in messages:
        content = m.get("content", "")
        if isinstance(content, list):
            text = " ".join(
                part.get("text", "") for part in content if isinstance(part, dict)
            )
            out.append({"role": m["role"], "content": text})
        else:
            out.append({"role": m["role"], "content": content})
    return out


def get_nexus_response(messages):
    """Call nexus-gateway /v1/chat which routes to Codex/Qwen/Claude."""
    normalized = _normalize(messages)

    # Build a single message from the conversation for the gateway.
    # System prompt is already in the conversation history.
    user_parts = []
    for m in normalized:
        if m["role"] == "user":
            user_parts.append(m["content"])
        elif m["role"] == "assistant":
            user_parts.append(f"[previous response] {m['content']}")

    message = user_parts[-1] if user_parts else ""

    try:
        resp = httpx.post(
            f"{GATEWAY_URL}/v1/chat",
            json={
                "message": message,
                "identity_id": "john",
                "task_type": "voice",
            },
            timeout=60.0,
            verify=_VERIFY_TLS,
        )
        resp.raise_for_status()
        data = resp.json()
        text = data.get("response", "")
    except Exception as exc:
        text = f"I'm having trouble connecting right now. ({exc})"

    class _Shim:
        def __init__(self, t: str) -> None:
            self.output_text = t

    return _Shim(text)


get_riko_response_no_tool = get_nexus_response


def llm_response(user_input: str) -> str:
    messages = load_history()
    messages.append({"role": "user", "content": user_input})
    result = get_nexus_response(messages)
    messages.append({"role": "assistant", "content": result.output_text})
    save_history(messages)
    return result.output_text


def llm_response_with_memory(user_input: str, context_memory: str) -> str:
    messages = load_history()
    if messages and messages[0]["role"] == "system":
        messages[0]["content"] = (
            f"{SYSTEM_PROMPT_TEXT}\n\n"
            "The following memories may or may not be relevant to this conversation. "
            "Ignore them if not:\n"
            f"{context_memory}"
        )
    messages.append({"role": "user", "content": user_input})
    result = get_nexus_response(messages)
    messages.append({"role": "assistant", "content": result.output_text})
    save_history(messages)
    return result.output_text


if __name__ == "__main__":
    print(llm_response("hi Nexus"))
