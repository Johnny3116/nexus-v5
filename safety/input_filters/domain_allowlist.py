"""Domain allowlist for outbound web access.

Doctrine §10: web sandbox may only fetch from an explicit allowlist.
Any attempt to fetch outside this list is blocked at the filter layer
and reported to observability as a potential injection attempt.
"""

from __future__ import annotations

from urllib.parse import urlparse

# Frozen list from CLAUDE.md §10. Changes require John's approval —
# do NOT add to this list from code.
#
# 2026-04-21 — merged with previous browser_agent-local list during Track B
# middleware mounting so there is one canonical allowlist. New additions
# below (dev / docs / research) are the union of both drifted lists.
ALLOWED_DOMAINS = frozenset(
    {
        # --- Code + packages ------------------------------------------------
        "github.com",
        "api.github.com",
        "raw.githubusercontent.com",
        "pypi.org",
        "files.pythonhosted.org",
        "npmjs.com",
        "registry.npmjs.org",
        "crates.io",
        # --- Docs ----------------------------------------------------------
        "docs.python.org",
        "docs.anthropic.com",
        "docs.docker.com",
        "fastapi.tiangolo.com",
        "tailscale.com",
        "ollama.com",
        # --- Research / AI -------------------------------------------------
        "huggingface.co",
        "arxiv.org",
        "stackoverflow.com",
        # --- Community (read-only research only) ---------------------------
        "reddit.com",
        "old.reddit.com",
        "youtube.com",
        "googleapis.com",
    }
)

# Defense-in-depth: even if a domain slips through the allowlist, these
# hostname fragments are never acceptable. Applied additively by callers
# (e.g. serving/skills/browser_agent.py).
BLOCKED_PATTERNS: tuple[str, ...] = (
    "mail.",
    "gmail.",
    "outlook.",
    "calendar.",
    "facebook.",
    "twitter.",
    "x.com",
    "instagram.",
    "linkedin.",
    "tiktok.",
    "snapchat.",
    "discord.com",    # webhooks only, never browser scrape
    "whatsapp.",
    "telegram.",
)


def is_blocked_pattern(url: str) -> tuple[bool, str]:
    """Defense-in-depth pattern check. Returns (blocked, reason)."""
    host = _host_of(url)
    for pat in BLOCKED_PATTERNS:
        if pat in host:
            return True, f"matches blocked pattern {pat!r}: {host}"
    return False, ""


class DomainBlocked(Exception):
    """Raised when the fetcher attempts a non-allowlisted domain."""


def _host_of(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    # Strip leading "www." for allowlist comparison
    if host.startswith("www."):
        host = host[4:]
    return host


def is_allowed(url: str) -> bool:
    host = _host_of(url)
    if not host:
        return False
    if host in ALLOWED_DOMAINS:
        return True
    # Allow subdomains of explicit parents (e.g. api.github.com → github.com)
    for allowed in ALLOWED_DOMAINS:
        if host.endswith("." + allowed):
            return True
    return False


def require_allowed(url: str) -> None:
    if not is_allowed(url):
        raise DomainBlocked(f"domain not allowlisted: {_host_of(url) or url}")
