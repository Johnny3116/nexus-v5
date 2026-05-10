"""RSS/Atom feed scraper — feedparser, no auth.

Ported from V4 with Reddit references removed. Handles any RSS/Atom feed
including Lobste.rs, PoE news, Last Epoch, anime, etc.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from time import mktime
from typing import Optional

logger = logging.getLogger("nexus.broadcaster.rss")


def fetch_feeds(
    feed_urls: list[str],
    max_age_hours: int = 24,
    max_per_feed: int = 10,
) -> list[dict]:
    """Fetch recent entries from RSS/Atom feeds.

    Returns list of ContentItem dicts, deduplicated by URL.
    """
    try:
        import feedparser
    except ImportError:
        logger.error("feedparser not installed — pip install feedparser")
        return []

    cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=max_age_hours)
    seen: set[str] = set()
    items: list[dict] = []

    for feed_url in feed_urls:
        feed_url = feed_url.strip()
        if not feed_url:
            continue
        try:
            feed = feedparser.parse(feed_url)
            if feed.bozo and not feed.entries:
                logger.warning("RSS parse error for %s: %s", feed_url, feed.bozo_exception)
                continue

            feed_title = feed.feed.get("title", feed_url)
            count = 0
            for entry in feed.entries:
                if count >= max_per_feed:
                    break
                url = entry.get("link", "")
                if not url or url in seen:
                    continue
                published = _parse_published(entry)
                if published and published < cutoff:
                    continue
                seen.add(url)
                items.append({
                    "source": "rss",
                    "feed_title": feed_title,
                    "title": entry.get("title", ""),
                    "url": url,
                    "summary": _truncate(entry.get("summary", ""), 200),
                    "published_at": published.isoformat() if published else "",
                    "thumbnail": _extract_thumbnail(entry),
                })
                count += 1
        except Exception as exc:
            logger.warning("RSS fetch failed for %s: %s", feed_url, exc)

    logger.info("RSS: fetched %d entries from %d feeds", len(items), len(feed_urls))
    return items


def _parse_published(entry) -> Optional[datetime]:
    for attr in ("published_parsed", "updated_parsed", "created_parsed"):
        val = getattr(entry, attr, None)
        if val:
            try:
                return datetime.fromtimestamp(mktime(val), tz=timezone.utc)
            except Exception:
                continue
    return None


def _extract_thumbnail(entry) -> Optional[str]:
    if hasattr(entry, "media_thumbnail") and entry.media_thumbnail:
        return entry.media_thumbnail[0].get("url")
    for enc in getattr(entry, "enclosures", []):
        if enc.get("type", "").startswith("image/"):
            return enc.get("href") or enc.get("url")
    return None


def _truncate(text: str, n: int) -> str:
    return text if len(text) <= n else text[: n - 1] + "\u2026"
