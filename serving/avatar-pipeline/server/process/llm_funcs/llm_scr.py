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
import threading
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

load_dotenv()

_ROOT = Path(__file__).resolve().parents[3]

GATEWAY_URL = os.getenv("NEXUS_GATEWAY_URL", "http://127.0.0.1:8000")
# Only verify TLS when actually talking HTTPS. Loopback HTTP doesn't need it,
# and an HTTPS gateway must not silently skip verification.
_VERIFY_TLS = GATEWAY_URL.lower().startswith("https")


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


def load_history() -> list[dict]:
    """Load conversation history with soul hot-reload.

    M18: delegates file I/O to history.history_store.
    Soul is re-read every call so identity edits hot-reload without a restart.
    """
    try:
        soul = _load_soul()
    except FileNotFoundError:
        logger.exception("soul.md missing on hot-reload; using cached copy")
        soul = SYSTEM_PROMPT_TEXT
    from history.history_store import load_history as _hs_load
    return _hs_load(soul_text=soul)


def save_history(history: list[dict]) -> None:
    """Persist conversation history to disk.

    M18: delegates file I/O to history.history_store.
    """
    from history.history_store import save_history as _hs_save
    _hs_save(history)



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
    """Main conversation entry point.

    Loads Supabase memories, injects them into the system prompt,
    calls the LLM, saves history, then fires a background thread to
    extract any new memorable facts from this exchange.
    """
    memories_block = _load_memories_block()
    messages = load_history()

    # Inject memories into system prompt if we have any
    if memories_block and messages and messages[0].get("role") == "system":
        messages[0] = {
            "role": "system",
            "content": (
                messages[0]["content"]
                + "\n\n"
                + memories_block
            ),
        }

    messages.append({"role": "user", "content": user_input})
    result = get_nexus_response(messages)
    response_text = result.output_text
    messages.append({"role": "assistant", "content": response_text})
    save_history(messages)

    # Background: extract memorable facts (non-blocking)
    t = threading.Thread(
        target=_extract_memories_bg,
        args=(user_input, response_text),
        daemon=True,
    )
    t.start()

    return response_text


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




# ---------------------------------------------------------------------------
# Supabase memory integration
# ---------------------------------------------------------------------------

def _load_memories_block() -> str:
    """Fetch Supabase memories and format as a context block.

    Reads agent_memories (conversation-derived) + memories[category=user]
    (persistent user facts). Returns empty string if Supabase is disabled
    or unavailable -- never raises.
    """
    if os.getenv("SUPABASE_ENABLED", "true").lower() != "true":
        return ""
    try:
        from db.client import agent_memory_read, memory_read
        rows: list[dict] = agent_memory_read(limit=40)
        user_mem = memory_read(category="user", limit=10)
        rows = rows + user_mem
        if not rows:
            return ""
        lines = ["[What Nexus remembers about John]"]
        for row in rows:
            key = row.get("key", "")
            content = row.get("content", "").strip()
            cat = row.get("category", "")
            lines.append(f"- [{cat}] {key}: {content}")
        return "\n".join(lines)
    except Exception as exc:
        logger.warning("Supabase memory load failed (non-fatal): %s", exc)
        return ""


def save_agent_memory(
    key: str,
    content: str,
    *,
    category: str = "learned",
    metadata: dict | None = None,
) -> None:
    """Explicitly save a fact to agent_memories. Safe to call from anywhere.

    Args:
        key:      Unique identifier (e.g. "john-prefers-dark-mode").
        content:  The fact to remember.
        category: e.g. "user_preference", "game_preference", "learned".
        metadata: Optional extra data.
    """
    try:
        from db.client import agent_memory_upsert
        agent_memory_upsert(key, content, category=category, metadata=metadata or {})
        logger.info("agent_memory saved: [%s] %s", category, key)
    except Exception as exc:
        logger.warning("agent_memory save failed (non-fatal): %s", exc)


def _extract_memories_bg(user_input: str, assistant_response: str) -> None:
    """Background thread: extract memorable facts from this exchange.

    Sends a lightweight prompt to the gateway asking for JSON-formatted
    facts. Saves any valid results to agent_memories. Fails silently.
    """
    if os.getenv("SUPABASE_ENABLED", "true").lower() != "true":
        return
    if os.getenv("MEMORY_EXTRACTION_ENABLED", "true").lower() != "true":
        return

    EXTRACT_PROMPT = (
        "You are a memory extractor. Analyze this conversation exchange "
        "and extract 0-3 memorable facts about the user (John) that would "
        "be useful to remember across future conversations.\n\n"
        "ONLY extract facts that are clearly stated or strongly implied. "
        "Do NOT guess or infer.\n\n"
        "Return ONLY valid JSON -- an array of objects:\n"
        '[{"key": "short-slug", "content": "full fact", '
        '"category": "user_preference|game_preference|personal_fact|project_state"}]\n'
        "Return [] if nothing memorable.\n\n"
        f"User: {user_input}\n"
        f"Nexus: {assistant_response}"
    )

    try:
        resp = httpx.post(
            f"{GATEWAY_URL}/v1/chat",
            json={"message": EXTRACT_PROMPT, "identity_id": "system", "task_type": "extract"},
            timeout=30.0,
            verify=_VERIFY_TLS,
        )
        resp.raise_for_status()
        raw = resp.json().get("response", "[]").strip()
        start = raw.find("[")
        end = raw.rfind("]") + 1
        if start == -1 or end == 0:
            return
        import json as _json
        facts = _json.loads(raw[start:end])
        if not isinstance(facts, list):
            return
        for fact in facts:
            if not isinstance(fact, dict):
                continue
            key = str(fact.get("key", "")).strip()
            content = str(fact.get("content", "")).strip()
            category = str(fact.get("category", "learned")).strip()
            if key and content and len(content) < 2000:
                save_agent_memory(key, content, category=category)
                logger.info("auto-extracted memory: [%s] %s", category, key)
    except Exception as exc:
        logger.debug("memory extraction failed (non-fatal): %s", exc)

if __name__ == "__main__":
    print(llm_response("hi Nexus"))
