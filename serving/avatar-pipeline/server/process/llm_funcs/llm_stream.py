"""Streaming LLM helper — direct Ollama, sentence-by-sentence yield.

Bypasses the nexus-gateway for the voice hot-path so the avatar can start
TTS on sentence 1 while sentence 2 is still generating. Identity comes from
the canonical Soul Container (safety.identity.soul_container) so the
streaming path stays consistent with /v1/chat.

If Ollama is unreachable, callers should fall back to `llm_scr.llm_response`
(which goes through the gateway and can hit Codex/Claude).
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import AsyncIterator

import httpx

from .llm_scr import SYSTEM_PROMPT_TEXT, load_history, save_history

logger = logging.getLogger(__name__)

# Add Nexus repo root so we can import the canonical safety package.
_NEXUS_ROOT = Path(__file__).resolve().parents[5]
if str(_NEXUS_ROOT) not in sys.path:
    sys.path.insert(0, str(_NEXUS_ROOT))

# Canonical soul + post-LLM filter. Falls back to llm_scr soul if unavailable.
try:
    from safety.identity.soul_container import get_identity_block, enforce as soul_enforce  # type: ignore
    _CANONICAL_IDENTITY_AVAILABLE = True
except Exception:
    _CANONICAL_IDENTITY_AVAILABLE = False
    def get_identity_block(_task_type: str = "voice") -> str:  # type: ignore
        return SYSTEM_PROMPT_TEXT
    def soul_enforce(text: str) -> str:  # type: ignore
        return text

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5-coder:7b")
# Hard cap so TTS doesn't get 30s monologues.
OLLAMA_NUM_PREDICT = int(os.getenv("OLLAMA_NUM_PREDICT_VOICE", "120"))

# Split after a terminator + whitespace OR at the end of the buffer.
# Keeps the terminator attached to the preceding sentence.
# NOTE: Tried tightening with (?=[A-Z0-9"'(\[]) to skip abbreviations like
# "Dr. Smith" / decimals like "3.14", but it broke Nexus's casual lowercase
# speech ("yeah. so anyway..." → never split). Reverted. TODO: smarter
# abbreviation-aware split that preserves casual style.
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=\S)")


def _flush_sentences(buffer: str) -> tuple[list[str], str]:
    """Pop complete sentences off the front of `buffer`.

    Returns (sentences, remaining_buffer). A sentence is "complete" when it
    ends in `.!?` and is followed by whitespace + more text.
    """
    parts = _SENTENCE_SPLIT.split(buffer)
    if len(parts) <= 1:
        return [], buffer
    # Last part is still incomplete; hold it for the next token.
    return [p.strip() for p in parts[:-1] if p.strip()], parts[-1]


async def stream_sentences(user_input: str) -> AsyncIterator[str]:
    """Yield Nexus reply sentence-by-sentence as Ollama streams tokens.

    Also writes the completed reply to the same history file that
    `llm_scr.llm_response` uses so the non-streaming path stays in sync.
    Raises on Ollama errors — caller should catch and fall back.
    """
    history = load_history()
    history.append({"role": "user", "content": user_input})

    # Override the cached system prompt with the live canonical identity
    # block (soul.md + doctrines + voice context) on every call so soul
    # edits hot-reload without restarting the avatar server.
    identity_block = get_identity_block("voice")

    # Normalize for Ollama (flatten any list-style content).
    messages = []
    saw_system = False
    for m in history:
        c = m.get("content", "")
        if isinstance(c, list):
            c = " ".join(p.get("text", "") for p in c if isinstance(p, dict))
        if m.get("role") == "system" and not saw_system:
            c = identity_block
            saw_system = True
        messages.append({"role": m["role"], "content": c})
    if not saw_system:
        messages.insert(0, {"role": "system", "content": identity_block})

    payload = {
        "model": OLLAMA_MODEL,
        "messages": messages,
        "stream": True,
        "options": {"temperature": 0.4, "num_predict": OLLAMA_NUM_PREDICT},
        "keep_alive": -1,
    }

    buffer = ""
    full = ""

    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=5.0)) as client:
        async with client.stream("POST", f"{OLLAMA_URL}/api/chat", json=payload) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line:
                    continue
                try:
                    chunk = json.loads(line)
                except Exception:
                    continue
                tok = chunk.get("message", {}).get("content", "")
                if tok:
                    buffer += tok
                    full += tok
                    sentences, buffer = _flush_sentences(buffer)
                    for s in sentences:
                        # Run soul filter per-sentence: strips assistant-isms
                        # ("Certainly!", "As an AI…") and tool-call leakage
                        # before TTS sees the text.
                        cleaned = soul_enforce(s)
                        if cleaned.strip():
                            yield cleaned
                if chunk.get("done"):
                    break

    # Flush whatever's left as the final sentence.
    tail = buffer.strip()
    if tail:
        cleaned = soul_enforce(tail)
        if cleaned.strip():
            yield cleaned

    # Persist conversation so llm_response()'s next call sees the context.
    history.append({"role": "assistant", "content": full.strip()})
    try:
        save_history(history)
    except Exception:
        logger.exception("Failed to persist conversation history after stream")
