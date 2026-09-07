"""How to actually reach a Metro station from a bus stop.

The nearest-metro panel used to answer with a walking time and nothing else.
For a station 3 km away that read "40 min walk", which is not advice anyone
acts on -- it is a distance restated in minutes. What a commuter needs is the
bus that gets them there.

This module answers that: for a bus stop and a Metro station, find the bus stop
closest to the station, route to it with the existing predictor, and report the
bus, the ride, and the short walk left at the end.

Nothing here re-implements routing or distance. It composes
BMTCBusPredictor.predict() and the same haversine the rest of the system uses,
so a journey shown here is a journey the search page would also return.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from app.ml.blocking import haversine_km
from app.ml.text import normalize_text

logger = logging.getLogger("bmtc.metro_bus_link")

# Under this, walking is genuinely the right answer and suggesting a bus for it
# would be noise. Roughly ten minutes at the 12.5 min/km the metro service uses.
COMFORTABLE_WALK_KM = 0.8

# Beyond this from the station, a bus stop is not a sensible place to be
# dropped for that station -- better to report no useful connection than to
# send someone on a long second walk.
MAX_FINAL_WALK_KM = 1.5

# Same pace metro_service.py uses for its walking estimates, kept in step so
# two parts of the same screen do not quote different walking speeds.
WALK_MINUTES_PER_KM = 12.5


# Station coordinates never change, so the closest bus stop to each is worked
# out once per process rather than on every request.
_NEAREST_STOP_CACHE: dict[tuple[float, float], Optional[tuple[str, float]]] = {}


def _nearest_bus_stop(lat: float, lon: float, predictor: Any) -> Optional[tuple[str, float]]:
    """The bus stop closest to a coordinate, with its distance in km."""
    key = (round(lat, 5), round(lon, 5))
    if key in _NEAREST_STOP_CACHE:
        return _NEAREST_STOP_CACHE[key]

    coordinates = getattr(getattr(predictor, "distance_service", None), "stop_coordinates", None)
    if not coordinates:
        return None

    best_name: Optional[str] = None
    best_km = float("inf")
    for records in coordinates.values():
        for record in records:
            if record.lat is None or record.lon is None:
                continue
            km = haversine_km((lat, lon), (record.lat, record.lon))
            if km < best_km:
                best_km, best_name = km, record.stop_name
    found = (best_name, best_km) if best_name else None
    _NEAREST_STOP_CACHE[key] = found
    return found


def bus_connection_to_station(
    origin_stop: str,
    station: dict[str, Any],
    predictor: Any,
) -> Optional[dict[str, Any]]:
    """The bus to take from `origin_stop` to reach `station`.

    Returns None when a bus does not help: the station is already an easy
    walk, no coordinate is known, the nearest stop to the station is the one
    the commuter is standing at, or no route connects them.
    """
    if predictor is None or not origin_stop:
        return None

    lat, lon = station.get("latitude"), station.get("longitude")
    if not lat or not lon:
        return None

    walk_km = station.get("distance_km")
    if walk_km is not None and walk_km <= COMFORTABLE_WALK_KM:
        return None  # walking is the honest answer here

    nearest = _nearest_bus_stop(float(lat), float(lon), predictor)
    if not nearest:
        return None
    alight_stop, final_walk_km = nearest
    if final_walk_km > MAX_FINAL_WALK_KM:
        return None

    # Already at the best stop for this station -- there is no bus to take.
    if normalize_text(alight_stop) == normalize_text(origin_stop):
        return None

    try:
        result = predictor.predict(origin_stop, alight_stop, limit=1)
    except Exception:
        return None

    best = (result or {}).get("best_match") or {}
    if not best:
        return None

    ride_minutes = best.get("duration_minutes")
    final_walk_minutes = max(1, int(round(final_walk_km * WALK_MINUTES_PER_KM)))

    return {
        "bus_chain": best.get("bus_chain") or best.get("bus_number"),
        "transfers": best.get("transfers") or 0,
        "board_stop": best.get("matched_current_stop") or origin_stop,
        "alight_stop": best.get("matched_destination") or alight_stop,
        "distance_km": best.get("distance_km"),
        "duration_minutes": round(ride_minutes, 1) if ride_minutes else None,
        "total_stops": best.get("total_stops"),
        "final_walk_km": round(final_walk_km, 2),
        "final_walk_minutes": final_walk_minutes,
    }


def attach_bus_connections(
    stations: list[dict[str, Any]],
    origin_stop: Optional[str],
    predictor: Any,
    limit: int = 3,
) -> list[dict[str, Any]]:
    """Add a `bus_connection` to each station, for the closest few only.

    Bounded deliberately: each connection costs a nearest-stop scan and a route
    search, and a commuter does not act on the eighth-closest Metro station. Three matches
    what the panel displays, so no station is left showing a bare walking time
    -- which is the thing this replaced.
    """
    if not origin_stop or predictor is None:
        return stations

    for index, station in enumerate(stations):
        if index >= limit:
            station["bus_connection"] = None
            continue
        try:
            station["bus_connection"] = bus_connection_to_station(origin_stop, station, predictor)
        except Exception:
            logger.exception("Could not build a bus connection to %s", station.get("station_name"))
            station["bus_connection"] = None
    return stations
