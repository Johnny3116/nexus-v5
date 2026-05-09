"""sonnet_builder.py — Claude claude-sonnet-4-6 builder for V5.

Drop-in replacement for builder.py. Same build_from_plan() signature.
Uses ANTHROPIC_API_KEY from environment. Falls back to Ollama builder
if the key is missing or the API call fails.

Milestone 5: Sonnet produces higher-quality, more architecturally sound
code than Ollama 7B. Selection happens at runtime in server.py.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import httpx

from .build_prompt import SYSTEM_PROMPT, build_implementation_prompt
from .builder import _validate_output_paths, _write_files, WORKSPACE_ROOT

logger = logging.getLogger(__name__)

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_BUILD_MODEL", "claude-sonnet-4-6")
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"

_BUILDER_NAME = f"sonnet:{ANTHROPIC_MODEL}"


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
    if text.endswith("```"):
        text = text.rsplit("```", 1)[0]
    return text.strip()


async def build_from_plan(plan: dict, task_packet: dict, error_context: str = "") -> dict:
    """Generate code using Claude Sonnet. Falls back to Ollama on any failure.

    Returns the same build_result dict as builder.build_from_plan().
    """
    if not ANTHROPIC_API_KEY:
        logger.warning("ANTHROPIC_API_KEY not set — falling back to Ollama builder")
        from .builder import build_from_plan as _ollama_build
        return await _ollama_build(plan, task_packet)

    user_message = build_implementation_prompt(plan, task_packet, error_context=error_context)

    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }

    payload = {
        "model": ANTHROPIC_MODEL,
        "max_tokens": 8192,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": user_message}],
    }

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=10.0)) as client:
            resp = await client.post(ANTHROPIC_URL, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        logger.error("Sonnet API call failed (%s) — falling back to Ollama builder", exc)
        from .builder import build_from_plan as _ollama_build
        return await _ollama_build(plan, task_packet)

    raw_text = ""
    for block in data.get("content", []):
        if block.get("type") == "text":
            raw_text += block["text"]

    raw_text = _strip_fences(raw_text.strip())
    if not raw_text:
        logger.error("Sonnet returned empty response — falling back to Ollama builder")
        from .builder import build_from_plan as _ollama_build
        return await _ollama_build(plan, task_packet)

    # Sonnet may wrap JSON in markdown; strip and parse
    try:
        build_dict = json.loads(raw_text)
    except json.JSONDecodeError:
        # Try to extract JSON object from response
        import re
        m = re.search(r'\{[\s\S]+\}', raw_text)
        if not m:
            logger.error("Could not parse Sonnet JSON response — falling back")
            from .builder import build_from_plan as _ollama_build
            return await _ollama_build(plan, task_packet)
        build_dict = json.loads(m.group(0))

    files = build_dict.get("files", [])
    notes = build_dict.get("notes", "")

    if not files:
        return {"success": False, "written_files": [], "notes": notes,
                "error": "Sonnet returned no files"}

    errors = _validate_output_paths(files)
    if errors:
        logger.error("Sonnet build aborted — path validation: %s", errors)
        return {"success": False, "written_files": [], "notes": notes,
                "error": f"Path validation failed: {'; '.join(errors)}"}

    written = _write_files(files)
    logger.info("Sonnet build complete: %d file(s) written", len(written))

    return {"success": True, "written_files": written, "notes": notes, "error": None}
