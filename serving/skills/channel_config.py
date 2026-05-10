"""Discord broadcast channel configuration.

Maps each channel to its content sources. Reddit is gone — replaced with
Hacker News (public JSON API), Lobste.rs (public RSS), and gaming RSS
feeds (PoE, Last Epoch). Zero credentials required for any new source.

Channel keys match the .env suffix: discord_channel_<key>
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ChannelConfig:
    key: str
    label: str
    colour: int
    hackernews: bool = False
    hn_min_score: int = 100
    rss_feeds: list[str] = field(default_factory=list)
    youtube_channel_ids: list[str] = field(default_factory=list)
    youtube_queries: list[str] = field(default_factory=list)
    items_per_window: int = 5


CHANNELS: list[ChannelConfig] = [

    # #tech-news — HN (score > 100) + Lobste.rs RSS
    ChannelConfig(
        key="tech_news",
        label="#tech-news",
        colour=0x7289DA,
        hackernews=True,
        hn_min_score=100,
        rss_feeds=[
            "https://lobste.rs/rss",
            "https://hnrss.org/frontpage",       # HN RSS fallback
        ],
        youtube_queries=["AI news 2026", "open source project"],
        items_per_window=5,
    ),

    # #game-news — PoE + Last Epoch + general gaming RSS
    ChannelConfig(
        key="game_news",
        label="#game-news",
        colour=0xF04747,
        rss_feeds=[
            "https://www.pathofexile.com/news/rss",
            "https://store.steampowered.com/feeds/news/app/899770",  # Last Epoch Steam news
            "https://www.pcgamer.com/rss/",
            "https://www.rockpapershotgun.com/feed",
        ],
        youtube_queries=["Path of Exile news", "Last Epoch update"],
        items_per_window=5,
    ),

    # #ai-drops — AI/ML focused
    ChannelConfig(
        key="ai_drops",
        label="#ai-drops",
        colour=0x9B59B6,
        hackernews=True,
        hn_min_score=150,
        rss_feeds=[
            "https://huggingface.co/blog/feed.xml",
            "https://rsshub.app/papers/cs.AI",   # arxiv cs.AI via RSSHub (paperswithcode feed is broken XML)
        ],
        youtube_queries=["large language model tutorial", "AI agent development"],
        items_per_window=5,
    ),

    # #anime — anime news + releases
    ChannelConfig(
        key="anime",
        label="#anime",
        colour=0xFF73FA,
        rss_feeds=[
            "https://www.animenewsnetwork.com/all/rss.xml?cat=anime",
            "https://myanimelist.net/rss/news.xml",
        ],
        youtube_queries=["anime news 2026", "new anime season"],
        items_per_window=5,
    ),

    # #dev-feed — programming / open source
    ChannelConfig(
        key="dev_feed",
        label="#dev-feed",
        colour=0x43B581,
        rss_feeds=[
            "https://lobste.rs/rss",
            "https://github.blog/feed/",
        ],
        youtube_queries=["programming tutorial 2026"],
        items_per_window=5,
    ),
]

CHANNEL_MAP: dict[str, ChannelConfig] = {c.key: c for c in CHANNELS}


def get_channel_id(cfg: ChannelConfig, settings) -> str:
    attr = f"discord_channel_{cfg.key}"
    return getattr(settings, attr, "") or ""
