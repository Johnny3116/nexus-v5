"""Streaming LLM helper with Ollama tool-calling support.

Bypasses the nexus-gateway for the voice hot-path so the avatar can start
TTS on sentence 1 while sentence 2 is still generating. Identity comes from
the canonical Soul Container (safety.identity.soul_container).

V5.3b: Ollama tool-calling integration. Defines connector tools that the
model can invoke mid-conversation. When the model returns a tool_call,
we execute it via the connector registry and feed the result back.
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

_NEXUS_ROOT = Path(__file__).resolve().parents[5]
if str(_NEXUS_ROOT) not in sys.path:
    sys.path.insert(0, str(_NEXUS_ROOT))

try:
    from safety.identity.soul_container import get_identity_block, enforce as soul_enforce
    _CANONICAL_IDENTITY_AVAILABLE = True
except Exception:
    _CANONICAL_IDENTITY_AVAILABLE = False
    def get_identity_block(_task_type: str = "voice") -> str:
        return SYSTEM_PROMPT_TEXT
    def soul_enforce(text: str) -> str:
        return text

# Full prompt assembly (soul + memories + RAG). Falls back to get_identity_block.
try:
    from serving.brain_pool.prompt_builder import assemble_system_prompt as _assemble_prompt
    _PROMPT_ASSEMBLER_AVAILABLE = True
except Exception:
    _PROMPT_ASSEMBLER_AVAILABLE = False
    async def _assemble_prompt(  # type: ignore
        message: str, *, task_type: str = "avatar", identity_id: str = "john"
    ) -> str:
        return get_identity_block(task_type)

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5-coder:7b")
OLLAMA_NUM_PREDICT = int(os.getenv("OLLAMA_NUM_PREDICT_VOICE", "200"))
GATEWAY_URL = os.getenv("NEXUS_GATEWAY_URL", "http://127.0.0.1:8000")

# Max tool-call rounds per user message (prevent infinite loops)
MAX_TOOL_ROUNDS = 3

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=\S)")


def _flush_sentences(buffer: str) -> tuple[list[str], str]:
    parts = _SENTENCE_SPLIT.split(buffer)
    if len(parts) <= 1:
        return [], buffer
    return [p.strip() for p in parts[:-1] if p.strip()], parts[-1]


# ---------------------------------------------------------------------------
# Tool definitions for Ollama
# ---------------------------------------------------------------------------

CONNECTOR_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_memories",
            "description": "Search Nexus's Supabase memory for information about John, past conversations, preferences, or facts. Use this when asked about something you might have stored, or when you want to recall details.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search term or phrase to look for in memories"
                    },
                    "table": {
                        "type": "string",
                        "description": "Which table to search: memories, agent_memories, game_notes, games, game_currencies, anime_series",
                        "enum": ["memories", "agent_memories", "game_notes", "games", "game_currencies", "anime_series"],
                        "default": "memories"
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "save_memory",
            "description": "Save a new fact or memory about John to Supabase. Use this when John tells you something worth remembering for future conversations, like preferences, facts about himself, or project updates.",
            "parameters": {
                "type": "object",
                "properties": {
                    "key": {
                        "type": "string",
                        "description": "A short slug identifier for this memory, like 'john-favorite-game' or 'project-nexus-status'"
                    },
                    "content": {
                        "type": "string",
                        "description": "The full fact or memory to store"
                    },
                    "category": {
                        "type": "string",
                        "description": "Category: user_preference, game_preference, personal_fact, project_state, learned",
                        "enum": ["user_preference", "game_preference", "personal_fact", "project_state", "learned"],
                        "default": "learned"
                    }
                },
                "required": ["key", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_table",
            "description": "Read rows from a Supabase table with optional filters. Use for browsing game data, anime lists, or checking specific records.",
            "parameters": {
                "type": "object",
                "properties": {
                    "table": {
                        "type": "string",
                        "description": "Table to read from",
                        "enum": ["memories", "agent_memories", "game_notes", "games", "game_currencies", "anime_series", "anime_notes", "anime_characters"]
                    },
                    "filters": {
                        "type": "object",
                        "description": "Column-value pairs to filter by, e.g. {\"category\": \"user\"}"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max rows to return (default 10)",
                        "default": 10
                    }
                },
                "required": ["table"]
            }
        }
    }
]


def _execute_tool_call(name: str, args: dict) -> str:
    """Execute a tool call synchronously via the connector API. Returns result as string."""
    try:
        import requests
        if name == "search_memories":
            resp = requests.post(
                f"{GATEWAY_URL}/v1/connectors/supabase/run",
                json={"action": "search", "params": {
                    "table": args.get("table", "memories"),
                    "query": args.get("query", ""),
                    "limit": 5,
                }},
                timeout=10,
            )
            data = resp.json()
            if data.get("success") and data.get("data"):
                rows = data["data"]
                results = []
                for r in rows[:5]:
                    key = r.get("key", r.get("id", ""))
                    content = r.get("content", r.get("name", ""))
                    cat = r.get("category", "")
                    results.append(f"[{cat}] {key}: {content[:200]}")
                return f"Found {len(rows)} results:\n" + "\n".join(results)
            elif data.get("success"):
                return "No results found."
            else:
                return f"Search failed: {data.get('error', 'unknown')}"

        elif name == "save_memory":
            resp = requests.post(
                f"{GATEWAY_URL}/v1/connectors/supabase/run",
                json={"action": "write", "params": {
                    "table": "agent_memories",
                    "rows": [{
                        "key": args.get("key", "unknown"),
                        "content": args.get("content", ""),
                        "category": args.get("category", "learned"),
                    }],
                    "upsert": True,
                }},
                timeout=10,
            )
            data = resp.json()
            if data.get("success"):
                return f"Memory saved: {args.get('key')}"
            else:
                return f"Save failed: {data.get('error', 'unknown')}"

        elif name == "read_table":
            resp = requests.post(
                f"{GATEWAY_URL}/v1/connectors/supabase/run",
                json={"action": "read", "params": {
                    "table": args.get("table", "memories"),
                    "filters": args.get("filters", {}),
                    "limit": min(args.get("limit", 10), 20),
                }},
                timeout=10,
            )
            data = resp.json()
            if data.get("success") and data.get("data"):
                rows = data["data"]
                results = []
                for r in rows[:10]:
                    # Summarize each row
                    summary = {k: str(v)[:100] for k, v in r.items()
                               if k not in ("metadata", "updated_at") and v}
                    results.append(json.dumps(summary))
                return f"{len(rows)} rows:\n" + "\n".join(results)
            elif data.get("success"):
                return "No rows found."
            else:
                return f"Read failed: {data.get('error', 'unknown')}"

        else:
            return f"Unknown tool: {name}"

    except Exception as exc:
        logger.warning("Tool call %s failed: %s", name, exc)
        return f"Tool error: {exc}"


# ---------------------------------------------------------------------------
# Main streaming function with tool-call loop
# ---------------------------------------------------------------------------

async def stream_sentences(user_input: str) -> AsyncIterator[str]:
    """Yield Nexus reply sentence-by-sentence as Ollama streams tokens.

    V5.3b: If the model returns tool_calls instead of text, we execute
    them and re-call the model with the results until it produces text.
    """
    history = load_history()
    history.append({"role": "user", "content": user_input})

    # Unified prompt assembly: soul + memories (no RAG for avatar — latency).
    # Falls back to get_identity_block if prompt assembler unavailable.
    identity_block = await _assemble_prompt(user_input, task_type="avatar")

    # Build messages with system prompt
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

    # Tool-call loop: model may call tools before generating final text
    tool_round = 0
    full_response = ""

    while tool_round <= MAX_TOOL_ROUNDS:
        payload = {
            "model": OLLAMA_MODEL,
            "messages": messages,
            "stream": False if tool_round < MAX_TOOL_ROUNDS else False,
            "tools": CONNECTOR_TOOLS,
            "options": {"temperature": 0.4, "num_predict": OLLAMA_NUM_PREDICT},
            "keep_alive": -1,
        }

        # Non-streaming call to check for tool calls
        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=5.0)) as client:
            resp = await client.post(f"{OLLAMA_URL}/api/chat", json=payload)
            resp.raise_for_status()
            result = resp.json()

        msg = result.get("message", {})
        tool_calls = msg.get("tool_calls", [])

        if tool_calls:
            tool_round += 1
            logger.info("Tool calls in round %d: %s", tool_round,
                        [tc.get("function", {}).get("name") for tc in tool_calls])

            # Add assistant message with tool calls to history
            messages.append(msg)

            # Execute each tool call and add results
            for tc in tool_calls:
                func = tc.get("function", {})
                name = func.get("name", "")
                args = func.get("arguments", {})
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except Exception:
                        args = {}

                tool_result = _execute_tool_call(name, args)
                logger.info("Tool %s result: %s", name, tool_result[:100])

                messages.append({
                    "role": "tool",
                    "content": tool_result,
                })

            # Loop back to let the model respond with the tool results
            continue

        # No tool calls — we have a text response
        full_response = msg.get("content", "")
        break

    if not full_response:
        return

    # Stream the response sentence by sentence (for TTS)
    sentences = _SENTENCE_SPLIT.split(full_response)
    for s in sentences:
        s = s.strip()
        if s:
            cleaned = soul_enforce(s)
            if cleaned.strip():
                yield cleaned

    # Save to history
    history.append({"role": "assistant", "content": full_response.strip()})
    try:
        save_history(history)
    except Exception:
        logger.exception("Failed to persist conversation history")
