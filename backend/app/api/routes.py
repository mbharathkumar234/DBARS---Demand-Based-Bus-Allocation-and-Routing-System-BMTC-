from __future__ import annotations

import asyncio
from dataclasses import replace
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.core.config import settings
from app.ml.blocking import ScenarioChange, parse_clock
from app.models.schemas import (
    BlockingDecisionRequest,
    BlockingScenarioRequest,
    CrewScenarioRequest,
    DeployBusRequest,
    PredictRequest,
    TrainRequest,
)
from app.auth.auth import UserRole, get_current_user, require_role
from app.ml.crew import CrewParameters
from app.services.blocking_service import blocking_plan_service
from app.services.crew_service import crew_plan_service

import time

router = APIRouter()

DEPLOYED_BUSES: list[dict] = []
BLOCKING_DECISIONS: list[dict] = []


def rank_dispatch_recommendations(
    aggregated_votes: list[dict],
    predictor,
    *,
    days: int,
    limit: int = 10,
) -> list[dict]:
    """Turn raw vote-aggregation rows into ranked, real dispatch recommendations.

    Pulled out as its own function (rather than inlined in the endpoint
    below) specifically so it can be unit-tested against fixture vote data
    without needing a live MongoDB connection -- the endpoint itself is
    just this function plus the I/O around it.

    `aggregated_votes` is whatever get_vote_aggregation() returns: rows of
    {current_stop, destination, time_preference, vote_count, unique_voters,
    last_vote, flagged_count}, one row per (current_stop, destination,
    time_preference) combination. This collapses those into one entry per
    (current_stop, destination) pair, ranks by genuine vote count (votes
    minus ones the existing fraud detector already flagged), and resolves
    each surfaced pair to a REAL recommended bus via predictor.predict()
    -- never an invented route number.
    """
    by_pair: dict[tuple[str, str], dict] = {}
    for row in aggregated_votes:
        key = (row["current_stop"], row["destination"])
        genuine = max(0, row["vote_count"] - row.get("flagged_count", 0))
        entry = by_pair.setdefault(key, {"genuine_votes": 0, "unique_voters": 0, "last_vote": None})
        entry["genuine_votes"] += genuine
        entry["unique_voters"] = max(entry["unique_voters"], row.get("unique_voters", 0))
        last_vote = row.get("last_vote")
        if last_vote and (entry["last_vote"] is None or last_vote > entry["last_vote"]):
            entry["last_vote"] = last_vote

    ranked_pairs = sorted(
        ((pair, data) for pair, data in by_pair.items() if data["genuine_votes"] > 0),
        key=lambda item: item[1]["genuine_votes"],
        reverse=True,
    )[:limit]

    recommendations = []
    for (current_stop, destination), data in ranked_pairs:
        try:
            result = predictor.predict(current_stop, destination, limit=1)
        except ValueError:
            # Can't resolve a real bus for this OD pair (e.g. a stop name
            # that no longer matches anything) -- skip it rather than
            # invent one, same principle as everything else here.
            continue
        best = result.get("best_match")
        if not best:
            continue

        votes = data["genuine_votes"]
        surge_level = "HIGH" if votes >= 15 else "MEDIUM" if votes >= 5 else "LOW"

        recommendations.append({
            "route_number": best.get("bus_number"),
            "current_stop": best.get("matched_current_stop", current_stop),
            "destination": best.get("matched_destination", destination),
            "surge_level": surge_level,
            "genuine_vote_count": votes,
            "unique_voters": data["unique_voters"],
            "reason": f"{votes} commuter vote(s) from {data['unique_voters']} unique voter(s) in the last {days} days.",
            "last_vote_at": data["last_vote"].isoformat() if data["last_vote"] else None,
        })
    return recommendations


@router.get("/depot/dispatch-recommendations")
async def depot_dispatch_recommendations(
    request: Request,
    days: int = Query(14, ge=1, le=90),
    limit: int = Query(10, ge=1, le=50),
    user: dict = Depends(require_role(UserRole.ADMIN, UserRole.DEPOT_MANAGER)),
) -> dict:
    """Surface the routes with the strongest real, recent commuter demand signal.

    Previously this returned four fully invented recommendations (fake
    route numbers, fake depot names, fake "passenger surge counts", fake
    CO2 figures) that never changed regardless of any real activity, while
    the frontend told users they were "real-time... generated from high
    commuter route search & vote surges." Real demand data already exists
    in this project -- commuter votes recorded per origin-destination pair
    via POST /votes -- it just wasn't being used here. This aggregates
    that real vote data (see rank_dispatch_recommendations above) and
    resolves each high-demand pair to an actual bus using the real
    prediction engine.

    If MongoDB isn't reachable, or there simply isn't enough real vote
    data yet, this honestly returns an empty list with a note explaining
    why -- never fabricated content.
    """
    from app.db.database import db_available
    from app.services.vote_service import get_vote_aggregation

    predictor = get_predictor(request)

    if not db_available():
        return {
            "status": "unavailable",
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "period_days": days,
            "note": "Vote data requires a database connection, which is currently unavailable.",
            "total_recommendations": 0,
            "deployed_buses": DEPLOYED_BUSES,
            "recommendations": [],
        }

    aggregated = await get_vote_aggregation(days=days)
    recommendations = rank_dispatch_recommendations(aggregated, predictor, days=days, limit=limit)

    return {
        "status": "ok",
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "period_days": days,
        "total_recommendations": len(recommendations),
        "deployed_buses": DEPLOYED_BUSES,
        "recommendations": recommendations,
        "note": None if recommendations else f"No commuter votes recorded in the last {days} days yet.",
    }


@router.post("/depot/deploy-bus")
async def deploy_bus(
    payload: DeployBusRequest,
    user: dict = Depends(require_role(UserRole.DEPOT_MANAGER, UserRole.ADMIN)),
) -> dict:
    """Record that a depot manager has reviewed and actioned a recommendation.

    Previously this defaulted to a fictional depot ("Agara Depot") and
    returned a fabricated real-world status ("En Route to Corridor") for a
    bus that was never actually dispatched anywhere -- there is no real
    fleet/depot system wired into this app. This now only records what's
    actually true: someone acknowledged the recommendation, plus whatever
    note they added themselves.

    Also, found during the Phase 5 scale-readiness audit: this endpoint had
    no auth at all -- anyone could call it, unauthenticated, and mark any
    route as reviewed. Gated to depot_manager/admin, consistent with every
    other write action in this codebase that represents real depot/admin
    activity (crowding report submission requires login, alert creation
    requires depot_manager/admin, etc.).
    """
    acknowledgement = {
        "id": f"ACK-{int(time.time())}",
        "route_number": payload.route_number,
        "note": payload.note,
        "timestamp": time.strftime("%H:%M:%S"),
        "status": "Reviewed by depot manager",
        "reviewed_by": user["sub"],
    }
    DEPLOYED_BUSES.append(acknowledgement)
    return {
        "status": "success",
        "message": f"Marked Route {payload.route_number} as reviewed.",
        "acknowledgement": acknowledgement,
    }


@router.get("/depot/blocking-plan")
async def depot_blocking_plan(
    depot: str = Query("", description="Depot label to scope to; omit for the network summary"),
    user: dict = Depends(require_role(UserRole.ADMIN, UserRole.DEPOT_MANAGER)),
) -> dict:
    """Minimum fleet and dead kilometres, derived from BMTC's own timetable.

    Unlike /depot/dispatch-recommendations next door -- which needs MongoDB and
    honestly reports itself unavailable without it -- this endpoint reads only
    files that ship with the repo (the timetable CSV, the stop coordinates, the
    depot workbook). It therefore keeps working when the database does not,
    which matters because this is the panel meant to be shown to BMTC.

    The plan is computed once and cached in-process; it is a pure function of
    those files, so there is nothing to invalidate.
    """
    plan = await blocking_plan_service.get_plan()
    if not depot:
        return plan

    match = next((entry for entry in plan["depots"] if entry["key"] == depot), None)
    if match is None:
        raise HTTPException(status_code=404, detail=f"No blocking plan for depot '{depot}'.")
    return {
        **{key: value for key, value in plan.items() if key != "depots"},
        "depot": match,
        "depots": [
            {key: entry[key] for key in ("key", "label", "zone", "routes", "buses_released")}
            for entry in plan["depots"]
        ],
        "decisions": BLOCKING_DECISIONS,
    }


@router.post("/depot/blocking-decision")
async def depot_blocking_decision(
    payload: BlockingDecisionRequest,
    user: dict = Depends(require_role(UserRole.ADMIN, UserRole.DEPOT_MANAGER)),
) -> dict:
    """Record a controller's decision on one proposed re-block.

    Records only what actually happened -- that a named human accepted or
    rejected a proposal, and why. Nothing is dispatched: there is no real fleet
    system wired to this app, and claiming otherwise is exactly the kind of
    invented status this codebase has had to remove before (see deploy_bus
    above). Advisory by design, which is also what makes it deployable inside a
    transport corporation.
    """
    decision = {
        "id": f"BLK-{int(time.time() * 1000)}",
        "depot": payload.depot,
        "route_number": payload.route_number,
        "decision": payload.decision,
        "note": payload.note,
        "buses_released": payload.buses_released,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "reviewed_by": user["sub"],
    }
    BLOCKING_DECISIONS.append(decision)
    return {"status": "success", "decision": decision}


@router.post("/depot/blocking-scenario")
async def depot_blocking_scenario(
    payload: BlockingScenarioRequest,
    user: dict = Depends(require_role(UserRole.ADMIN, UserRole.DEPOT_MANAGER)),
) -> dict:
    """Answer "what would this frequency change actually cost?" before making it.

    This is the demand side of the loop the blocking plan opens up: the plan
    says what the current timetable needs, this says what a different one would
    need -- extra buses, which depot they come from, the dead-km consequence,
    and whether the result is still crew-feasible.

    Scoped to the affected route's depot, so it answers in well under a second
    rather than the ~17s a full network re-block costs.
    """
    start = parse_clock(payload.start_time)
    end = parse_clock(payload.end_time)
    if start is None or end is None:
        raise HTTPException(status_code=422, detail="Times must be HH:MM.")
    if end <= start:
        raise HTTPException(status_code=422, detail="end_time must be after start_time.")
    if payload.action == "set_headway" and not payload.headway_minutes:
        raise HTTPException(status_code=422, detail="set_headway needs headway_minutes.")
    if payload.action == "add_trips" and not payload.trips:
        raise HTTPException(status_code=422, detail="add_trips needs trips.")

    change = ScenarioChange(
        route_number=payload.route_number,
        action=payload.action,
        start_minute=start,
        end_minute=end,
        headway_minutes=payload.headway_minutes,
        trips=payload.trips,
        direction_id=payload.direction_id,
    )
    try:
        return await blocking_plan_service.run_scenario(change)
    except LookupError:
        suggestions = await blocking_plan_service.known_routes(payload.route_number, limit=8)
        raise HTTPException(
            status_code=404,
            detail={
                "message": f"No passenger route named '{payload.route_number}'.",
                "did_you_mean": suggestions,
            },
        )


@router.get("/depot/crew-plan")
async def depot_crew_plan(
    depot: str = Query("", description="Depot label to scope to; omit for the network summary"),
    user: dict = Depends(require_role(UserRole.ADMIN, UserRole.DEPOT_MANAGER)),
) -> dict:
    """How many crew duties the blocked timetable actually needs.

    The companion to /depot/blocking-plan, and the answer to the objection that
    plan invites: a re-block that saves buses by stretching each one across
    fourteen hours has not saved anything unless a roster can staff it. This
    cuts those blocks at legal relief opportunities and counts the duties.

    Same properties as the blocking plan next door -- no database, computed
    once and cached, a pure function of files that ship with the repo -- and
    the same honesty about its inputs: every crew rule here is an assumption,
    listed in `network.assumptions`, because BMTC's crew agreement is not in
    any published dataset.
    """
    plan = await crew_plan_service.get_plan()
    if not depot:
        return plan

    match = next((entry for entry in plan["depots"] if entry["key"] == depot), None)
    if match is None:
        raise HTTPException(status_code=404, detail=f"No crew plan for depot '{depot}'.")
    return {
        **{key: value for key, value in plan.items() if key != "depots"},
        "depot": match,
        "depots": [
            {key: entry[key] for key in ("key", "label", "zone", "routes", "duties")}
            for entry in plan["depots"]
        ],
    }


@router.post("/depot/crew-scenario")
async def depot_crew_scenario(
    payload: CrewScenarioRequest,
    user: dict = Depends(require_role(UserRole.ADMIN, UserRole.DEPOT_MANAGER)),
) -> dict:
    """Answer "what would this crew rule actually cost?" before agreeing to it.

    The mirror of /depot/blocking-scenario: that one varies the timetable and
    reports the fleet consequence, this one varies the crew agreement and
    reports the staffing consequence. Both are worth having in front of you at
    the same time, because the cheapest timetable and the cheapest roster are
    rarely the same schedule.
    """
    overrides = {
        field: value
        for field, value in payload.model_dump(exclude={"depot"}).items()
        if value is not None
    }
    parameters = replace(CrewParameters(), **overrides)

    if parameters.min_break_minutes > parameters.max_continuous_driving_minutes:
        raise HTTPException(
            status_code=422,
            detail="min_break_minutes cannot exceed max_continuous_driving_minutes.",
        )
    if parameters.max_working_minutes > parameters.max_spreadover_minutes:
        raise HTTPException(
            status_code=422,
            detail=(
                "max_working_minutes cannot exceed max_spreadover_minutes -- paid time is "
                "part of the spreadover, not additional to it."
            ),
        )

    try:
        return await crew_plan_service.run_scenario(parameters, depot=payload.depot.strip())
    except LookupError:
        known = await crew_plan_service.known_depots()
        raise HTTPException(
            status_code=404,
            detail={
                "message": f"No depot named '{payload.depot}'.",
                "did_you_mean": known[:8],
            },
        )


@router.get("/depot/routes")
async def depot_route_names(
    q: str = Query("", max_length=50, description="Prefix to match"),
    limit: int = Query(20, ge=1, le=100),
    user: dict = Depends(require_role(UserRole.ADMIN, UserRole.DEPOT_MANAGER)),
) -> dict:
    """Route names the scenario console can accept, for type-ahead."""
    return {"routes": await blocking_plan_service.known_routes(q, limit=limit)}


# The conductor pass verifier used to live here. It computed an HMAC it never
# consulted, decided validity from whether the pass id ended in "FAIL", returned
# a hardcoded passenger name, and padded its own response time so that
# "Offline Local Cryptographic Scan" would look measured. It has been replaced
# by real signed-token verification in app/services/pass_service.py, exposed at
# the same POST /conductor/verify-pass path from app/api/conductor.py.


@router.get("/tracking/source")
async def get_tracking_source() -> dict:
    """Report what is actually powering /tracking/buses right now.

    Derived from the running vehicle feed adapter, not from a stored label.
    That distinction is the whole history of this endpoint: it once reflected a
    mutable in-memory dict that an unauthenticated POST could flip to claim the
    data came from a "BMTC GTFS-RT Live Feed Stream" -- a real-sounding name
    for a government system this project did not connect to. The positions
    never changed when the label did. A status you can set to a false value on
    request is not a status.

    Now `is_live` comes from the adapter that produced the data, and the same
    flag gates the GTFS-realtime vehicle feed. Making it lie would mean
    configuring a different feed, which is the only honest way to change it.
    """
    from app.tracking.ingest import vehicle_ingest

    report = vehicle_ingest.source_report()
    return {
        "mode": "live" if report["is_live"] else "simulation",
        "label": f"{report['feed'] or 'none'} ({'live' if report['is_live'] else 'simulated'})",
        "provider": report["description"],
        **report,
    }



def get_predictor(request: Request):
    return request.app.state.predictor


@router.get("/health")
async def health(request: Request) -> dict:
    predictor = get_predictor(request)
    return {
        "status": "ok",
        "version": settings.app_version,
        "model_ready": predictor.ready,
        "dataset_rows": predictor.profile.get("rows", 0),
    }


@router.post("/train")
async def train(payload: TrainRequest, request: Request) -> dict:
    # force=true triggers a full retraining cycle -- confirmed to take
    # roughly 200 seconds of CPU time (see the benchmark this project's
    # earlier sessions measured directly). Without an auth gate, anyone
    # could repeatedly hit this endpoint with force=true and exhaust
    # server CPU; found during the Phase 5 scale-readiness audit. The
    # cheap, cached-metrics default (force=false) stays open to anyone,
    # since it has none of that cost.
    if payload.force:
        user = await get_current_user(request)
        if user.get("role") not in {UserRole.ADMIN.value, UserRole.DEPOT_MANAGER.value}:
            raise HTTPException(status_code=403, detail="force=true retraining requires admin or depot_manager.")
    predictor = get_predictor(request)
    return predictor.train(force=payload.force)


@router.post("/predict")
async def predict(payload: PredictRequest, request: Request) -> dict:
    from app.services.metro_service import metro_service
    from app.services.alerts_service import get_active_alerts
    from app.db.database import db_available
    from app.services.analytics_service import log_event

    predictor = get_predictor(request)
    try:
        # predict() is a synchronous graph search over the stop index. Measured
        # on this dataset it costs anywhere from 0.4s to ~26s for a hub-to-hub
        # pair ("KR Market" -> "Kempegowda Bus Station"). Calling it directly
        # from this `async def` pinned the event loop for that entire time: a
        # GET /health issued 0.5s into one such request did not even begin
        # executing until 26.3s in. That stalls every other user on the worker
        # and fails container/platform health checks.
        #
        # /votes/allocation next door already does exactly this, for exactly
        # this reason -- this endpoint is far busier and was missed.
        res = await asyncio.to_thread(
            predictor.predict, payload.current_stop, payload.destination, payload.limit
        )

        # Real usage event for pilot measurement (see analytics_service.py).
        # Fire-and-forget: never let logging affect the actual response.
        best_match = res.get("best_match") or {}
        await log_event("predict_query", {
            "matched": bool(res.get("best_match")),
            "transfers": best_match.get("transfers", 0),
            "matched_current_stop": best_match.get("matched_current_stop"),
            "matched_destination": best_match.get("matched_destination"),
        })
        
        # Calculate nearest metro station to destination bus stop
        dest_stop = payload.destination
        if isinstance(res, dict) and "best_match" in res and res["best_match"]:
            dest_stop = res["best_match"].get("matched_destination") or payload.destination
        
        nearest_stations = metro_service.find_nearest_stations(
            stop_name=dest_stop,
            limit=3,
            distance_service=predictor.distance_service,
        )
        
        if isinstance(res, dict):
            res["destination_nearest_metro"] = nearest_stations[0] if nearest_stations else None
            res["destination_nearest_metro_list"] = nearest_stations
            if res.get("best_match"):
                res["best_match"]["destination_nearest_metro"] = nearest_stations[0] if nearest_stations else None
                res["best_match"]["destination_nearest_metro_list"] = nearest_stations

        # Surface any real, active service disruption alerts affecting this
        # journey. Route prediction itself must never depend on MongoDB
        # (see database.py's docstrings), so this degrades to an empty list
        # rather than failing the whole request if it's unavailable --
        # exactly the same principle already applied to account/voting
        # features elsewhere in this project.
        res["active_alerts"] = []
        if isinstance(res, dict) and res.get("best_match") and db_available():
            best_match = res["best_match"]
            route_numbers = {best_match.get("bus_number")}
            stop_names = {best_match.get("matched_current_stop"), best_match.get("matched_destination")}
            for leg in best_match.get("legs", []):
                route_numbers.add(leg.get("bus_number"))
                stop_names.add(leg.get("from_stop"))
                stop_names.add(leg.get("to_stop"))
            route_numbers.discard(None)
            stop_names.discard(None)

            seen_alert_ids: set[str] = set()
            collected_alerts: list[dict] = []
            for route_number in route_numbers:
                for alert in await get_active_alerts(route_number=route_number):
                    if alert["id"] not in seen_alert_ids:
                        seen_alert_ids.add(alert["id"])
                        collected_alerts.append(alert)
            for stop_name in stop_names:
                for alert in await get_active_alerts(stop_name=stop_name):
                    if alert["id"] not in seen_alert_ids:
                        seen_alert_ids.add(alert["id"])
                        collected_alerts.append(alert)
            res["active_alerts"] = collected_alerts

        return res
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/routes")
async def routes(
    request: Request,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    search: str | None = Query(None, max_length=120),
) -> dict:
    predictor = get_predictor(request)
    # Scans and normalizes every route when `search` is set -- off the loop for
    # the same reason as /predict above.
    return await asyncio.to_thread(
        predictor.list_routes, limit=limit, offset=offset, search=search
    )


@router.get("/metrics")
async def metrics(request: Request) -> dict:
    predictor = get_predictor(request)
    # train() is a no-op once the predictor is ready (the lifespan handler has
    # already trained it), but it is a full training run if it is not -- so it
    # must not run on the event loop either.
    await asyncio.to_thread(predictor.train)
    return predictor.metrics


@router.get("/autocomplete")
async def autocomplete(
    request: Request,
    q: str = Query("", max_length=120),
    limit: int = Query(10, ge=1, le=25),
    kind: str = Query("stop", pattern="^(stop|destination)$"),
) -> dict:
    predictor = get_predictor(request)
    # Scores the query against all ~4.9k stop names. Cheap per call, but it is
    # fired on every keystroke by the frontend's debounced autocomplete, so
    # keeping it off the loop matters most here under concurrency.
    items = await asyncio.to_thread(predictor.autocomplete, q, limit=limit, kind=kind)
    return {"items": items}


@router.post("/directions")
async def directions(payload: PredictRequest) -> dict:
    if not settings.google_maps_api_key or settings.google_maps_api_key == "your-google-maps-api-key":
        raise HTTPException(status_code=500, detail="Google Maps API Key not configured in backend .env")
    
    origin = f"{payload.current_stop}, {settings.google_maps_location_suffix}"
    destination = f"{payload.destination}, {settings.google_maps_location_suffix}"
    
    params = {
        "origin": origin,
        "destination": destination,
        "mode": "transit",
        "transit_mode": "bus",
        "alternatives": "true",
        "key": settings.google_maps_api_key,
    }
    
    url = f"https://maps.googleapis.com/maps/api/directions/json?{urlencode(params)}"
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(url, timeout=10.0)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"Google API Error: {str(exc)}") from exc