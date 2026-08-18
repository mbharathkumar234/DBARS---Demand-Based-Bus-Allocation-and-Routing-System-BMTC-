from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any

from app.db.database import get_db

logger = logging.getLogger("bmtc.services.crowding")

# How recent a report has to be to count toward the current crowding
# signal. Bus occupancy changes trip to trip, not day to day -- a report
# from 3 hours ago says nothing about the current bus.
REPORT_FRESHNESS_MINUTES = 45
# Minimum gap before the same user can report the same route again, to
# limit one enthusiastic (or malicious) user from dominating the signal.
REPORT_COOLDOWN_MINUTES = 10


class CrowdingLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    FULL = "full"


_LEVEL_WEIGHT = {
    CrowdingLevel.LOW: 1,
    CrowdingLevel.MEDIUM: 2,
    CrowdingLevel.HIGH: 3,
    CrowdingLevel.FULL: 4,
}


async def submit_crowd_report(
    user_id: str,
    route_number: str,
    crowding_level: str,
    stop_name: str | None = None,
    bus_number: str | None = None,
) -> dict[str, Any]:
    """Record a real, commuter-submitted crowding report.

    This is deliberately separate from tracking_service.py's simulated
    per-bus occupancy_pct (random.uniform, clearly disclosed as part of
    the "Simulated / Demo Tracking" feature). That field answers "what
    would a live GPS+sensor feed look like"; this answers "what did a
    real person on a real bus actually report" -- the two must never be
    merged into one number, since doing so would launder a fabricated
    figure through a real one.
    """
    if crowding_level not in {level.value for level in CrowdingLevel}:
        raise ValueError(f"Invalid crowding_level: {crowding_level!r}")

    async for db in get_db():
        now = datetime.now(timezone.utc)
        cooldown_start = now - timedelta(minutes=REPORT_COOLDOWN_MINUTES)
        recent = await db.crowd_reports.find_one({
            "user_id": user_id,
            "route_number": route_number,
            "created_at": {"$gte": cooldown_start},
        })
        if recent:
            raise ValueError(
                f"Already reported this route in the last {REPORT_COOLDOWN_MINUTES} minutes."
            )

        doc = {
            "user_id": user_id,
            "route_number": route_number,
            "bus_number": bus_number,
            "stop_name": stop_name,
            "crowding_level": crowding_level,
            "created_at": now,
        }
        result = await db.crowd_reports.insert_one(doc)
        doc["_id"] = str(result.inserted_id)
        logger.info("Crowd report recorded for route %s: %s", route_number, crowding_level)
        return doc

    return {}


async def get_route_crowding(route_number: str) -> dict[str, Any]:
    """Aggregate real, recent crowd reports for a route.

    Returns an honest "not enough data" state when there are too few
    recent reports to say anything meaningful -- never a fabricated
    fallback value. Three is a deliberately low bar (this is a new
    feature with no existing report volume yet), revisit upward once
    real usage data shows what a reliable threshold looks like.
    """
    MIN_REPORTS_FOR_SIGNAL = 3

    async for db in get_db():
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=REPORT_FRESHNESS_MINUTES)
        cursor = db.crowd_reports.find({
            "route_number": route_number,
            "created_at": {"$gte": cutoff},
        }).sort("created_at", -1)
        reports = await cursor.to_list(length=200)

        if len(reports) < MIN_REPORTS_FOR_SIGNAL:
            return {
                "route_number": route_number,
                "status": "insufficient_data",
                "report_count": len(reports),
                "crowding_level": None,
                "note": (
                    f"Only {len(reports)} report(s) in the last {REPORT_FRESHNESS_MINUTES} "
                    f"minutes -- need at least {MIN_REPORTS_FOR_SIGNAL} for a reliable signal."
                ),
            }

        avg_weight = sum(_LEVEL_WEIGHT[CrowdingLevel(r["crowding_level"])] for r in reports) / len(reports)
        # Round to the nearest defined level rather than reporting a
        # fractional "2.4", which isn't a real crowding level anyone
        # reported.
        closest_level = min(_LEVEL_WEIGHT, key=lambda lvl: abs(_LEVEL_WEIGHT[lvl] - avg_weight))

        return {
            "route_number": route_number,
            "status": "ok",
            "report_count": len(reports),
            "crowding_level": closest_level.value,
            "most_recent_report_at": reports[0]["created_at"].isoformat(),
            "window_minutes": REPORT_FRESHNESS_MINUTES,
        }

    return {"route_number": route_number, "status": "unavailable", "report_count": 0, "crowding_level": None}