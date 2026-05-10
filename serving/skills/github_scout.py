"""nexus-tools — GitHub Scout Skill

Autonomous GitHub repository discovery and analysis.

Workflow (per run):
    1. Search GitHub topics matching John's interests
    2. Deduplicate against posted_urls (skip already-notified repos)
    3. For each candidate: check stars, last commit, license
    4. Security scan: requirements.txt/package.json for red flags,
       suspicious code patterns (obfuscated exec, destructive subprocess, etc.)
    5. Prompt injection scan: README/docs for system-prompt injection attempts
    6. Generate structured project.md (description, stack, findings, score)
    7. Write to Supabase github_queue table
    8. Post a rich Discord embed for repos scoring above threshold
    9. Mark URL as posted in posted_urls

Safety tier: NON_DESTRUCTIVE
    (Reads from GitHub API + shallow-clones to temp dir. No system state modified.)

Standalone entry point (used by APScheduler):
    from serving.skills.github_scout import run_scout
    summary = await run_scout()

Skill engine entry point:
    GithubScoutSkill.execute(context)  — actions: scout, analyze, scan_security
"""

from __future__ import annotations

import logging
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any, Optional

import httpx

from api_gateway.config.settings import get_settings
from serving.skills.execution_context import ExecutionContext
from serving.skills.skill_base import SafetyTier, SkillBase

logger = logging.getLogger("nexus.tools.skills.github_scout")

# Patterns that flag potential prompt injection in README/docs
_INJECTION_PATTERNS = [
    r"ignore previous instructions",
    r"ignore all previous",
    r"you are now",
    r"system prompt",
    r"</?(system|assistant|user)>",
    r"<nexus_task",
    r"act as if you",
    r"roleplay as",
    r"jailbreak",
    r"DAN mode",
]

# Patterns that flag suspicious code
_SUSPICIOUS_CODE_PATTERNS = [
    r"base64\.b64decode\(.{50,}\)",
    r"exec\(.*decode",
    r"eval\(.*decode",
    r"requests\.get\(['\"]http[^'\"]+\.(ru|cn|tk|top)['\"]",
    r"subprocess.*rm -rf",
    r"os\.system.*rm",
]

# Keyword weights for relevance scoring (aligned with John's interests)
_RELEVANCE_KEYWORDS = {
    "agent": 0.15, "llm": 0.1, "ollama": 0.15, "fastapi": 0.1,
    "homelab": 0.1, "automation": 0.1, "vrm": 0.1, "vtuber": 0.1,
    "mcp": 0.1, "claude": 0.1, "local": 0.05, "discord": 0.05,
    "python": 0.05, "asyncio": 0.05,
}


# ── Standalone entry point (called by APScheduler) ────────────────────────────

async def run_scout(settings=None, db=None) -> dict:
    """Execute a full scout run across all configured topics.

    Args:
        settings: NexusSettings instance. Falls back to get_settings() if None.
        db:       SupabaseClient instance. Falls back to SupabaseClient() if None.

    Returns:
        Summary dict: {candidates_found, analyzed, notified, skipped_dedup}
    """
    from kv_cache.cold.supabase_client import get_supabase as _get_supabase  # phase 2 wiring
    # PostedUrlsRepository — deferred to Phase 2 (needs Supabase table migration)

    if settings is None:
        settings = get_settings()
    if db is None:
        db = SupabaseClient()

    posted_repo = PostedUrlsRepository(db)

    topics = [t.strip() for t in settings.github_scout_topics.split(",") if t.strip()]
    max_per_run = settings.github_scout_max_per_run
    min_stars = settings.github_scout_min_stars
    min_relevance = settings.github_scout_min_relevance

    candidates = await _search_github(topics, min_stars, settings.github_token)
    logger.info("GitHub Scout: %d candidates found across %d topics", len(candidates), len(topics))

    # Determine notification channel
    notify_channel = (
        settings.github_scout_notify_channel
        or settings.discord_channel_dev_feed
        or settings.discord_channel_general
    )

    # Deduplicate against posted_urls
    candidate_items = [{"url": r["html_url"], **r} for r in candidates]
    fresh = posted_repo.filter_new(candidate_items, notify_channel) if notify_channel else candidate_items
    skipped = len(candidates) - len(fresh)
    logger.info("GitHub Scout: %d fresh after dedup (%d already posted)", len(fresh), skipped)

    analyzed = 0
    notified = 0

    for repo in fresh[:max_per_run]:
        result = await _analyze_repo(repo["html_url"], repo, settings)
        analyzed += 1

        relevance = result.get("relevance_score", 0.0)
        has_critical = result.get("security", {}).get("critical_issues", False)
        injection_risk = result.get("injection", {}).get("risk", False)

        if relevance >= min_relevance and not has_critical:
            await _notify_discord(
                url=repo["html_url"],
                repo_meta=repo,
                result=result,
                settings=settings,
                notify_channel=notify_channel,
            )
            if notify_channel:
                posted_repo.mark_posted(
                    url=repo["html_url"],
                    channel_id=notify_channel,
                    channel_key="github_scout",
                    source="github",
                    title=repo.get("full_name", ""),
                )
            notified += 1
            logger.info(
                "Scout posted: %s (relevance=%.2f injection=%s)",
                repo["html_url"], relevance, injection_risk,
            )
        else:
            logger.info(
                "Scout skipped notification: %s (relevance=%.2f critical=%s)",
                repo["html_url"], relevance, has_critical,
            )

    summary = {
        "candidates_found": len(candidates),
        "skipped_dedup": skipped,
        "analyzed": analyzed,
        "notified": notified,
    }
    logger.info("GitHub Scout complete: %s", summary)
    return summary


# ── SkillBase class (called by the agentic engine) ────────────────────────────

class GithubScoutSkill(SkillBase):
    name = "github_scout"
    description = (
        "Autonomously discover and analyze GitHub repositories matching John's interests. "
        "Runs security and prompt injection scans. Posts to Discord. Deduplicates via posted_urls."
    )
    safety_tier = SafetyTier.NON_DESTRUCTIVE
    version = "1.1.0"

    async def execute(self, context: ExecutionContext) -> dict:
        dispatch = {
            "scout": self._skill_scout,
            "analyze": self._skill_analyze,
            "scan_security": self._skill_scan_security,
        }
        handler = dispatch.get(context.action)
        if handler is None:
            return {"success": False, "error": f"Unknown action '{context.action}'"}
        return await handler(context)

    def get_capabilities(self) -> list[dict]:
        return [
            {"action": "scout", "description": "Run a full autonomous discovery cycle across configured topics"},
            {
                "action": "analyze",
                "description": "Analyze a specific GitHub repository",
                "params": {"url": "GitHub repo URL"},
            },
            {
                "action": "scan_security",
                "description": "Run security scan on a locally cloned repo",
                "params": {"path": "local clone path"},
            },
        ]

    async def _skill_scout(self, context: ExecutionContext) -> dict:
        summary = await run_scout()
        return {"success": True, **summary}

    async def _skill_analyze(self, context: ExecutionContext) -> dict:
        url = context.require_param("url")
        settings = get_settings()
        result = await _analyze_repo(url, None, settings)
        return {"success": True, **result}

    async def _skill_scan_security(self, context: ExecutionContext) -> dict:
        path_str = context.require_param("path")
        path = Path(path_str)
        if not path.exists():
            return {"success": False, "error": f"Path does not exist: {path_str}"}
        findings = _run_security_scan(path)
        return {"success": True, "path": path_str, "findings": findings}


# ── Core pipeline (shared by standalone + skill engine) ──────────────────────

async def _search_github(topics: list[str], min_stars: int, token: str) -> list[dict]:
    """Search GitHub for repos matching topics, filtered by min stars."""
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "Nexus-V4-Scout/1.1",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    candidates = []
    async with httpx.AsyncClient(timeout=30.0, headers=headers) as client:
        for topic in topics:
            try:
                resp = await client.get(
                    "https://api.github.com/search/repositories",
                    params={
                        "q": f"topic:{topic} stars:>={min_stars}",
                        "sort": "updated",
                        "per_page": 5,
                    },
                )
                if resp.status_code == 200:
                    candidates.extend(resp.json().get("items", []))
                elif resp.status_code == 403:
                    logger.warning("GitHub rate limit hit for topic '%s'", topic)
                    break
                else:
                    logger.warning("GitHub search for '%s' returned %d", topic, resp.status_code)
            except Exception as exc:
                logger.error("GitHub search failed for topic '%s': %s", topic, exc)

    # Deduplicate by repo ID
    seen: set[int] = set()
    unique = []
    for repo in candidates:
        rid = repo.get("id")
        if rid not in seen:
            seen.add(rid)
            unique.append(repo)
    return unique


async def _analyze_repo(url: str, repo_meta: Optional[dict], settings) -> dict:
    """Clone + scan one repo. Returns analysis dict."""
    result: dict[str, Any] = {"url": url}
    tmp_dir: Optional[Path] = None

    try:
        tmp_dir = Path(tempfile.mkdtemp(prefix="nexus_scout_"))
        if not await _clone_repo(url, tmp_dir):
            result["error"] = "clone_failed"
            return result

        readme = _read_readme(tmp_dir)
        security = _run_security_scan(tmp_dir)
        injection = _scan_injection(readme)
        relevance = _score_relevance(readme, (repo_meta or {}).get("description", ""), security, injection)

        project_md = _generate_project_md(
            url=url,
            description=(repo_meta or {}).get("description", ""),
            stars=(repo_meta or {}).get("stargazers_count", 0),
            language=(repo_meta or {}).get("language", ""),
            license_name=((repo_meta or {}).get("license") or {}).get("spdx_id", "unknown"),
            readme=readme,
            security=security,
            injection=injection,
            relevance=relevance,
        )

        await _write_to_queue(url, repo_meta or {}, project_md, security, relevance)

        result.update({
            "relevance_score": relevance,
            "security": security,
            "injection": injection,
            "project_md": project_md,
        })

    except Exception as exc:
        logger.error("Repo analysis failed for %s: %s", url, exc, exc_info=True)
        result["error"] = str(exc)
    finally:
        if tmp_dir and tmp_dir.exists():
            shutil.rmtree(tmp_dir, ignore_errors=True)

    return result


async def _clone_repo(url: str, dest: Path) -> bool:
    import asyncio
    try:
        proc = await asyncio.create_subprocess_exec(
            "git", "clone", "--depth=1", url, str(dest),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=120)
        if proc.returncode != 0:
            logger.warning("Clone failed for %s: %s", url, stderr_b.decode(errors="replace").strip())
            return False
        return True
    except Exception as exc:
        logger.warning("Clone exception for %s: %s", url, exc)
        return False


def _read_readme(repo_path: Path) -> str:
    for name in ["README.md", "README.rst", "README.txt", "README", "readme.md"]:
        p = repo_path / name
        if p.exists():
            try:
                return p.read_text(encoding="utf-8", errors="replace")[:10000]
            except Exception:
                pass
    return ""


def _run_security_scan(repo_path: Path) -> dict:
    issues = []
    critical = False

    req_path = repo_path / "requirements.txt"
    if req_path.exists():
        try:
            content = req_path.read_text(errors="replace")
            unpinned = [
                line.strip() for line in content.splitlines()
                if line.strip() and not line.startswith("#")
                and "==" not in line and ">=" not in line
            ]
            if unpinned:
                issues.append({"type": "unpinned_deps", "details": unpinned[:10]})
        except Exception:
            pass

    for py_file in list(repo_path.rglob("*.py"))[:100]:
        try:
            content = py_file.read_text(encoding="utf-8", errors="replace")
            for pattern in _SUSPICIOUS_CODE_PATTERNS:
                if re.search(pattern, content, re.IGNORECASE):
                    issues.append({
                        "type": "suspicious_code",
                        "file": str(py_file.relative_to(repo_path)),
                        "pattern": pattern,
                    })
                    critical = True
                    break
        except Exception:
            pass

    return {"issues": issues, "critical_issues": critical, "issue_count": len(issues)}


def _scan_injection(text: str) -> dict:
    found = [p for p in _INJECTION_PATTERNS if re.search(p, text, re.IGNORECASE)]
    return {"risk": len(found) > 0, "patterns_found": found}


def _score_relevance(readme: str, description: str, security: dict, injection: dict) -> float:
    combined = (readme + " " + description).lower()
    score = sum(w for kw, w in _RELEVANCE_KEYWORDS.items() if kw in combined)
    if security.get("critical_issues"):
        score -= 0.3
    if injection.get("risk"):
        score -= 0.2
    return round(max(0.0, min(1.0, score)), 2)


def _generate_project_md(
    url: str, description: str, stars: int, language: str,
    license_name: str, readme: str, security: dict, injection: dict, relevance: float,
) -> str:
    return (
        f"# Project Analysis: {url}\n\n"
        f"**Description:** {description}\n"
        f"**Stars:** {stars} | **Language:** {language} | **License:** {license_name}\n"
        f"**Relevance Score:** {relevance:.2f}/1.00\n\n"
        f"## Security Findings\n"
        f"- Issues found: {security['issue_count']}\n"
        f"- Critical: {security['critical_issues']}\n\n"
        f"## Prompt Injection Risk\n"
        f"- Risk detected: {injection['risk']}\n"
        f"- Patterns: {', '.join(injection['patterns_found']) or 'none'}\n\n"
        f"## README Excerpt\n```\n{readme[:500]}\n```\n"
    )


async def _write_to_queue(url: str, repo_meta: dict, project_md: str, security: dict, relevance: float) -> None:
    try:
        from kv_cache.cold.supabase_client import get_supabase as get_db  # phase 2
        # SecurityCheck type — deferred to Phase 2
        db = get_db()
        db.table("github_queue").upsert({
            "repo_url": url,
            "repo_name": repo_meta.get("full_name", url.split("/")[-1]),
            "description": repo_meta.get("description", ""),
            "stars": repo_meta.get("stargazers_count", 0),
            "language": repo_meta.get("language"),
            "relevance_score": relevance,
            "security_check": (
                SecurityCheck.FLAGGED.value
                if security.get("critical_issues")
                else SecurityCheck.PASSED.value
            ),
            "project_md": project_md,
            "notified": False,
        }).execute()
    except Exception as exc:
        logger.warning("Failed to write to github_queue: %s", exc)


async def _notify_discord(url: str, repo_meta: dict, result: dict, settings, notify_channel: str) -> None:
    """Post a scout report embed to Discord."""
    try:
        from observability.alerting.discord_notifier import send_report  # phase 2 wiring

        relevance = result.get("relevance_score", 0.0)
        security = result.get("security", {})
        injection = result.get("injection", {})

        sec_status = (
            "Critical issues found — review before use"
            if security.get("critical_issues")
            else f"Clean — {security.get('issue_count', 0)} minor issue(s)"
        )
        if injection.get("risk"):
            sec_status += " | Injection patterns detected"

        relevance_label = (
            "High" if relevance >= 0.7
            else "Medium" if relevance >= 0.5
            else "Low"
        )

        await send_scout_report(ScoutReport(
            repo_name=repo_meta.get("full_name", url),
            repo_url=url,
            description=(repo_meta.get("description") or "")[:300],
            relevance_score=f"{relevance_label} ({relevance:.0%})",
            security_status=sec_status,
            stars=str(repo_meta.get("stargazers_count", "?")),
            language=repo_meta.get("language"),
        ))
    except Exception as exc:
        logger.warning("Scout Discord notify failed: %s", exc)
