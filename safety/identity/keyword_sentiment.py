"""Rule-based keyword sentiment analysis — Soul v1.

Pure function: text in, ExpressionPayload out. No side effects, no I/O.
This is the swap point for future upgrades: replacing this module with
VADER or a transformer sentiment model only requires matching the
`analyze(text) -> ExpressionPayload` signature.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from typing import Any

from safety.identity.keywords import KEYWORDS, PRIORITY, EXPRESSION_MAP

_WORD_RE = re.compile(r"\b[\w']+\b", re.UNICODE)


@dataclass
class ExpressionPayload:
    """Soul output. Feeds the expression controller and is broadcast over WS.

    Attributes:
        expression: The VRM expression preset name (e.g. "happy", "angry").
        weight: Expression intensity, 0.0-1.0.
        duration_ms: How long the expression should hold before auto-fade.
        source: Identifier of the Soul implementation that produced this
            payload, for debug/routing. v1 uses "keyword_v1".
        context: Optional dict of extra fields (e.g. category, hit counts).
    """

    expression: str
    weight: float
    duration_ms: int
    source: str
    context: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _tokenize(text: str) -> list[str]:
    return [tok.lower() for tok in _WORD_RE.findall(text)]


def _count_hits(tokens: list[str]) -> dict[str, int]:
    hits: dict[str, int] = {cat: 0 for cat in KEYWORDS}
    for tok in tokens:
        for cat, words in KEYWORDS.items():
            if tok in words:
                hits[cat] += 1
    return hits


def _winning_category(hits: dict[str, int]) -> str | None:
    """Return the category with the highest hit count, breaking ties by PRIORITY order.

    Returns None if no category has any hits.
    """
    max_count = max(hits.values()) if hits else 0
    if max_count == 0:
        return None
    top = [cat for cat, count in hits.items() if count == max_count]
    for cat in PRIORITY:
        if cat in top:
            return cat
    return top[0]  # unreachable if PRIORITY covers all categories


def analyze(text: str) -> ExpressionPayload:
    """Classify text sentiment and return an expression payload.

    Algorithm:
        1. Tokenize (lowercase, word-boundary split).
        2. Count keyword hits per category.
        3. Pick the winning category (highest count, PRIORITY tie-break).
        4. If no hits → neutral, weight 0.5, 2000ms.
        5. Otherwise → map category to VRM preset, scale weight by
           hit_count/total_words (capped at 0.9, floored at 0.4), 2500ms.
    """
    tokens = _tokenize(text)
    total_words = max(1, len(tokens))  # avoid div-by-zero on empty input
    hits = _count_hits(tokens)
    category = _winning_category(hits)

    if category is None:
        return ExpressionPayload(
            expression=EXPRESSION_MAP["neutral"],
            weight=0.5,
            duration_ms=2000,
            source="keyword_v1",
            context={"category": "neutral", "hits": hits, "total_words": total_words},
        )

    hit_count = hits[category]
    raw_weight = hit_count / total_words
    weight = max(0.4, min(0.9, raw_weight * 3.0))  # scale up — single keyword in short text reads strong

    return ExpressionPayload(
        expression=EXPRESSION_MAP[category],
        weight=round(weight, 3),
        duration_ms=2500,
        source="keyword_v1",
        context={
            "category": category,
            "hits": hits,
            "hit_count": hit_count,
            "total_words": total_words,
        },
    )
