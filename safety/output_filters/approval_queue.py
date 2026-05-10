"""nexus-tools — Approval Queue

Safety gate for DESTRUCTIVE and CRITICAL skill actions triggered by automation.

When a skill requires approval:
    1. Write item to Supabase `approval_queue` table (task details, reason, source)
    2. Send Discord notification: "Nexus wants to [action]. Approve? React ✅ or ❌"
    3. Poll for approval status (Discord reaction or direct API call)
    4. If approved → execute via SkillManager
    5. If denied or timeout (1 hour) → log denial, do not execute

Table schema (Supabase `approval_queue`):
    id          uuid PK
    skill_name  text
    action      text
    params      jsonb
    source      text        (TaskSource value)
    request_id  text
    reason      text
    status      text        pending | approved | denied | expired
    created_at  timestamptz
    resolved_at timestamptz
    resolved_by text
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from safety.output_filters.safety_tier_gate import TaskSource

logger = logging.getLogger("nexus.tools.approval_queue")

APPROVAL_TIMEOUT_SECONDS = 3600  # 1 hour
TABLE = "approval_queue"


class ApprovalQueue:
    """Manages the pending approval queue for destructive skill actions.

    Args:
        db: SupabaseClient instance. If None, queue operates in memory-only
            mode (for testing/development without Supabase).
    """

    def __init__(self, db=None) -> None:
        self._db = db
        self._memory: dict[str, dict] = {}  # Fallback for no-DB mode

    # ------------------------------------------------------------------
    # Enqueueing
    # ------------------------------------------------------------------

    async def enqueue(
        self,
        skill_name: str,
        action: str,
        params: dict[str, Any],
        source: TaskSource,
        request_id: Optional[str] = None,
        reason: str = "",
    ) -> str:
        """Add an action to the approval queue.

        Returns:
            The approval item ID (UUID string).
        """
        item_id = str(uuid.uuid4())
        item = {
            "id": item_id,
            "skill_name": skill_name,
            "action": action,
            "params": params,
            "source": source.value,
            "request_id": request_id or "",
            "reason": reason or f"Automated action requires approval: {skill_name}.{action}",
            "status": "pending",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "resolved_at": None,
            "resolved_by": None,
        }

        # Persist to Supabase
        if self._db is not None:
            try:
                self._db.table(TABLE).insert(item).execute()
            except Exception as exc:
                logger.error("Failed to persist approval item to Supabase: %s — using memory", exc)
                self._memory[item_id] = item
        else:
            self._memory[item_id] = item

        logger.info(
            "Approval queued: id=%s skill=%s.%s source=%s",
            item_id, skill_name, action, source.value,
        )

        # Send Discord notification
        await self._notify_discord(item)

        return item_id

    # ------------------------------------------------------------------
    # Resolution
    # ------------------------------------------------------------------

    async def approve(self, item_id: str, approved_by: str = "unknown") -> bool:
        """Mark an item as approved.

        Returns True if the item was found and updated, False otherwise.
        """
        return await self._resolve(item_id, "approved", approved_by)

    async def deny(self, item_id: str, denied_by: str = "unknown") -> bool:
        """Mark an item as denied.

        Returns True if the item was found and updated, False otherwise.
        """
        return await self._resolve(item_id, "denied", denied_by)

    async def _resolve(self, item_id: str, status: str, resolved_by: str) -> bool:
        update = {
            "status": status,
            "resolved_at": datetime.now(timezone.utc).isoformat(),
            "resolved_by": resolved_by,
        }

        if self._db is not None:
            try:
                result = (
                    self._db.table(TABLE)
                    .update(update)
                    .eq("id", item_id)
                    .execute()
                )
                if result.data:
                    logger.info("Approval item %s → %s by %s", item_id, status, resolved_by)
                    return True
                logger.warning("Approval item %s not found in Supabase", item_id)
            except Exception as exc:
                logger.error("Failed to update approval item %s: %s", item_id, exc)

        # Memory fallback
        if item_id in self._memory:
            self._memory[item_id].update(update)
            logger.info("Approval item %s → %s (memory mode)", item_id, status)
            return True

        return False

    # ------------------------------------------------------------------
    # Inspection
    # ------------------------------------------------------------------

    async def get_status(self, item_id: str) -> Optional[dict]:
        """Get the current status of an approval item."""
        if self._db is not None:
            try:
                result = (
                    self._db.table(TABLE).select("*").eq("id", item_id).execute()
                )
                if result.data:
                    return result.data[0]
            except Exception as exc:
                logger.error("Failed to get approval item %s: %s", item_id, exc)

        return self._memory.get(item_id)

    async def list_pending(self) -> list[dict]:
        """List all items with status=pending."""
        if self._db is not None:
            try:
                result = (
                    self._db.table(TABLE)
                    .select("*")
                    .eq("status", "pending")
                    .order("created_at", desc=True)
                    .execute()
                )
                return result.data or []
            except Exception as exc:
                logger.error("Failed to list pending approvals: %s", exc)

        return [v for v in self._memory.values() if v.get("status") == "pending"]

    async def expire_old(self) -> int:
        """Mark timed-out pending items as expired. Returns count expired."""
        now = datetime.now(timezone.utc)
        expired = 0

        pending = await self.list_pending()
        for item in pending:
            created_str = item.get("created_at", "")
            if not created_str:
                continue
            try:
                created = datetime.fromisoformat(created_str.replace("Z", "+00:00"))
                age_seconds = (now - created).total_seconds()
                if age_seconds > APPROVAL_TIMEOUT_SECONDS:
                    await self._resolve(item["id"], "expired", "system")
                    expired += 1
                    logger.info("Approval item %s expired (age=%.0fs)", item["id"], age_seconds)
            except Exception:
                pass

        return expired

    # ------------------------------------------------------------------
    # Notification
    # ------------------------------------------------------------------

    async def _notify_discord(self, item: dict) -> None:
        """Send Discord notification asking for approval."""
        try:
            from observability.alerting.discord_notifier import send_alert, Alert, Severity
            await send_alert(Alert(
                severity=Severity.WARN,
                title="Action requires approval",
                detail=f"`{item['skill_name']}.{item['action']}`\nSource: `{item['source']}`\n{item['reason']}",
                source="approval_queue",
                fields={"ID": f"`{item['id']}`", "Expires": "1 hour"},
            ))
        except Exception as exc:
            logger.warning("Failed to send approval notification: %s", exc)
