"""Vehicle-facing queries: where buses are, which trip they are on, when they arrive.

Sits between the raw observation store and the API. Everything here degrades to
"we do not know" rather than to a guess, because the alternative to an honest
gap in vehicle data is a rider standing at a stop waiting for a bus that the
map invented.
"""

from __future__ import annotations

import logging
from typing import Any

from app.core.config import settings
from app.ml.blocking import parse_clock
from app.ml.data_loader import RouteRecord
from app.ml.route_geometry import RouteGeometry, resolve_route_geometry
from app.ml.text import normalize_text
from app.tracking.base import VehicleObservation
from app.tracking.ingest import vehicle_ingest
from app.tracking.matcher import (
    Projection,
    estimate_arrival,
    match_trip,
    project_onto_polyline,
)
from app.tracking.store import vehicle_store

logger = logging.getLogger("bmtc.services.vehicle")

# Matches BlockingParameters.average_speed_kmph. When neither an observed
# segment speed nor the vehicle's own speed is available, this is what the ETA
# falls back to -- and the estimate is labelled low-confidence for saying so.
DEFAULT_SPEED_KMPH = 16.0
DWELL_MINUTES_PER_STOP = 0.3


class RouteGeometryCache:
    """Route polylines, resolved once and kept.

    Resolving a route's stops is the expensive part (~1ms each), and an ETA
    request needs it every time. Cached per route-direction; the underlying CSV
    does not change while the process runs, so there is nothing to invalidate.
    """

    def __init__(self) -> None:
        self._cache: dict[tuple[str, int], RouteGeometry | None] = {}

    def get(self, route: RouteRecord, distance_service: Any) -> RouteGeometry | None:
        key = (route.route_number, route.direction_id)
        if key not in self._cache:
            geometry = resolve_route_geometry(route, distance_service)
            self._cache[key] = geometry if geometry.usable else None
        return self._cache[key]

    def clear(self) -> None:
        self._cache.clear()


geometry_cache = RouteGeometryCache()


def _routes_for(predictor: Any, route_number: str, direction_id: int | None) -> list[RouteRecord]:
    needle = route_number.strip().casefold()
    matches = [
        route for route in predictor.routes
        if route.route_number.casefold() == needle
        and (direction_id is None or route.direction_id == direction_id)
    ]
    return matches


def _stop_index(geometry: RouteGeometry, stop_name: str) -> int | None:
    """Which stop on this route the rider means.

    Compared on normalized names, the same grouping the predictor uses
    everywhere else, so "Majestic" and "Kempegowda Bus Station" resolve to the
    same stop here exactly as they do in a route search.
    """
    needle = normalize_text(stop_name)
    if not needle:
        return None
    for index, record in enumerate(geometry.records):
        if normalize_text(record.stop_name) == needle:
            return index
    # Fall back to a containment check for the long official names ("Central
    # Silk Board" vs "Silk Board") that normalization alone does not collapse.
    for index, record in enumerate(geometry.records):
        candidate = normalize_text(record.stop_name)
        if needle and (needle in candidate or candidate in needle):
            return index
    return None


# Above this many vehicles, per-vehicle enrichment (projecting each onto its
# route to name the next stop) costs more than it is worth on a poll every few
# seconds. A real BMTC fleet is ~6,000 vehicles; a map at city zoom cannot
# usefully label that many anyway, and a client wanting detail for one bus has
# GET /tracking/bus/{number}.
MAX_VEHICLES_TO_ENRICH = 250


def describe_vehicles(
    route_number: str | None = None, predictor: Any = None
) -> dict[str, Any]:
    """Current vehicle positions, with their provenance attached.

    `is_live` travels with every payload rather than being something the caller
    has to look up separately, so a UI cannot render simulated positions as
    live tracking by omission.
    """
    observations = (
        vehicle_store.for_route(route_number) if route_number else vehicle_store.fresh()
    )
    report = vehicle_ingest.source_report()

    enrich = predictor is not None and len(observations) <= MAX_VEHICLES_TO_ENRICH
    buses = []
    for observation in observations:
        payload = observation.as_dict()
        payload["next_stop"] = ""
        payload["direction"] = ""
        if enrich:
            detail = _next_stop_and_direction(predictor, observation)
            if detail:
                payload.update(detail)
        buses.append(payload)

    return {
        "status": "ok",
        "count": len(observations),
        "is_live": report["is_live"],
        "feed": report["feed"],
        "source_note": report["description"],
        "stale_withheld": report.get("vehicles_stale", 0),
        "enriched": enrich,
        "buses": buses,
    }


def _next_stop_and_direction(predictor: Any, observation: VehicleObservation) -> dict[str, str] | None:
    """Which stop this vehicle reaches next, from where it sits on the route.

    Derived from the projection rather than carried in the feed: real AVL feeds
    report a position, not a next stop, so computing it here is what makes the
    same UI work for a live feed and the simulator alike.
    """
    if not observation.route_number:
        return None
    for route in _routes_for(predictor, observation.route_number, observation.direction_id):
        geometry = geometry_cache.get(route, predictor.distance_service)
        if geometry is None:
            continue
        projection = _project(observation, geometry)
        if projection is None or projection.offset_km > 1.5:
            continue
        next_index = min(projection.segment_index + 1, len(geometry.records) - 1)
        return {
            "next_stop": geometry.records[next_index].stop_name,
            "direction": route.full_name or f"{route.source} to {route.destination}",
        }
    return None


def _project(
    observation: VehicleObservation, geometry: RouteGeometry
) -> Projection | None:
    return project_onto_polyline(
        (observation.lat, observation.lon), geometry.points, geometry.cumulative_km
    )


def vehicle_trip_status(
    predictor: Any, observation: VehicleObservation, now_minute: int
) -> dict[str, Any] | None:
    """Which scheduled trip a vehicle is running, and whether it is late.

    The single most valuable thing real vehicle positions unlock: schedule
    adherence is what a depot controller acts on, and it is unavailable to
    every consumer app because none of them hold the timetable.
    """
    if not observation.route_number:
        return None
    routes = _routes_for(predictor, observation.route_number, observation.direction_id)
    if not routes:
        return None

    best: dict[str, Any] | None = None
    for route in routes:
        geometry = geometry_cache.get(route, predictor.distance_service)
        if geometry is None:
            continue
        projection = _project(observation, geometry)
        if projection is None:
            continue

        departures = [
            minute for minute in (parse_clock(clock) for clock in route.trip_list)
            if minute is not None
        ]
        if not departures:
            continue
        duration = max(int(round(geometry.total_km / DEFAULT_SPEED_KMPH * 60)), 1)
        from app.ml.blocking import Trip

        candidates = [
            Trip(
                route_number=route.route_number,
                direction_id=route.direction_id,
                depart_minute=depart,
                arrive_minute=depart + duration,
                origin=normalize_text(route.stops[0]),
                destination=normalize_text(route.stops[-1]),
                revenue_km=geometry.total_km,
            )
            for depart in departures
        ]
        match = match_trip(now_minute, projection, geometry.total_km, candidates)
        if match is None:
            continue
        if best is None or abs(match.schedule_deviation_minutes) < abs(best["deviation_minutes"]):
            best = {
                "route_number": route.route_number,
                "direction_id": route.direction_id,
                "scheduled_departure": f"{match.trip.depart_minute // 60:02d}:{match.trip.depart_minute % 60:02d}",
                "deviation_minutes": match.schedule_deviation_minutes,
                "status": (
                    "on time" if abs(match.schedule_deviation_minutes) <= 3
                    else "late" if match.schedule_deviation_minutes > 0 else "early"
                ),
                "confidence": match.confidence,
                "distance_along_km": round(match.projection.distance_along_km, 2),
                "route_length_km": round(geometry.total_km, 2),
            }
    return best


def estimate_eta(
    predictor: Any, bus_number: str, target_stop: str
) -> dict[str, Any]:
    """When the next vehicle on this route reaches this stop.

    Distance is measured ALONG the route, not through buildings. The old
    estimate took a straight line, multiplied by 1.4 and divided by current
    speed, which is wrong in a specific and misleading way: a bus 400 m away
    across a block can be fifteen minutes from you if the route loops, and the
    straight-line figure confidently said two.
    """
    observations = vehicle_store.for_route(bus_number)
    if not observations:
        report = vehicle_ingest.source_report()
        return {
            "status": "no_vehicles",
            "bus_number": bus_number,
            "target_stop": target_stop,
            "is_live": report["is_live"],
            "note": (
                f"No current position for bus {bus_number}. "
                + (
                    "The vehicle feed is running but has not reported this route recently."
                    if report["is_live"]
                    else report["description"]
                )
            ),
        }

    routes = _routes_for(predictor, bus_number, None)
    if not routes:
        return {
            "status": "unknown_route",
            "bus_number": bus_number,
            "target_stop": target_stop,
            "note": f"No published route named {bus_number}.",
        }

    best: dict[str, Any] | None = None
    for observation in observations:
        for route in routes:
            if observation.direction_id is not None and route.direction_id != observation.direction_id:
                continue
            geometry = geometry_cache.get(route, predictor.distance_service)
            if geometry is None:
                continue
            stop_index = _stop_index(geometry, target_stop)
            if stop_index is None:
                continue
            projection = _project(observation, geometry)
            if projection is None or projection.offset_km > 1.5:
                continue

            estimate = estimate_arrival(
                projection,
                geometry.cumulative_km[stop_index],
                stops_between=max(stop_index - projection.segment_index - 1, 0),
                observed_speed_kmph=observation.speed_kmph,
                default_speed_kmph=DEFAULT_SPEED_KMPH,
                dwell_minutes_per_stop=DWELL_MINUTES_PER_STOP,
            )
            if estimate is None:
                # This vehicle has already passed the stop. Keep looking: the
                # next one behind it is the answer the rider wants.
                continue
            if best is None or estimate.minutes < best["eta_minutes"]:
                best = {
                    **estimate.as_dict(),
                    "vehicle_id": observation.vehicle_id,
                    "direction_id": route.direction_id,
                    "bus_lat": round(observation.lat, 6),
                    "bus_lon": round(observation.lon, 6),
                    "observation_age_seconds": round(observation.age_seconds(), 1),
                    "is_live": observation.is_live,
                }

    if best is None:
        return {
            "status": "no_approaching_vehicle",
            "bus_number": bus_number,
            "target_stop": target_stop,
            "note": (
                f"No vehicle on route {bus_number} is currently approaching {target_stop} -- "
                "every tracked vehicle has already passed it, is running the other direction, "
                "or is too far from the route line to place."
            ),
        }
    return {"status": "ok", "bus_number": bus_number, "target_stop": target_stop, **best}


def ingest_key_matches(supplied: str) -> bool:
    """Constant-time comparison of the AVL push secret.

    An unset key refuses everything: an open ingest endpoint would let anyone
    inject bus positions onto the map, which is a more consequential kind of
    fake data than anything else in this codebase.
    """
    import hmac

    expected = settings.avl_ingest_key
    if not expected:
        return False
    return hmac.compare_digest(supplied or "", expected)
