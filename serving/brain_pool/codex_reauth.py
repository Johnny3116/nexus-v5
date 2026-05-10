"""Codex OAuth re-auth helper.

When OpenClaw's OAuth token refresh fails, this helper:
  1. Checks a 24h cooldown to avoid alert spam if many calls fail in a row
  2. Spawns the openclaw auth login subcommand to start the device-flow
  3. Reads stdout for the sign-in URL the user must visit
  4. Fires a Discord WARN + Telegram CRITICAL alert with that URL
  5. Lets the subprocess continue running detached so the user's click
     completes the flow against the same process that allocated the URL

Subprocess invocations use asyncio.create_subprocess_exec with argv lists
(no shell). All arguments are static literals.

The provider (codex.py) calls maybe_fire_reauth_alert() before re-raising
so the user is notified, but the in-flight call still falls through to
qwen via BrainPool's normal fallback chain.

Cooldown state is stored at NEXUS_REAUTH_STATE / ~/.nexus_reauth.json.
Sync via Syncthing if you share .nexus-agent across machines, so the
cooldown is shared too (avoids both NexusBody and NexusServer firing
overlapping alerts during a token expiry window).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("nexus.brain.codex_reauth")

_COOLDOWN_HOURS = 24
_OPENCLAW_CWD = "C:\\Users\\Nexus\\openclaw"
_OPENCLAW_STATE_DIR = os.environ.get(
    "NEXUS_OPENCLAW_STATE_DIR",
    "C:\\Users\\Nexus\\.nexus-agent",
)
_DEVICE_FLOW_TIMEOUT_S = 30  # generous; we just need stdout, not user click


def _openclaw_env() -> dict:
    env = os.environ.copy()
    env["OPENCLAW_STATE_DIR"] = _OPENCLAW_STATE_DIR
    return env

# Match OpenClaw's device-flow URL output. Pattern is loose on purpose;
# any https://... URL emitted by the auth subcommand is treated as the
# sign-in link.
_URL_PATTERN = re.compile(r"https://\S+")


def _state_path() -> Path:
    override = os.environ.get("NEXUS_REAUTH_STATE")
    if override:
        return Path(override)
    return Path.home() / ".nexus_reauth.json"


def _read_state() -> dict:
    p = _state_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        logger.warning("reauth state at %s unreadable; treating as empty", p)
        return {}


def _write_state(state: dict) -> None:
    p = _state_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(state, indent=2), encoding="utf-8")
    except Exception as exc:
        logger.warning("could not persist reauth state: %s", exc)


def _on_cooldown(state: dict) -> bool:
    last = state.get("last_alert_iso")
    if not last:
        return False
    try:
        last_dt = datetime.fromisoformat(last)
    except ValueError:
        return False
    age_h = (datetime.now(timezone.utc) - last_dt).total_seconds() / 3600.0
    return age_h < _COOLDOWN_HOURS


def _start_device_flow_blocking(timeout_s: int) -> str | None:
    """Run openclaw auth login until we see a URL or hit the timeout.

    Blocking — call from run_in_executor. Reads stdout incrementally so we
    can return as soon as the device-flow URL appears, without waiting
    for the user to actually complete the auth flow.
    """
    import subprocess
    import time
    try:
        proc = subprocess.Popen(
            ["node", "openclaw.mjs", "auth", "login"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=_OPENCLAW_CWD,
            env=_openclaw_env(),
            bufsize=1,  # line-buffered
            text=True,
        )
    except Exception as exc:
        logger.error("could not spawn openclaw auth login: %s", exc)
        return None

    deadline = time.monotonic() + timeout_s
    buf = []
    while time.monotonic() < deadline:
        if proc.stdout is None:
            break
        line = proc.stdout.readline()
        if not line:
            if proc.poll() is not None:
                break
            time.sleep(0.1)
            continue
        buf.append(line)
        match = _URL_PATTERN.search(line) or _URL_PATTERN.search("".join(buf))
        if match:
            return match.group(0)
    return None


async def _start_device_flow(timeout_s: int = _DEVICE_FLOW_TIMEOUT_S) -> str | None:
    """Async wrapper around blocking device-flow capture (Windows-safe)."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _start_device_flow_blocking, timeout_s)


async def maybe_fire_reauth_alert(reason: str = "OAuth token refresh failed") -> bool:
    """If outside cooldown, surface a sign-in URL and alert the user.

    Returns True if an alert was sent, False if cooldown suppressed it or
    if something went wrong. Never raises; this is best-effort
    notification on top of an already-failing call.
    """
    state = _read_state()
    if _on_cooldown(state):
        logger.debug("codex reauth alert suppressed (24h cooldown active)")
        return False

    url = await _start_device_flow()

    # Lazy imports - avoid pulling alerting deps unless we're actually firing.
    try:
        from observability.alerting.discord_notifier import (
            Alert,
            Severity,
            send_alert as discord_send,
        )
        from observability.alerting.telegram_alerts import send_alert as telegram_send
    except Exception as exc:
        logger.error("alerting modules unavailable; cannot notify reauth: %s", exc)
        return False

    title = "Codex OAuth - re-authentication required"
    if url:
        detail = (
            f"OpenClaw OAuth refresh failed. Sign in here to restore Codex routes:\n{url}\n\n"
            f"Reason: {reason}\n"
            "Calls fall back to local Qwen until you sign in."
        )
        action_url = url
    else:
        detail = (
            "OpenClaw OAuth refresh failed and the device-flow URL could not be captured. "
            f"Run on NexusBody: cd {_OPENCLAW_CWD} ; node openclaw.mjs auth login\n\n"
            f"Reason: {reason}"
        )
        action_url = ""

    alert = Alert(
        severity=Severity.WARN,
        title=title,
        detail=detail,
        source="codex_reauth",
        action_taken="auto-spawned device-flow" if url else "device-flow capture failed",
        fields={"reason": reason[:120]},
    )

    discord_ok = False
    telegram_ok = False
    try:
        discord_ok = await discord_send(alert)
    except Exception as exc:
        logger.error("discord reauth alert failed: %s", exc)
    try:
        telegram_ok = await telegram_send(
            Severity.CRITICAL,  # bump to CRITICAL so Telegram actually sends
            title,
            detail[:200],
            action_url=action_url,
        )
    except Exception as exc:
        logger.error("telegram reauth alert failed: %s", exc)

    if discord_ok or telegram_ok:
        state["last_alert_iso"] = datetime.now(timezone.utc).isoformat()
        state["last_url"] = url or ""
        state["last_reason"] = reason
        _write_state(state)
        logger.info("codex reauth alert sent (discord=%s telegram=%s)", discord_ok, telegram_ok)
        return True

    logger.warning("codex reauth alert delivery failed on all channels")
    return False


def reset_cooldown() -> None:
    """Clear the cooldown after a successful Codex chat so future expiry
    can alert immediately instead of waiting out the 24h window."""
    state = _read_state()
    if state.pop("last_alert_iso", None) is not None:
        _write_state(state)
        logger.debug("codex reauth cooldown cleared (successful Codex call)")


class CodexAuthExpired(RuntimeError):
    """Raised by the Codex provider when OpenClaw OAuth refresh fails.

    BrainPool catches this as a normal provider exception and falls
    through to the next provider in the chain. The provider also fires
    a one-shot Discord/Telegram reauth alert before raising.
    """

    def __init__(self, message: str = "codex OAuth expired - re-authenticate") -> None:
        super().__init__(message)
