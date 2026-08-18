from __future__ import annotations

from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from pymongo.errors import DuplicateKeyError
from bson import ObjectId
from bson.errors import InvalidId

from app.auth.auth import UserRole, get_current_user, require_role
from app.services.tracking_service import bus_simulator
from app.services.vehicle_service import (
    describe_vehicles,
    estimate_eta,
    ingest_key_matches,
    vehicle_trip_status,
)
from app.tracking.base import VehicleObservation
from app.tracking.ingest import vehicle_ingest
from app.tracking.store import vehicle_store

router = APIRouter(prefix="/tracking", tags=["tracking"])
avl_router = APIRouter(prefix="/avl", tags=["avl"])


class FavoriteRequest(BaseModel):
    current_stop: str = Field(..., min_length=1, max_length=150)
    destination: str = Field(..., min_length=1, max_length=150)
    label: str | None = Field(None, max_length=100)


def _get_distance_service(request: Request):
    predictor = request.app.state.predictor
    return getattr(predictor, "distance_service", None)


@router.get("/buses")
async def get_all_buses(request: Request, route: str = Query("", max_length=50)) -> dict:
    """Current vehicle positions, from whichever feed is configured.

    Served out of the observation store the ingest loop maintains, so the
    payload is identical in shape whether it came from the simulator or a real
    BMTC feed -- and carries `is_live` either way, so no client can render
    simulated positions as live tracking by omission.

    Positions older than AVL_STALE_SECONDS are withheld rather than shown. A
    stalled feed keeps returning its last payload, and a map of buses frozen
    mid-road is worse than an empty one: riders wait for them.
    """
    if not vehicle_store.fresh() and vehicle_ingest.feed is not None:
        # First request before the loop's first tick, or after a restart.
        await vehicle_ingest.poll_once()

    payload = describe_vehicles(route.strip() or None, predictor=request.app.state.predictor)
    # `mode` retained for the existing frontend, which keys off it.
    payload["mode"] = "live" if payload["is_live"] else "simulated"
    return payload


@router.post("/tick")
async def tick_simulation(
    request: Request,
    user: dict = Depends(require_role(UserRole.ADMIN, UserRole.DEPOT_MANAGER)),
) -> dict:
    """Force the simulation forward by one step (admin/depot only).

    Normal clients never need this -- GET /tracking/buses self-advances. It is
    kept only as a manual override for demos, and gated because it mutates
    state shared by every viewer and rewrites the bus_positions collection.
    """
    if not bus_simulator._active_buses:
        predictor = request.app.state.predictor
        dist_svc = _get_distance_service(request)
        await bus_simulator.initialize_buses(predictor.routes, dist_svc)

    updated_bus_list = await bus_simulator.tick()
    return {"updated": len(updated_bus_list), "buses": updated_bus_list}


@router.get("/bus/{bus_number}")
async def get_bus(bus_number: str, request: Request) -> dict:
    """Position, provenance and schedule adherence for one route's vehicles."""
    if not vehicle_store.fresh() and vehicle_ingest.feed is not None:
        await vehicle_ingest.poll_once()

    observations = vehicle_store.for_route(bus_number)
    if not observations:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No current position for bus {bus_number}. "
                + vehicle_ingest.source_report()["description"]
            ),
        )

    predictor = request.app.state.predictor
    now = datetime.now(timezone.utc)
    now_minute = now.hour * 60 + now.minute

    buses = []
    for observation in observations:
        payload = observation.as_dict()
        # Schedule adherence is the thing real positions unlock and no consumer
        # app can produce, because none of them hold the timetable. It is null
        # rather than fabricated when the vehicle cannot be placed on a trip.
        payload["schedule"] = vehicle_trip_status(predictor, observation, now_minute)
        buses.append(payload)
    return {"buses": buses, "count": len(buses), "is_live": observations[0].is_live}


@router.get("/eta")
async def get_eta(
    request: Request,
    bus_number: str = Query(..., max_length=50),
    target_stop: str = Query(..., max_length=150),
) -> dict:
    """When the next vehicle on this route reaches this stop.

    Measured along the route rather than straight-line, and returned as a range
    with a confidence label saying which speed source it rests on. A rider told
    "8-14 min, low confidence" can plan; one told "11 min" by a number that came
    from a hard-coded default cannot.
    """
    if not vehicle_store.fresh() and vehicle_ingest.feed is not None:
        await vehicle_ingest.poll_once()

    result = estimate_eta(request.app.state.predictor, bus_number, target_stop)
    if result["status"] == "unknown_route":
        raise HTTPException(status_code=404, detail=result["note"])
    return result


@router.get("/favorites")
async def get_favorites(user: dict = Depends(get_current_user)) -> dict:
    """Get user's favorite routes."""
    from app.db.database import get_db

    formatted_rows = []
    async for db in get_db():
        cursor = db.favorites.find({"user_id": user["sub"]}).sort("created_at", -1)
        rows = await cursor.to_list(None)

        for r in rows:
            formatted_rows.append({
                "id": str(r["_id"]),
                "current_stop": r["current_stop"],
                "destination": r["destination"],
                "label": r.get("label"),
                "created_at": r.get("created_at")
            })
    return {"favorites": formatted_rows}


@router.post("/favorites")
async def add_favorite(
    payload: FavoriteRequest,
    user: dict = Depends(get_current_user),
) -> dict:
    """Add a favorite route."""
    from app.db.database import get_db

    async for db in get_db():
        try:
            doc = {
                "user_id": user["sub"],
                "current_stop": payload.current_stop,
                "destination": payload.destination,
                "label": payload.label,
                "created_at": datetime.now(timezone.utc)
            }
            res = await db.favorites.insert_one(doc)
            return {"id": str(res.inserted_id), "message": "Favorite added"}
        except DuplicateKeyError:
            raise HTTPException(status_code=409, detail="Already in favorites")


@router.delete("/favorites/{fav_id}")
async def remove_favorite(fav_id: str, user: dict = Depends(get_current_user)) -> dict:
    """Remove a favorite route."""
    from app.db.database import get_db

    try:
        oid = ObjectId(fav_id)
    except InvalidId:
        raise HTTPException(status_code=400, detail="Invalid id.")

    async for db in get_db():
        await db.favorites.delete_one({"_id": oid, "user_id": user["sub"]})
    return {"message": "Favorite removed"}


# ── AVL ingest ──────────────────────────────────────────────────────────────

class AvlObservationIn(BaseModel):
    """One vehicle sighting pushed by an operator's ITS, or by a driver app."""

    vehicle_id: str = Field(..., min_length=1, max_length=64)
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)
    recorded_at: datetime | None = Field(
        None,
        description=(
            "When the DEVICE observed this. Omit only if genuinely unknown -- a "
            "server-stamped time makes a stalled feed look permanently fresh and "
            "defeats staleness detection entirely."
        ),
    )
    route_number: str | None = Field(None, max_length=50)
    direction_id: int | None = Field(None, ge=0, le=1)
    bearing: float | None = Field(None, ge=0, le=360)
    speed_kmph: float | None = Field(None, ge=0, le=150)
    occupancy_pct: float | None = Field(None, ge=0, le=100)


class AvlIngestRequest(BaseModel):
    observations: list[AvlObservationIn] = Field(..., min_length=1, max_length=2000)


@avl_router.post("/ingest")
async def ingest_positions(payload: AvlIngestRequest, request: Request) -> dict:
    """Accept pushed vehicle positions.

    Authenticated by a shared secret in X-AVL-Key rather than a user session:
    the caller is a fleet system, not a person, and it has no account. An unset
    AVL_INGEST_KEY refuses everything -- an open ingest endpoint would let
    anyone inject bus positions onto the map, which is a more consequential
    kind of fake data than anything else in this codebase.

    Merges rather than replaces, keeping the newest fix per vehicle, because
    each push carries only the vehicles that reported and an out-of-order
    arrival must not overwrite a newer position.
    """
    if not ingest_key_matches(request.headers.get("X-AVL-Key", "")):
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing X-AVL-Key. Set AVL_INGEST_KEY to enable this endpoint.",
        )

    now = datetime.now(timezone.utc)
    observations = [
        VehicleObservation(
            vehicle_id=item.vehicle_id,
            lat=item.lat,
            lon=item.lon,
            recorded_at=item.recorded_at or now,
            route_number=item.route_number,
            direction_id=item.direction_id,
            bearing=item.bearing,
            speed_kmph=item.speed_kmph,
            occupancy_pct=item.occupancy_pct,
            source="push",
            is_live=True,
        )
        for item in payload.observations
    ]
    vehicle_store.apply(observations)
    return {
        "status": "ok",
        "accepted": len(observations),
        "vehicles_fresh": len(vehicle_store.fresh()),
    }
