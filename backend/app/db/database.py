from __future__ import annotations

import asyncio
import logging
import os
from typing import AsyncGenerator

from fastapi import HTTPException, status
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.errors import PyMongoError

logger = logging.getLogger("bmtc.db")

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
DB_NAME = os.getenv("MONGO_DB_NAME", "bmtc")
# The driver's own default (30s) makes a missing/unreachable MongoDB hang
# the whole app for half a minute before failing. This project's core
# route-prediction feature needs no database at all (see init_db()'s
# docstring), so an absent Mongo instance should degrade the
# account/voting/ticketing/admin features quickly and clearly instead.
MONGO_SERVER_SELECTION_TIMEOUT_MS = int(os.getenv("MONGO_SERVER_SELECTION_TIMEOUT_MS", "3000"))

_client: AsyncIOMotorClient | None = None
_init_lock = asyncio.Lock()
_initialized = False
_unavailable = False  # set once we've confirmed Mongo can't be reached


def _get_client() -> AsyncIOMotorClient:
    global _client
    if not _client:
        _client = AsyncIOMotorClient(MONGO_URI, serverSelectionTimeoutMS=MONGO_SERVER_SELECTION_TIMEOUT_MS)
    return _client


async def init_db() -> None:
    """Set up MongoDB collections/indexes if MongoDB is reachable. Safe to call multiple times.

    IMPORTANT: the bus-route-prediction feature (BMTCBusPredictor) is
    CSV/in-memory only and needs no database whatsoever -- only the
    account, voting, ticketing, and admin/depot features use MongoDB.
    Previously, a missing MongoDB instance crashed (or, worse, hung for the
    driver's 30s default timeout and then crashed) the ENTIRE app at
    startup, taking the route predictor down with it even though it has no
    actual dependency on a database. Now: a failure here is caught and
    logged, and only the features that genuinely need MongoDB are
    affected (see get_db(), which returns a clear 503 for them) -- see
    main.py, which trains the predictor first, independent of this call's
    outcome.
    """
    global _initialized, _unavailable
    if _initialized:
        return
    async with _init_lock:
        if _initialized:
            return

        db = _get_client()[DB_NAME]
        try:
            await db.users.create_index("email", unique=True)
            await db.votes.create_index([("current_stop", 1), ("destination", 1)])
            await db.votes.create_index([("created_at", -1)])
            await db.votes.create_index("user_id")
            await db.predictions.create_index("user_id")
            await db.favorites.create_index(
                [("user_id", 1), ("current_stop", 1), ("destination", 1)], unique=True
            )
            await db.notifications.create_index([("user_id", 1), ("is_read", 1)])
            await db.bus_positions.create_index("bus_number")
            await db.crowd_reports.create_index([("route_number", 1), ("created_at", -1)])
            await db.crowd_reports.create_index([("user_id", 1), ("route_number", 1), ("created_at", -1)])
            await db.service_alerts.create_index([("status", 1), ("created_at", -1)])
            await db.service_alerts.create_index("affected_routes")
            await db.service_alerts.create_index("affected_stops")
            await db.trip_shares.create_index("code", unique=True)
            # TTL index: MongoDB automatically deletes documents once
            # expires_at is in the past, so an expired share doesn't just
            # stop being returned by get_shared_trip -- it's actually gone.
            await db.trip_shares.create_index("expires_at", expireAfterSeconds=0)
            await db.usage_events.create_index([("event_type", 1), ("created_at", -1)])
            # Raw event rows aren't kept indefinitely -- 90 days is enough
            # for a pilot period plus review time, consistent with the
            # retention principles set out in Phase 1's data governance
            # document (notifications: 90 days there too).
            await db.usage_events.create_index("created_at", expireAfterSeconds=90 * 24 * 60 * 60)
            # ── conductor waybills and onboard ticketing ──
            await db.waybills.create_index([("conductor_id", 1), ("status", 1)])
            await db.waybills.create_index([("depot", 1), ("duty_date", -1)])
            await db.waybills.create_index("waybill_id", unique=True)
            # THE index that makes offline ticketing safe. The device replays
            # its queue until acknowledged; without this, a retried batch is
            # counted again and the day's revenue is overstated.
            await db.conductor_tickets.create_index(
                [("waybill_id", 1), ("client_ticket_uuid", 1)], unique=True
            )
            await db.conductor_tickets.create_index([("waybill_id", 1)])
            await db.travel_passes.create_index("pass_id", unique=True)
            await db.travel_passes.create_index([("status", 1), ("expires_at", 1)])
            # Audit entries are NOT given a TTL, unlike usage_events above.
            # These record who moved money; a retention window on them would
            # be a retention window on accountability.
            await db.audit_events.create_index([("created_at", -1)])
            await db.audit_events.create_index([("action", 1), ("created_at", -1)])
        except PyMongoError as exc:
            _unavailable = True
            logger.warning(
                "MongoDB is not reachable at %s (%s). Account, voting, ticketing, and "
                "admin/depot features will return 503 until it is available. Route "
                "prediction is unaffected -- it does not use a database.",
                MONGO_URI, exc,
            )
            return

        _initialized = True
        logger.info("MongoDB initialized at %s database %s", MONGO_URI, DB_NAME)


def db_available() -> bool:
    """True once init_db() has confirmed MongoDB is reachable and set up."""
    return _initialized and not _unavailable


async def get_db() -> AsyncGenerator:
    """Yield a MongoDB database handle for routes that need one.

    Raises a clear 503 (instead of letting a request hang on a connection
    attempt, or surface an opaque timeout error) if MongoDB was never
    reachable at startup.
    """
    if _unavailable:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "This feature requires a database connection, which is currently "
                "unavailable. Bus route prediction does not require a database and "
                "is unaffected."
            ),
        )
    yield _get_client()[DB_NAME]


async def close_db() -> None:
    """Close MongoDB connection pool."""
    global _client, _initialized, _unavailable
    if _client:
        _client.close()
        _client = None
    _initialized = False
    _unavailable = False
    logger.info("MongoDB connection closed")