from __future__ import annotations

import logging
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from bson import ObjectId
from bson.errors import InvalidId
from pymongo import ReturnDocument

from app.db.database import get_db

logger = logging.getLogger("bmtc.services.alerts")


class AlertSeverity(str, Enum):
    INFO = "info"
    MODERATE = "moderate"
    SEVERE = "severe"


def _serialize_alert(doc: dict[str, Any]) -> dict[str, Any]:
    doc = dict(doc)
    doc["id"] = str(doc.pop("_id"))
    for field in ("created_at", "resolved_at"):
        if doc.get(field):
            doc[field] = doc[field].isoformat()
    return doc


async def create_alert(
    created_by_user_id: str,
    title: str,
    description: str,
    severity: str,
    affected_routes: list[str] | None = None,
    affected_stops: list[str] | None = None,
) -> dict[str, Any]:
    """Create a real service disruption alert.

    Deliberately a manually-created, moderated record -- not an automated
    feed. Bengaluru's most common real disruption causes (monsoon
    flooding, ad hoc road closures, VIP movement) generally aren't
    available anywhere as structured, machine-readable data, so a human
    (depot staff, admin) reporting what they know is the honest starting
    point, not a placeholder for something better. Restricted to
    admin/depot_manager roles at the API layer (see api/alerts.py) --
    unmoderated public alert creation would let anyone post a fake
    disruption.
    """
    if severity not in {s.value for s in AlertSeverity}:
        raise ValueError(f"Invalid severity: {severity!r}")
    if not title.strip() or not description.strip():
        raise ValueError("title and description are required")

    async for db in get_db():
        doc = {
            "title": title.strip(),
            "description": description.strip(),
            "severity": severity,
            "affected_routes": affected_routes or [],
            "affected_stops": affected_stops or [],
            "status": "active",
            "created_by": created_by_user_id,
            "created_at": datetime.now(timezone.utc),
            "resolved_at": None,
        }
        result = await db.service_alerts.insert_one(doc)
        doc["_id"] = result.inserted_id
        logger.info("Service alert created: %s (severity=%s)", title, severity)
        return _serialize_alert(doc)

    return {}


async def get_active_alerts(
    route_number: str | None = None,
    stop_name: str | None = None,
) -> list[dict[str, Any]]:
    """Return active alerts, optionally filtered to ones affecting a
    specific route or stop. An empty list is a valid, honest answer --
    "no known disruptions" -- not a sign anything is broken."""
    async for db in get_db():
        query: dict[str, Any] = {"status": "active"}
        if route_number:
            query["affected_routes"] = route_number
        if stop_name:
            query["affected_stops"] = stop_name
        cursor = db.service_alerts.find(query).sort("created_at", -1)
        alerts = await cursor.to_list(length=100)
        return [_serialize_alert(a) for a in alerts]

    return []


async def resolve_alert(alert_id: str, resolved_by_user_id: str) -> dict[str, Any] | None:
    """Mark an alert resolved. Returns None if the alert doesn't exist."""
    try:
        object_id = ObjectId(alert_id)
    except InvalidId:
        return None

    async for db in get_db():
        result = await db.service_alerts.find_one_and_update(
            {"_id": object_id, "status": "active"},
            {"$set": {
                "status": "resolved",
                "resolved_at": datetime.now(timezone.utc),
                "resolved_by": resolved_by_user_id,
            }},
            return_document=ReturnDocument.AFTER,
        )
        return _serialize_alert(result) if result else None

    return None