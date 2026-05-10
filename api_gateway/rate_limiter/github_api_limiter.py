"""GitHub API rate limiter — Phase 8 stub.

GitHub enforces 5000 req/hr authenticated / 60 req/hr unauth. When Scout
(Phase 8) starts crawling, this module will track `X-RateLimit-Remaining`
and back off proactively.

Exists today as a stub so `api_gateway/main.py` can import it without
ceremony when Scout lands.
"""

from __future__ import annotations


class GitHubLimiter:
    def __init__(self, token: str = "", min_remaining: int = 50) -> None:
        self.token = token
        self.min_remaining = min_remaining

    async def wait(self) -> None:
        """Block until it is safe to make a GitHub call. Phase 8."""
        raise NotImplementedError("github_api_limiter arrives with Phase 8 (Scout)")

    def record(self, response) -> None:
        """Update remaining quota from response headers. Phase 8."""
        raise NotImplementedError("github_api_limiter arrives with Phase 8 (Scout)")
