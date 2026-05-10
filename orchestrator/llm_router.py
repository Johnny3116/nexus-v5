"""orchestrator/llm_router.py — LLM-backed intent router.

Phase 2 of the Coordinator Agent (M15): replaces keyword matching with an
Ollama call that reasons about the user's intent using the coordinator agent
system prompt (agents/coordinator/system.md + rules.md + routing.md).

Fallback behaviour:
  Any failure (Ollama down, timeout, bad JSON, invalid route) → keyword router.
  The pipeline never hard-fails on a routing error.

Environment:
  COORDINATOR_MODEL — Ollama model for routing (default: OLLAMA_MODEL)
  OLLAMA_URL        — Ollama endpoint (default: http://127.0.0.1:11434)
"""

from __future__ import annotations

import json
import logging
import os

import httpx

from .router import RouteDecision, classify_message as _keyword_classify

logger = logging.getLogger(__name__)

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
# Coordinator can use a faster model; falls back to the main model.
COORDINATOR_MODEL = os.getenv("COORDINATOR_MODEL", os.getenv("OLLAMA_MODEL", "qwen2.5-coder:7b"))


def _coordinator_model() -> str:
    """Return coordinator model from agents/coordinator/model.json, falling back to COORDINATOR_MODEL env."""
    try:
        from .agent_loader import load_model_config
        cfg = load_model_config("coordinator")
        return cfg.get("model", COORDINATOR_MODEL)
    except Exception:
        return COORDINATOR_MODEL

_VALID_ROUTES = {"chat", "avatar", "skill", "code_plan", "code_build", "memory", "admin", "unknown"}
_TIMEOUT = 10.0  # seconds — routing must be fast

# Compact fallback prompt used when agent files can't be loaded
_FALLBACK_SYSTEM = (
    "You are a routing classifier. Given a user message, output JSON with:\n"
    "  route: one of [chat, code_plan, code_build, memory, admin, avatar, skill, unknown]\n"
    "  confidence: float 0.0–1.0\n"
    "  reason: brief string\n"
    "  requires_task_packet: bool (true only for code_plan)\n\n"
    "Route definitions:\n"
    "  code_plan — user wants to build, implement, refactor, fix, create, or plan code\n"
    "  chat      — conversation, questions, general discussion (fallback)\n"
    "  admin     — system/health checks, restart requests, service status\n"
    "  memory    — remember/recall/forget/store information\n"
    "  avatar    — animation, pose, expression, lipsync control\n"
    "  skill     — explicit skill invocation\n"
    "  code_build — execute an existing approved plan\n"
    "  unknown   — genuinely ambiguous (rare)\n"
)


def _build_coordinator_prompt() -> str:
    """Build system prompt from coordinator agent files via agent_loader.
    agent_loader.load() is @lru_cache — disk read happens once per process.
    """
    try:
        from .agent_loader import load
        system = load("coordinator", "system")
        rules = load("coordinator", "rules")
        routing = load("coordinator", "routing")
        # Append the JSON output contract so the model knows what to return
        contract = (
            "\n\n## Output Contract\n"
            "Return ONLY valid JSON with these exact keys:\n"
            "  route           — one of the route types defined above\n"
            "  confidence      — float 0.0–1.0\n"
            "  reason          — max 20 words describing why\n"
            "  requires_task_packet — bool (true only for code_plan)\n"
            "No markdown, no explanation outside the JSON object."
        )
        return f"{system}\n\n{rules}\n\n{routing}{contract}"
    except Exception as e:
        logger.warning("Could not load coordinator agent files (%s) — using compact prompt", e)
        return _FALLBACK_SYSTEM


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
    if text.endswith("```"):
        text = text.rsplit("```", 1)[0]
    return text.strip()


async def _llm_classify(message: str) -> RouteDecision:
    """Call Ollama to classify message. Raises on any failure."""
    system_prompt = _build_coordinator_prompt()

    user_msg = (
        f"Classify this message and return JSON.\n\n"
        f"Message: {message}"
    )

    payload = {
        "model": _coordinator_model(),
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_msg},
        ],
        "stream": False,
        "options": {
            "temperature": 0.0,   # deterministic routing
            "num_predict": 150,   # route + confidence + reason + bool fits in 150 tokens
        },
        "keep_alive": -1,
        "format": "json",
    }

    async with httpx.AsyncClient(timeout=httpx.Timeout(_TIMEOUT, connect=3.0)) as client:
        resp = await client.post(f"{OLLAMA_URL}/api/chat", json=payload)
        resp.raise_for_status()
        data = resp.json()

    raw = data.get("message", {}).get("content", "").strip()
    if not raw:
        raise ValueError("LLM router returned empty response")

    raw = _strip_fences(raw)
    parsed = json.loads(raw)

    route = str(parsed.get("route", "chat")).lower()
    if route not in _VALID_ROUTES:
        logger.warning("LLM router returned invalid route %r — keyword fallback", route)
        return _keyword_classify(message)

    confidence = min(1.0, max(0.0, float(parsed.get("confidence", 0.8))))
    reason = str(parsed.get("reason", "LLM classified"))[:120]
    requires_tp = bool(parsed.get("requires_task_packet", route == "code_plan"))

    logger.info("LLM router: %s (%.2f) — %s", route, confidence, reason)
    return RouteDecision(
        route=route,
        confidence=confidence,
        reason=f"[LLM] {reason}",
        requires_task_packet=requires_tp,
    )


async def classify_message_llm(message: str) -> RouteDecision:
    """Classify a message using LLM reasoning.

    Falls back to keyword router on:
      - Ollama unavailable or timeout
      - Bad JSON or missing route key
      - Route value not in _VALID_ROUTES
      - Any other exception

    The keyword fallback means routing never silently fails.
    Caller can detect LLM vs keyword result by checking reason.startswith("[LLM]").
    """
    try:
        return await _llm_classify(message)
    except Exception as exc:
        logger.warning("LLM router failed (%s) — keyword fallback", exc)
        result = _keyword_classify(message)
        # Tag result so callers know which path was taken
        result = RouteDecision(
            route=result.route,
            confidence=result.confidence,
            reason=f"[KW] {result.reason}",
            requires_task_packet=result.requires_task_packet,
        )
        return result
