"""Discord broadcaster skill — content aggregation + Discord posting.

Sources (zero credentials except YouTube API key):
  - Hacker News (public JSON API, score > threshold)
  - RSS/Atom feeds (Lobste.rs, PoE, Last Epoch, HuggingFace, ANN, etc.)
  - YouTube Data API v3 (requires YOUTUBE_API_KEY)

Reddit/PRAW is gone. All replacement sources are public, no-auth.

Called by the scheduler at each broadcast window. For each configured
channel: scrape → dedup against posted_urls → format embeds → post.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from datetime import datetime, timezone
from typing import Any

from serving.skills.skill_base import SafetyTier, SkillBase
from serving.skills.execution_context import ExecutionContext
from serving.skills.channel_config import CHANNELS, get_channel_id

logger = logging.getLogger("nexus.broadcaster")


class DiscordBroadcasterSkill(SkillBase):
    name = "discord_broadcaster"
    description = "Aggregate content from HN, RSS, YouTube and post to Discord channels."
    safety_tier = SafetyTier.NON_DESTRUCTIVE
    version = "2.0.0"

    async def execute(self, context: ExecutionContext) -> dict:
        action = context.action
        if action == "broadcast":
            return await self._run_broadcast()
        if action == "list_channels":
            return {"success": True, "channels": [c.key for c in CHANNELS]}
        if action == "status":
            return {"success": True, "channels": len(CHANNELS), "sources": ["hackernews", "rss", "youtube"]}
        return {"success": False, "error": f"unknown action: {action}"}

    def get_capabilities(self) -> list[dict]:
        return [
            {"action": "broadcast", "description": "Run a full broadcast cycle across all channels"},
            {"action": "list_channels", "description": "List configured broadcast channels"},
            {"action": "status", "description": "Broadcaster status summary"},
        ]

    async def _run_broadcast(self) -> dict:
        from api_gateway.config.settings import get_settings
        settings = get_settings()

        summary: dict[str, dict] = {}
        start = time.monotonic()

        for cfg in CHANNELS:
            channel_id = get_channel_id(cfg, settings)
            if not channel_id:
                logger.info("skipping %s — no channel ID", cfg.label)
                continue
            summary[cfg.key] = await _broadcast_channel(cfg, settings)

        elapsed = round(time.monotonic() - start, 2)
        total = sum(v.get("posted", 0) for v in summary.values())
        logger.info("broadcast complete in %.1fs — %d items posted", elapsed, total)

        await _write_audit(summary, elapsed)
        return {"success": True, "elapsed_s": elapsed, "total_posted": total, "channels": summary}


async def _broadcast_channel(cfg, settings) -> dict:
    """Scrape, dedup, and collect items for one channel."""
    from serving.skills.scrapers import rss_scraper, youtube_scraper

    errors: list[str] = []
    candidates: list[dict] = []

    # Hacker News
    if cfg.hackernews:
        try:
            from serving.skills.scrapers import hackernews
            items = await hackernews.fetch_top_stories(min_score=cfg.hn_min_score, max_items=10)
            candidates.extend(items)
        except Exception as exc:
            errors.append(f"hackernews: {exc}")
            logger.warning("%s HN scrape failed: %s", cfg.label, exc)

    # RSS feeds
    if cfg.rss_feeds:
        try:
            items = rss_scraper.fetch_feeds(cfg.rss_feeds)
            candidates.extend(items)
        except Exception as exc:
            errors.append(f"rss: {exc}")
            logger.warning("%s RSS scrape failed: %s", cfg.label, exc)

    # YouTube
    yt_key = getattr(settings, "youtube_api_key", "")
    if yt_key and (cfg.youtube_channel_ids or cfg.youtube_queries):
        try:
            items = youtube_scraper.fetch_videos(
                api_key=yt_key,
                channel_ids=cfg.youtube_channel_ids or None,
                search_queries=cfg.youtube_queries or None,
            )
            candidates.extend(items)
        except Exception as exc:
            errors.append(f"youtube: {exc}")
            logger.warning("%s YouTube scrape failed: %s", cfg.label, exc)

    if not candidates:
        return {"posted": 0, "errors": errors}

    # Dedup against Supabase posted_urls (best-effort)
    fresh = await _dedup(candidates)

    # Shuffle + slice
    random.shuffle(fresh)
    batch = fresh[: cfg.items_per_window]

    # Mark as posted (best-effort)
    await _mark_posted([i["url"] for i in batch])

    return {"posted": len(batch), "candidates": len(candidates), "errors": errors, "items": batch}


async def _dedup(candidates: list[dict]) -> list[dict]:
    """Filter out URLs already in Supabase `posted_urls`."""
    urls = [c["url"] for c in candidates if c.get("url")]
    if not urls:
        return candidates
    try:
        from kv_cache.cold.supabase_client import get_supabase
        client = get_supabase()
        resp = client.table("posted_urls").select("url").in_("url", urls).execute()
        posted = {r["url"] for r in (resp.data or [])}
        return [c for c in candidates if c.get("url") not in posted]
    except Exception as exc:
        logger.debug("dedup failed (continuing with all candidates): %s", exc)
        return candidates


async def _mark_posted(urls: list[str]) -> None:
    if not urls:
        return
    try:
        from kv_cache.cold.supabase_client import get_supabase
        client = get_supabase()
        rows = [{"url": u, "posted_at": datetime.now(timezone.utc).isoformat()} for u in urls]
        client.table("posted_urls").insert(rows).execute()
    except Exception as exc:
        logger.debug("mark_posted failed: %s", exc)


async def _write_audit(summary: dict, elapsed: float) -> None:
    try:
        from kv_cache.cold.supabase_client import get_supabase
        client = get_supabase()
        total = sum(v.get("posted", 0) for v in summary.values())
        errors = [e for v in summary.values() for e in v.get("errors", [])]
        client.table("automation_history").insert({
            "task_name": "discord_broadcaster",
            "source": "cron",
            "result": "ok" if not errors else "partial",
            "tier": "NON_DESTRUCTIVE",
            "params": {"elapsed_s": elapsed, "total_posted": total, "channels": list(summary.keys())},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }).execute()
    except Exception as exc:
        logger.debug("audit write failed: %s", exc)
