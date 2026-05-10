"""Codex provider — routes through local OpenClaw on NexusBody.

OpenClaw moved from NexusServer to NexusBody on 2026-04-21 (co-located
with the api_gateway). Transport is now a local subprocess exec against
`C:\\Users\\Nexus\\openclaw\\openclaw.mjs` — no SSH hop, no WS gateway.

Model: openai-codex/gpt-5.4 (configured in openclaw's agents.defaults.model)

The WS gateway URL in settings (`nexus_agent_url`) is retained for the
health probe only. Real chat calls go through the local CLI.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
from typing import Optional

import httpx

from api_gateway.config.settings import get_settings
from serving.brain_pool.providers import ProviderResult

logger = logging.getLogger("nexus.brain.codex")

_OPENCLAW_CWD = "C:\\Users\\Nexus\\openclaw"

# OpenClaw state dir on this machine. NexusBody and NexusServer each keep
# their own copy; this points local openclaw at the local state so each
# machine signs in independently. Override with NEXUS_OPENCLAW_STATE_DIR.
_OPENCLAW_STATE_DIR = os.environ.get(
    "NEXUS_OPENCLAW_STATE_DIR",
    "C:\\Users\\Nexus\\.nexus-agent",
)


def _openclaw_env() -> dict:
    """Subprocess env: parent env + OPENCLAW_STATE_DIR pointing at local state."""
    env = os.environ.copy()
    env["OPENCLAW_STATE_DIR"] = _OPENCLAW_STATE_DIR
    return env


async def chat(
    messages: list[dict],
    *,
    max_tokens: int = 4096,
    temperature: float = 0.85,
    client: Optional[httpx.AsyncClient] = None,
    **_: object,
) -> ProviderResult:
    settings = get_settings()

    # Flatten messages into a single prompt for the agent CLI.
    # System prompt is prepended; multi-turn history is joined.
    parts: list[str] = []
    for m in messages:
        role = m.get("role", "user")
        content = m.get("content", "")
        if role == "system":
            parts.insert(0, f"[system] {content}")
        elif role == "assistant":
            parts.append(f"[assistant] {content}")
        else:
            parts.append(content)
    prompt = "\n\n".join(parts)

    # Escape for shell (single-quote the message, escape inner quotes).
    escaped = prompt.replace("'", "'\\''")

    # Local subprocess — openclaw runs on NexusBody directly (post-2026-04-21).
    openclaw_cwd = _OPENCLAW_CWD
    timeout_s = 60

    cmd = [
        "node", "openclaw.mjs",
        "agent", "-m", prompt,
        "--agent", "main", "--json",
        "--timeout", str(timeout_s),
    ]

    # Windows + uvicorn's default SelectorEventLoop doesn't support
    # asyncio.create_subprocess_exec (raises NotImplementedError). Use a
    # blocking subprocess.run in a thread pool instead — same effect, but
    # works on every event loop. Safe because openclaw is a one-shot CLI
    # call with bounded timeout.
    def _run_blocking() -> tuple[int, bytes, bytes]:
        try:
            cp = subprocess.run(
                cmd,
                cwd=openclaw_cwd,
                env=_openclaw_env(),
                capture_output=True,
                timeout=timeout_s + 15,
                check=False,
            )
            return cp.returncode, cp.stdout, cp.stderr
        except subprocess.TimeoutExpired:
            return -1, b"", b"__TIMEOUT__"

    loop = asyncio.get_running_loop()
    rc, stdout_b, stderr_b = await loop.run_in_executor(None, _run_blocking)

    if stderr_b == b"__TIMEOUT__":
        logger.error("codex subprocess timed out after %ds", timeout_s + 15)
        raise RuntimeError(f"codex provider timed out after {timeout_s + 15}s")

    output = stdout_b.decode("utf-8", errors="replace").strip()
    err_output = stderr_b.decode("utf-8", errors="replace").strip()

    if rc != 0:
        logger.warning("codex subprocess exit=%d stderr=%s", rc, err_output[:500])

    # The CLI outputs the agent response as text (non-JSON by default).
    # With --json it wraps in a JSON object when the gateway path succeeds;
    # on fallback-to-embedded it outputs plain text.
    response_text = ""
    tokens_in = 0
    tokens_out = 0
    try:
        data = json.loads(output)
        # --json wraps in {payloads: [{text: ...}], meta: {agentMeta: {usage: ...}}}
        payloads = data.get("payloads", [])
        if payloads:
            response_text = "\n".join(
                p.get("text", "") for p in payloads if p.get("text")
            )
        if not response_text:
            response_text = (
                data.get("output", "")
                or data.get("text", "")
                or data.get("content", "")
                or output
            )
        # Extract usage from agentMeta
        meta = data.get("meta", {}).get("agentMeta", {})
        usage = meta.get("usage", {})
        tokens_in = int(usage.get("input", 0))
        tokens_out = int(usage.get("output", 0))
    except (json.JSONDecodeError, TypeError):
        response_text = output

    if not response_text and err_output:
        # Check for known errors.
        if "OAuth token refresh failed" in err_output:
            # Fire a best-effort reauth alert (Discord + Telegram with the
            # sign-in URL) and raise a typed exception so BrainPool's
            # fallback chain takes over while we wait for the user.
            from serving.brain_pool.codex_reauth import (
                CodexAuthExpired,
                maybe_fire_reauth_alert,
            )
            try:
                await maybe_fire_reauth_alert(reason=err_output[:200])
            except Exception as alert_exc:
                logger.error("reauth alert helper raised (suppressed): %s", alert_exc)
            raise CodexAuthExpired(
                "codex provider: OAuth token expired - reauth alert dispatched"
            )
        if "FailoverError" in err_output:
            raise RuntimeError(f"codex provider: all fallbacks failed — {err_output[:300]}")
        raise RuntimeError(f"codex provider returned empty response: {err_output[:300]}")

    # Successful Codex call - clear any stale reauth cooldown so the next
    # token expiry fires an alert immediately instead of waiting 24h.
    try:
        from serving.brain_pool.codex_reauth import reset_cooldown
        reset_cooldown()
    except Exception:
        pass

    return ProviderResult(
        content=response_text,
        model_used=settings.codex_model,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cost_usd=0.0,
    )


async def health(client: Optional[httpx.AsyncClient] = None) -> bool:
    """Health probe — verify the local openclaw.mjs is reachable.

    Spawns `node openclaw.mjs --help` and waits up to 5s for a clean exit.
    Argv-based subprocess, no shell interpolation, no user input. Does not
    exercise the agent runtime — that would cost a real turn.
    """
    # Same Windows-asyncio constraint as chat() — use blocking subprocess
    # in a thread pool instead of asyncio.create_subprocess_exec.
    def _probe_blocking() -> int:
        try:
            cp = subprocess.run(
                ["node", "openclaw.mjs", "--help"],
                cwd=_OPENCLAW_CWD,
                env=_openclaw_env(),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5.0,
                check=False,
            )
            return cp.returncode
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return -1
    try:
        loop = asyncio.get_running_loop()
        rc = await loop.run_in_executor(None, _probe_blocking)
        return rc == 0
    except Exception as exc:
        logger.debug("codex health probe failed: %s", exc)
        return False
