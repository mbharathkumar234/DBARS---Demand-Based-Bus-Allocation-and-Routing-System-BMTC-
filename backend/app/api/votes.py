from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.auth.auth import UserRole, get_current_user, require_role
from app.services.vote_service import get_pair_demand, get_vote_aggregation, submit_vote

router = APIRouter(prefix="/votes", tags=["votes"])


class VoteRequest(BaseModel):
    current_stop: str = Field(..., min_length=2, max_length=120)
    destination: str = Field(..., min_length=2, max_length=120)
    time_preference: str = Field("any", pattern="^(any|morning_peak|afternoon|evening_peak|night)$")


@router.post("")
async def create_vote(payload: VoteRequest, request: Request, user: dict = Depends(get_current_user)) -> dict:
    """Record a new vote from a commuter."""
    # pull the ip address so we can do some basic anti-spam filtering later
    client_ip = request.client.host if request.client else None
    
    vote_record = await submit_vote(
        user_id=user["sub"],
        current_stop=payload.current_stop.strip(),
        destination=payload.destination.strip(),
        time_preference=payload.time_preference,
        ip_address=client_ip,
    )
    return vote_record


@router.get("/my")
async def my_votes(
    user: dict = Depends(get_current_user),
    limit: int = Query(20, ge=1, le=100),
) -> dict:
    """Fetch the logged-in user's recent voting activity."""
    from app.db.database import get_db

    user_votes = []
    # we need to grab a fresh db connection to query the votes collection
    async for db in get_db():
        cursor = db.votes.find({"user_id": user["sub"]}).sort("created_at", -1).limit(limit)
        raw_votes = await cursor.to_list(None)
        
        for vote_item in raw_votes:
            user_votes.append({
                "id": str(vote_item["_id"]),
                "current_stop": vote_item["current_stop"],
                "destination": vote_item["destination"],
                "time_preference": vote_item.get("time_preference"),
                "created_at": vote_item.get("created_at"),
                "is_flagged": vote_item.get("is_flagged")
            })

    return {"votes": user_votes}


def _allocated_bus(prediction: dict) -> dict | None:
    """Reshape a predict() result into the one journey allocated to this pair.

    Everything here is copied from what the prediction engine returned; no
    field is computed or embellished on the way out. If the engine found
    nothing, this returns None and the endpoint says so, rather than naming a
    bus that does not serve these two stops.
    """
    best = prediction.get("best_match")
    if not best:
        return None

    legs = best.get("legs") or []
    return {
        # The bus to board now. On a transfer journey this is the FIRST bus,
        # never the whole chain collapsed into one number -- same rule
        # predictor.predict() applies for exactly the same reason.
        "bus_number": best.get("bus_number"),
        "bus_chain": best.get("bus_chain") or best.get("bus_number"),
        "transfers": best.get("transfers", 0),
        "route_name": best.get("route_name"),
        "board_at": best.get("matched_current_stop"),
        "alight_at": best.get("matched_destination"),
        "transfer_stops": best.get("transfer_stops", []),
        "summary": best.get("summary"),
        "stops_on_journey": best.get("stop_span"),
        "distance_km": best.get("distance_km"),
        "duration_minutes": best.get("duration_minutes"),
        "confidence": best.get("confidence"),
        "trips_per_day": best.get("trip_count"),
        "first_departures": best.get("first_trips", []),
        "metro_interchange": best.get("metro_interchange"),
        "legs": [
            {
                "bus_number": leg.get("bus_number"),
                "from_stop": leg.get("from_stop"),
                "to_stop": leg.get("to_stop"),
                "trips_per_day": leg.get("trip_count"),
                "first_departures": leg.get("first_trips", []),
            }
            for leg in legs
        ],
    }


def _other_options(prediction: dict, limit: int = 3) -> list[dict]:
    """The runner-up journeys, so the allocated one is a choice and not a decree."""
    options = []
    for suggestion in (prediction.get("alternatives") or [])[1 : limit + 1]:
        legs = suggestion.get("legs") or []
        if not legs:
            continue
        options.append({
            "bus_chain": suggestion.get("bus_chain"),
            "transfers": suggestion.get("transfers", 0),
            "board_at": legs[0].get("from_stop"),
            "alight_at": legs[-1].get("to_stop"),
            "total_stops": suggestion.get("total_stops"),
            "total_distance_km": suggestion.get("total_distance_km"),
        })
    return options


def _depot_review(bus_numbers: set[str]) -> dict | None:
    """Has a depot manager actually looked at this route on the back of the votes?

    DEPLOYED_BUSES records acknowledgements from POST /depot/deploy-bus and
    nothing more -- no bus is dispatched anywhere by this app, because no real
    fleet system is wired to it (see that endpoint's docstring). So this
    reports a review, in the words that endpoint itself stores, and the panel
    that shows it must not upgrade that into a claim that a bus was sent.
    """
    from app.api.routes import DEPLOYED_BUSES

    matches = [entry for entry in DEPLOYED_BUSES if entry.get("route_number") in bus_numbers]
    if not matches:
        return None
    latest = matches[-1]
    return {
        "route_number": latest.get("route_number"),
        "status": latest.get("status"),
        "note": latest.get("note"),
        "at": latest.get("timestamp"),
    }


@router.get("/allocation")
async def vote_allocation(
    request: Request,
    current_stop: str = Query(..., min_length=2, max_length=120),
    destination: str = Query(..., min_length=2, max_length=120),
    days: int = Query(30, ge=1, le=365),
    user: dict = Depends(get_current_user),
) -> dict:
    """Which bus actually serves the pair of stops this commuter just voted for.

    Closes the loop the vote page previously left open. A commuter could vote
    for an origin-destination pair and see nothing come back: the demand they
    generated was only ever visible on the depot dashboard, via
    /depot/dispatch-recommendations, which they have no access to. This is the
    commuter-facing half of that same pipeline -- the same prediction engine
    resolving the same pair to the same real bus -- plus what their own votes
    have added up to so far.

    The two halves degrade independently and on purpose. The bus comes from the
    timetable CSV loaded in-process, so it resolves whether or not MongoDB is
    reachable; the vote counts need MongoDB, and say so plainly when it is not
    there instead of reporting zero votes, which would read as "nobody voted".
    """
    from app.db.database import db_available

    predictor = request.app.state.predictor
    current_stop = current_stop.strip()
    destination = destination.strip()

    try:
        # A real graph search over the stop index, ~1s of CPU. Off the event
        # loop, or every other request queued behind it waits that long too.
        prediction = await asyncio.to_thread(predictor.predict, current_stop, destination, 4)
    except ValueError as exc:
        # Unresolvable stop name, or the two stops are the same place. The
        # commuter's own words are in the message, so pass it through.
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    allocated = _allocated_bus(prediction)
    bus_numbers = set()
    if allocated:
        bus_numbers = {leg["bus_number"] for leg in allocated["legs"]}
        bus_numbers.add(allocated["bus_number"])
        bus_numbers.discard(None)

    if db_available():
        demand = await get_pair_demand(current_stop, destination, days, user_id=user["sub"])
    else:
        demand = {
            "available": False,
            "period_days": days,
            "note": (
                "Vote counts need a database connection, which is currently unavailable. "
                "The bus below is unaffected -- it comes from the published timetable."
            ),
        }

    return {
        "query": {"current_stop": current_stop, "destination": destination},
        "allocated_bus": allocated,
        "other_options": _other_options(prediction),
        "demand": demand,
        "depot_review": _depot_review(bus_numbers) if bus_numbers else None,
        "source": (
            "Allocated from BMTC's published timetable (routes_cleaned.csv) by the same "
            "prediction engine that serves /predict. Scheduled service, not a live vehicle."
        ),
        "message": prediction.get("message"),
    }


@router.get("/aggregate")
async def vote_aggregate(
    current_stop: str | None = Query(None),
    destination: str | None = Query(None),
    days: int = Query(30, ge=1, le=365),
    user: dict = Depends(require_role(UserRole.ADMIN, UserRole.DEPOT_MANAGER)),
) -> dict:
    """Pull the aggregated demand data for the admin/depot dashboards."""
    aggregated_results = await get_vote_aggregation(current_stop, destination, days)
    return {"demand": aggregated_results, "period_days": days}
