from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from bson import ObjectId
from bson.errors import InvalidId

from app.db.database import get_db

logger = logging.getLogger("bmtc.services.safety")

# How long a shared trip stays viewable. A trusted contact checking on
# someone hours after a short bus ride has no real need to keep seeing it;
# expiring it also means an old share link doesn't linger indefinitely as
# a stale, forgotten source of someone's past travel plans.
TRIP_SHARE_EXPIRY_HOURS = 6

MAX_TRUSTED_CONTACTS = 5


async def save_trusted_contacts(user_id: str, contacts: list[dict[str, str]]) -> list[dict[str, str]]:
    """Save a user's own trusted contacts (name + phone number), entirely
    under their control -- these are used for real tel:/sms: links the
    user's own device opens (see the frontend), never auto-dialed or
    auto-messaged by the backend on the user's behalf."""
    if len(contacts) > MAX_TRUSTED_CONTACTS:
        raise ValueError(f"Maximum {MAX_TRUSTED_CONTACTS} trusted contacts allowed.")
    cleaned = []
    for contact in contacts:
        name = str(contact.get("name", "")).strip()
        phone = str(contact.get("phone", "")).strip()
        if not name or not phone:
            raise ValueError("Each contact needs a name and phone number.")
        cleaned.append({"name": name[:100], "phone": phone[:20]})

    async for db in get_db():
        await db.users.update_one(
            {"_id": ObjectId(user_id)},
            {"$set": {"trusted_contacts": cleaned}},
        )
        return cleaned
    return cleaned


async def get_trusted_contacts(user_id: str) -> list[dict[str, str]]:
    async for db in get_db():
        user = await db.users.find_one({"_id": ObjectId(user_id)})
        return (user or {}).get("trusted_contacts", [])
    return []


async def create_trip_share(
    user_id: str,
    current_stop: str,
    destination: str,
    bus_number: str | None,
    matched_current_stop: str | None,
    matched_destination: str | None,
) -> dict[str, Any]:
    """Create a real, viewable record of a planned trip's details, for a
    trusted contact to check.

    IMPORTANT, and this is the whole reason for this docstring: this
    shares the PLANNED journey (route, buses, stops) that predict()
    already returned -- not live location. There is no real GPS feed in
    this project (see tracking_service.py and the Live Tracking feature,
    which is a disclosed simulation), so a "share my live location" claim
    here would be false and could give a trusted contact a dangerously
    wrong picture of where someone actually is. Presenting planned-trip
    info as anything more than that is exactly the kind of overclaim this
    whole project's fixes have been about avoiding -- doubly so where it
    could affect someone's actual physical safety, not just a wrong bus
    number.
    """
    code = secrets.token_urlsafe(8)
    async for db in get_db():
        now = datetime.now(timezone.utc)
        doc = {
            "code": code,
            "user_id": user_id,
            "current_stop": current_stop,
            "destination": destination,
            "matched_current_stop": matched_current_stop,
            "matched_destination": matched_destination,
            "bus_number": bus_number,
            "created_at": now,
            "expires_at": now + timedelta(hours=TRIP_SHARE_EXPIRY_HOURS),
        }
        await db.trip_shares.insert_one(doc)
        logger.info("Trip share created for user %s: code=%s", user_id, code)
        return {
            "code": code,
            "expires_at": doc["expires_at"].isoformat(),
            "expiry_hours": TRIP_SHARE_EXPIRY_HOURS,
        }
    return {}


async def get_shared_trip(code: str) -> dict[str, Any] | None:
    """Public lookup for a trusted contact viewing a shared trip. Returns
    None for an unknown or expired code -- an expired share should look
    exactly like one that never existed, not leak that it once did."""
    async for db in get_db():
        doc = await db.trip_shares.find_one({"code": code})
        if not doc:
            return None
        expires_at = doc["expires_at"]
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at < datetime.now(timezone.utc):
            return None
        return {
            "current_stop": doc.get("matched_current_stop") or doc["current_stop"],
            "destination": doc.get("matched_destination") or doc["destination"],
            "bus_number": doc.get("bus_number"),
            "shared_at": doc["created_at"].isoformat(),
            "expires_at": doc["expires_at"].isoformat(),
            "note": (
                "This shows the planned trip only, not a live location -- "
                "this app does not have real-time GPS tracking."
            ),
        }
    return None