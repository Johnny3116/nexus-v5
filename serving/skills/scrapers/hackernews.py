"""Hacker News scraper — public JSON API, zero auth.

Two-step API:
  1. GET /topstories.json → list of up to 500 IDs
  2. GET /item/{id}.json  → individual story

We cap step 1 at 50 IDs, fetch in parallel with a shared client,
filter by score threshold, and guard against null responses + text-only
posts (Ask HN / Show HN with no url field).
"""

from __future__ import annotations

import asyncio
import logging
import time

import httpx

logger = logging.getLogger("nexus.broadcaster.hackernews")

_API = "https://hacker-news.firebaseio.com/v0"


async def fetch_top_stories(
    min_score: int = 100,
    max_items: int = 15,
    max_age_hours: int = 24,
) -> list[dict]:
    """Fetch top HN stories above the score threshold.

    Uses a single shared httpx client for all item fetches (not one per
    item — the original version created 50 clients).
    """
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(f"{_API}/topstories.json")
        resp.raise_for_status()
        story_ids: list[int] = resp.json()[:50]

        # Parallel fetch — single client, 50 concurrent requests.
        raw_responses = await asyncio.gather(
            *[client.get(f"{_API}/item/{sid}.json") for sid in story_ids],
            return_exceptions=True,
        )

    cutoff = time.time() - (max_age_hours * 3600)
    items: list[dict] = []

    for raw in raw_responses:
        if isinstance(raw, Exception):
            continue
        story = raw.json()
        # Null guard — some IDs return null.
        if not story:
            continue
        # Only actual stories (skip job posts, polls).
        if story.get("type") != "story":
            continue
        # Score threshold.
        if story.get("score", 0) < min_score:
            continue
        # Age filter.
        if story.get("time", 0) < cutoff:
            continue
        # Skip Ask HN / Show HN text-only posts (no url field).
        story_url = story.get("url")
        if not story_url:
            continue

        items.append({
            "source": "hackernews",
            "title": story.get("title", ""),
            "url": story_url,
            "score": story.get("score", 0),
            "comments": story.get("descendants", 0),
            "posted_by": story.get("by", ""),
            "hn_id": story["id"],
            "hn_url": f"https://news.ycombinator.com/item?id={story['id']}",
            "thumbnail": None,
        })
        if len(items) >= max_items:
            break

    logger.info("HN: %d stories (score > %d, from top 50)", len(items), min_score)
    return items
