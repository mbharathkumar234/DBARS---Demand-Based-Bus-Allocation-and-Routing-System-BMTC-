"""Audit log for actions that move money or change an operational record.

The codebase gates writes by role but records nothing about who performed them.
That was tolerable while every write was advisory -- a re-block someone
approved, a recommendation someone acknowledged. It stops being tolerable the
moment a waybill declares cash and a Shakti claim goes to the state.

Deliberately narrow. This is not request logging: it records the small set of
actions where "who did this, when, to what" is a question someone will
eventually need answered, and nothing else.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from app.db.database import db_available, get_db

logger = logging.getLogger("bmtc.services.audit")

VALID_ACTIONS = {
    "waybill.sign_on",
    "waybill.sign_off",
    "waybill.tickets_synced",
    "pass.issued",
    "pass.revoked",
}


async def record(
    action: str, actor_id: str, *, subject: str = "", metadata: dict[str, Any] | None = None
) -> None:
    """Write one audit entry.

    Failure here is logged and swallowed, exactly as analytics_service.py does:
    a conductor must not be blocked from signing off a shift because an audit
    write failed. The trade-off is deliberate and worth stating -- this is an
    accountability record, not a ledger, and the waybill itself remains the
    authoritative document.
    """
    if action not in VALID_ACTIONS:
        logger.warning("Ignoring unknown audit action: %r", action)
        return
    if not db_available():
        return
    try:
        async for db in get_db():
            await db.audit_events.insert_one({
                "action": action,
                "actor_id": actor_id,
                "subject": subject,
                "metadata": metadata or {},
                "created_at": datetime.now(timezone.utc),
            })
            return
    except Exception:
        logger.exception("Failed to record audit event %r by %s", action, actor_id)


async def recent(limit: int = 100, action: str = "") -> list[dict[str, Any]]:
    query = {"action": action} if action else {}
    async for db in get_db():
        cursor = db.audit_events.find(query).sort("created_at", -1).limit(limit)
        rows = []
        async for row in cursor:
            row.pop("_id", None)
            row["created_at"] = row["created_at"].isoformat()
            rows.append(row)
        return rows
    return []
