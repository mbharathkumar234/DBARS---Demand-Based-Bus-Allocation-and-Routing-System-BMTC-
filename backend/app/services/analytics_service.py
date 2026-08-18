from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from app.db.database import get_db, db_available

logger = logging.getLogger("bmtc.services.analytics")

# What this logs, deliberately: event type, channel, and route/stop names
# (not personal data -- a stop name isn't PII). What this does NOT log:
# IP addresses, device identifiers, or precise timestamps down to a level
# that could re-identify a specific trip to a specific person. This
# follows the same minimal-collection principle set out in Phase 1's data
# governance document -- a pilot needs to know HOW MUCH the product is
# used and BY WHICH CHANNEL, not a surveillance trail of who searched what.
VALID_EVENT_TYPES = {
    "predict_query",       # a real /predict call from the app
    "sms_query",            # a real query via the SMS/low-bandwidth channel
    "sms_low_confidence",   # SMS query that hit the confidence gate (Phase 4)
}


async def log_event(event_type: str, metadata: dict[str, Any] | None = None) -> None:
    """Record a real usage event for pilot measurement.

    Silently does nothing if MongoDB is unavailable -- exactly like every
    other non-core feature in this project (see database.py), logging
    usage must never be able to break the actual prediction request it's
    trying to measure. A dropped analytics event is an acceptable loss;
    a broken bus lookup is not.
    """
    if event_type not in VALID_EVENT_TYPES:
        logger.warning("Ignoring unknown event_type: %r", event_type)
        return
    if not db_available():
        return
    try:
        async for db in get_db():
            await db.usage_events.insert_one({
                "event_type": event_type,
                "metadata": metadata or {},
                "created_at": datetime.now(timezone.utc),
            })
            return
    except Exception:
        # Analytics must never be the reason a real user-facing request
        # fails -- log and move on.
        logger.exception("Failed to record usage event %r", event_type)


async def get_pilot_metrics(days: int = 30) -> dict[str, Any]:
    """Aggregate real, logged usage for a pilot report.

    Returns an honest "no_data" status with zeroed counts when nothing has
    been logged yet -- e.g. before a real pilot has actually started --
    rather than omitting fields or fabricating example numbers. A pilot
    report generated from this function is only ever describing what
    genuinely happened; it does not backfill or estimate.
    """
    if not db_available():
        return {"status": "unavailable", "note": "Database unavailable.", "period_days": days}

    async for db in get_db():
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

        total_events = await db.usage_events.count_documents({"created_at": {"$gte": cutoff}})
        if total_events == 0:
            return {
                "status": "no_data",
                "period_days": days,
                "note": (
                    f"No usage events recorded in the last {days} days. This is expected "
                    "before a real pilot has started -- this function reports what actually "
                    "happened, it does not estimate or project."
                ),
                "predict_queries": 0,
                "sms_queries": 0,
                "sms_low_confidence_rate": None,
                "crowd_reports": 0,
                "votes_cast": 0,
                "active_alerts_created": 0,
                "top_destinations": [],
            }

        by_type_cursor = db.usage_events.aggregate([
            {"$match": {"created_at": {"$gte": cutoff}}},
            {"$group": {"_id": "$event_type", "count": {"$sum": 1}}},
        ])
        by_type = {row["_id"]: row["count"] async for row in by_type_cursor}

        predict_queries = by_type.get("predict_query", 0)
        sms_queries = by_type.get("sms_query", 0)
        sms_low_confidence = by_type.get("sms_low_confidence", 0)

        # These collections already exist independently (Phases 2/3) --
        # no need for a separate event log for them, just count real rows.
        crowd_reports = await db.crowd_reports.count_documents({"created_at": {"$gte": cutoff}})
        votes_cast = await db.votes.count_documents({"created_at": {"$gte": cutoff}})
        alerts_created = await db.service_alerts.count_documents({"created_at": {"$gte": cutoff}})

        top_destinations_cursor = db.usage_events.aggregate([
            {"$match": {"created_at": {"$gte": cutoff}, "event_type": "predict_query", "metadata.matched": True}},
            {"$group": {"_id": "$metadata.matched_destination", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
            {"$limit": 10},
        ])
        top_destinations = [
            {"destination": row["_id"], "count": row["count"]}
            async for row in top_destinations_cursor if row["_id"]
        ]

        return {
            "status": "ok",
            "period_days": days,
            "predict_queries": predict_queries,
            "sms_queries": sms_queries,
            "sms_low_confidence_rate": (
                round(sms_low_confidence / sms_queries, 3) if sms_queries else None
            ),
            "crowd_reports": crowd_reports,
            "votes_cast": votes_cast,
            "active_alerts_created": alerts_created,
            "top_destinations": top_destinations,
        }

    return {"status": "unavailable", "note": "Database unavailable.", "period_days": days}