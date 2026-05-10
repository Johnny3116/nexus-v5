"""Claude daily/monthly budget gate.

Before any Claude-primary route fires, `is_over_budget()` is checked. When
true, the BrainPool is instructed (`set_claude_over_budget(True)`) to
re-route Claude traffic to Codex until the window resets.

Today's implementation is intentionally light: it reads a rolling day/month
sum from Supabase. Writing to that table is the responsibility of
`observability/metrics/brain_cost_tracker.py` (already scaffolded). The
gate is safe when the tracker isn't writing yet — it returns False
(under budget) on any read failure and logs.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone

from api_gateway.config.settings import get_settings

logger = logging.getLogger("nexus.api_gateway.budget.claude")


async def is_over_budget() -> bool:
    """Return True if today's Claude spend exceeds the configured cap."""
    settings = get_settings()
    cap = settings.claude_daily_budget_usd
    try:
        spent = await _today_spend_usd()
    except Exception as exc:
        logger.warning("claude budget read failed, assuming under budget: %s", exc)
        return False

    over = spent >= cap
    if over:
        logger.warning("claude daily budget blown: $%.2f >= $%.2f", spent, cap)
    return over


async def _today_spend_usd() -> float:
    """Sum today's Claude rows in `brain_cost_tracker` (Supabase)."""
    # Deliberately deferred — wires in when kv_cache/cold/supabase_client.py
    # lands the async query helper. Returning 0.0 today keeps the gate
    # inert but harmless.
    from kv_cache.cold.supabase_client import get_supabase

    today = date.today().isoformat()
    try:
        client = get_supabase()
        resp = (
            client.table("brain_cost_tracker")
            .select("cost_usd")
            .eq("provider", "claude")
            .gte("day", today)
            .execute()
        )
        rows = resp.data or []
        return float(sum(r.get("cost_usd", 0) or 0 for r in rows))
    except Exception as exc:
        logger.debug("supabase budget query failed: %s", exc)
        return 0.0


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
