"""Nexus V5 TaskPacket generator.

Takes a user message classified as code_plan and uses Ollama to
extract structured task information. Returns a TaskPacket dataclass.

No Codex, no Sonnet, no external agents — Ollama only (Phase 1).
"""

from __future__ import annotations

import json
import logging
import os
from typing import Optional

import httpx

from .schemas import TaskPacket, TaskPacketInput

logger = logging.getLogger(__name__)

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5-coder:7b")
TIMEOUT = 60.0

_SYSTEM_PROMPT = """You are Nexus's planning assistant. Your job is to extract structured task information from a user request.

Return ONLY a valid JSON object — no explanation, no markdown fences, no other text.

Required schema:
{
  "goal": "one sentence: what needs to happen",
  "request_type": "code_plan",
  "repo": "repo name or null if not specified",
  "constraints": ["list of hard limits or known constraints"],
  "likely_files": ["files probably involved, or empty list if unknown"],
  "acceptance_tests": ["binary-testable pass/fail criteria"],
  "do_not_touch": ["files or areas explicitly off-limits"],
  "required_output": "PLAN.md",
  "verification_steps": ["how to verify the task is done"]
}

Be specific. Infer reasonable constraints from context (e.g. 'no breaking changes to existing API'). If a field is unknown, use an empty list or null."""


async def generate_task_packet(
    user_message: str,
    repo_name: Optional[str] = None,
    context: Optional[str] = None,
) -> dict:
    """Call Ollama to generate a structured TaskPacket from a user message.

    Returns the packet as a dict. Raises on Ollama failure so the caller
    can handle the fallback (graceful degradation to normal chat).
    """
    user_content = user_message
    if repo_name:
        user_content = f"Repo: {repo_name}\n\nRequest: {user_message}"
    if context:
        user_content = f"Context: {context}\n\n{user_content}"

    payload = {
        "model": OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        "stream": False,
        "options": {"temperature": 0.2},  # Low temp for structured output
    }

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(TIMEOUT, connect=5.0)
    ) as client:
        resp = await client.post(f"{OLLAMA_URL}/api/chat", json=payload)
        resp.raise_for_status()
        data = resp.json()

    raw = data["message"]["content"].strip()

    # Strip markdown fences if model wraps output anyway
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw
        raw = raw.rsplit("```", 1)[0].strip()

    try:
        packet_dict = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.error("TaskPacket JSON parse failed: %s\nRaw: %s", e, raw[:300])
        raise ValueError(f"Ollama returned non-JSON: {raw[:100]}") from e

    # Validate required keys present; fill missing with safe defaults
    packet_dict.setdefault("goal", user_message[:100])
    packet_dict.setdefault("request_type", "code_plan")
    packet_dict.setdefault("repo", repo_name)
    packet_dict.setdefault("constraints", [])
    packet_dict.setdefault("likely_files", [])
    packet_dict.setdefault("acceptance_tests", [])
    packet_dict.setdefault("do_not_touch", [])
    packet_dict.setdefault("required_output", "PLAN.md")
    packet_dict.setdefault("verification_steps", [])

    logger.info(
        "TaskPacket generated: goal=%r files=%d tests=%d",
        packet_dict["goal"][:60],
        len(packet_dict["likely_files"]),
        len(packet_dict["acceptance_tests"]),
    )

    return packet_dict
