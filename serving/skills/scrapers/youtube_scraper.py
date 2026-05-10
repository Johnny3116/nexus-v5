"""YouTube Data API v3 scraper — requires YOUTUBE_API_KEY.

Ported from V4, no changes needed (was already Reddit-free).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger("nexus.broadcaster.youtube")

_YT_BASE = "https://www.youtube.com/watch?v="


def fetch_videos(
    api_key: str,
    channel_ids: Optional[list[str]] = None,
    search_queries: Optional[list[str]] = None,
    published_after_hours: int = 24,
    max_results: int = 10,
) -> list[dict]:
    if not api_key:
        logger.warning("YouTube API key not configured — skipping")
        return []

    try:
        from googleapiclient.discovery import build
    except ImportError:
        logger.error("google-api-python-client not installed")
        return []

    try:
        youtube = build("youtube", "v3", developerKey=api_key)
    except Exception as exc:
        logger.error("YouTube client build failed: %s", exc)
        return []

    cutoff = (
        datetime.now(tz=timezone.utc) - timedelta(hours=published_after_hours)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")

    seen: set[str] = set()
    items: list[dict] = []

    targets: list[dict] = []
    for cid in (channel_ids or []):
        targets.append({"channelId": cid})
    for q in (search_queries or []):
        targets.append({"q": q})

    for params in targets:
        try:
            resp = youtube.search().list(
                part="snippet", type="video", order="date",
                publishedAfter=cutoff, maxResults=max_results, **params,
            ).execute()
            for item in resp.get("items", []):
                vid_id = item["id"].get("videoId")
                if not vid_id or vid_id in seen:
                    continue
                seen.add(vid_id)
                snippet = item["snippet"]
                thumb = (
                    snippet.get("thumbnails", {})
                    .get("high", snippet.get("thumbnails", {}).get("default", {}))
                    .get("url")
                )
                items.append({
                    "source": "youtube",
                    "title": snippet.get("title", ""),
                    "url": f"{_YT_BASE}{vid_id}",
                    "channel": snippet.get("channelTitle", ""),
                    "published_at": snippet.get("publishedAt", ""),
                    "thumbnail": thumb,
                    "description": snippet.get("description", "")[:200],
                })
        except Exception as exc:
            logger.warning("YouTube fetch failed for %s: %s", params, exc)

    logger.info("YouTube: fetched %d videos", len(items))
    return items
