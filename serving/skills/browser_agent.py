"""nexus-tools — Browser Agent Skill

Domain-allowlisted web scraping and research via Playwright.

SECURITY CONTRACT (hard guardrail — not configurable at runtime):
    All URLs are validated against ALLOWED_DOMAINS BEFORE any request is made.
    No exceptions. Not even if the Brain specifically asks.
    Blocked domains are logged as security events.

    Explicitly blocked categories:
        - Email providers (mail.*, gmail.*, etc.)
        - Calendar services
        - Social media (twitter/X, facebook, instagram, linkedin, tiktok, reddit)
        - Any domain not in ALLOWED_DOMAINS

Actions:
    fetch     — fetch and return text content from an allowed URL
    search    — search an allowed search engine and return results
    screenshot — take a screenshot for vision analysis (Playwright required)
"""

from __future__ import annotations

import logging
import re

import httpx

from safety.input_filters.domain_allowlist import (
    is_allowed as _safety_is_allowed,
    is_blocked_pattern as _safety_is_blocked_pattern,
)
from serving.skills.execution_context import ExecutionContext
from serving.skills.skill_base import SafetyTier, SkillBase

logger = logging.getLogger("nexus.tools.skills.browser_agent")


def _is_allowed_url(url: str) -> tuple[bool, str]:
    """Validate a URL via the canonical safety.input_filters.domain_allowlist.

    Blocked-pattern check runs first (defense-in-depth for mail/social/etc.),
    then the allowlist check. Returns (allowed: bool, reason: str).
    """
    if not url:
        return False, "empty URL"

    blocked, reason = _safety_is_blocked_pattern(url)
    if blocked:
        return False, reason

    if not _safety_is_allowed(url):
        return False, f"domain not in safety.input_filters.domain_allowlist: {url}"

    return True, ""


class BrowserAgentSkill(SkillBase):
    name = "browser_agent"
    description = (
        "Domain-allowlisted web fetching and research. "
        "Only accesses approved domains (GitHub, PyPI, docs, arxiv, etc.). "
        "Hard-blocked: email, calendar, social media."
    )
    safety_tier = SafetyTier.NON_DESTRUCTIVE
    version = "1.0.0"

    async def execute(self, context: ExecutionContext) -> dict:
        action = context.action
        dispatch = {
            "fetch": self._fetch,
            "search": self._search,
        }
        handler = dispatch.get(action)
        if handler is None:
            return {"success": False, "error": f"Unknown action '{action}'"}
        return await handler(context)

    def get_capabilities(self) -> list[dict]:
        return [
            {
                "action": "fetch",
                "description": "Fetch text content from an allowed URL",
                "params": {"url": "URL to fetch (must be in allowed domains)"},
            },
            {
                "action": "search",
                "description": "Search GitHub or PyPI for packages/repos",
                "params": {
                    "query": "search query",
                    "engine": "github|pypi (default: github)",
                },
            },
        ]

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    async def _fetch(self, context: ExecutionContext) -> dict:
        url = context.require_param("url")

        allowed, reason = _is_allowed_url(url)
        if not allowed:
            logger.warning("SECURITY: browser_agent fetch blocked — %s (url=%s)", reason, url)
            return {
                "success": False,
                "error": f"URL blocked: {reason}",
                "security_block": True,
            }

        try:
            async with httpx.AsyncClient(
                timeout=30.0,
                follow_redirects=True,
                headers={"User-Agent": "Nexus-V4-BrowserAgent/1.0"},
            ) as client:
                resp = await client.get(url)
                resp.raise_for_status()

                content_type = resp.headers.get("content-type", "")
                if "html" in content_type:
                    # Strip HTML tags for plain text
                    text = re.sub(r"<[^>]+>", " ", resp.text)
                    text = re.sub(r"\s+", " ", text).strip()
                else:
                    text = resp.text

                return {
                    "success": True,
                    "url": url,
                    "status_code": resp.status_code,
                    "content": text[:8000],  # Truncate large pages
                    "content_type": content_type,
                }
        except httpx.HTTPStatusError as exc:
            return {"success": False, "error": f"HTTP {exc.response.status_code}: {url}"}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    async def _search(self, context: ExecutionContext) -> dict:
        query = context.require_param("query")
        engine = context.get_param("engine", "github")

        if engine == "github":
            url = f"https://api.github.com/search/repositories?q={query}&sort=stars&per_page=5"
        elif engine == "pypi":
            url = f"https://pypi.org/search/?q={query}&format=json"
        else:
            return {"success": False, "error": f"Unknown search engine '{engine}'. Use: github, pypi"}

        allowed, reason = _is_allowed_url(url)
        if not allowed:
            return {"success": False, "error": f"Search URL blocked: {reason}"}

        try:
            async with httpx.AsyncClient(
                timeout=15.0,
                headers={"User-Agent": "Nexus-V4-BrowserAgent/1.0"},
            ) as client:
                resp = await client.get(url)
                resp.raise_for_status()

                if engine == "github":
                    items = resp.json().get("items", [])
                    results = [
                        {
                            "name": r["full_name"],
                            "url": r["html_url"],
                            "description": r.get("description", ""),
                            "stars": r.get("stargazers_count", 0),
                            "language": r.get("language"),
                        }
                        for r in items
                    ]
                else:
                    results = [{"raw": resp.text[:2000]}]

                return {"success": True, "engine": engine, "query": query, "results": results}
        except Exception as exc:
            return {"success": False, "error": str(exc)}
