"""Reaching a Metro station by bus, not on foot.

The nearest-metro panel answered with a walking time and nothing else: "40 min
walk", "42 min walk", "50 min walk". That is a distance restated in minutes,
not advice -- nobody walks 50 minutes to a Metro station. What a commuter needs
is the bus that gets them there, from both ends of their journey.

Each station now carries a `bus_connection`: the bus to take, the ride time and
distance, where to board and get off, and the short walk left at the end. It
stays absent when a bus would be noise -- a station already a few minutes away
on foot -- so the walking answer survives where it is the honest one.
"""

from __future__ import annotations

import pytest

from app.core.config import settings
from app.ml.predictor import BMTCBusPredictor
from app.services.metro_bus_link import (
    COMFORTABLE_WALK_KM,
    MAX_FINAL_WALK_KM,
    attach_bus_connections,
    bus_connection_to_station,
)
from app.services.metro_service import metro_service


@pytest.fixture(scope="module")
def predictor() -> BMTCBusPredictor:
    p = BMTCBusPredictor(settings.dataset_path, settings.artifact_dir)
    p.train()
    return p


def _stations(predictor: BMTCBusPredictor, stop: str, limit: int = 3):
    found = metro_service.find_nearest_stations(
        stop_name=stop, limit=limit, distance_service=predictor.distance_service
    )
    return attach_bus_connections(found, stop, predictor)


# ── A far station gets a bus, not a walking time ────────────────────────────

def test_a_distant_station_is_reached_by_bus(predictor) -> None:
    """White Field Post Office -> Kadugodi Tree Park is 1.85 km: a 23 min walk."""
    stations = _stations(predictor, "White Field Post Office")
    assert stations
    far = [s for s in stations if (s.get("distance_km") or 0) > COMFORTABLE_WALK_KM]
    assert far, "expected at least one station beyond walking distance"
    for station in far:
        connection = station.get("bus_connection")
        assert connection, f"{station['station_name']} left with only a walking time"
        assert connection["bus_chain"]
        assert connection["final_walk_minutes"] >= 1


def test_the_connection_reports_ride_time_and_distance(predictor) -> None:
    """Both were asked for explicitly; a bus number alone is not enough."""
    for station in _stations(predictor, "White Field Post Office"):
        connection = station.get("bus_connection")
        if not connection:
            continue
        assert connection["distance_km"] and connection["distance_km"] > 0
        assert connection["duration_minutes"] and connection["duration_minutes"] > 0
        assert connection["board_stop"] and connection["alight_stop"]


def test_the_final_walk_is_short(predictor) -> None:
    """A bus that drops you 3 km from the station has not helped."""
    for station in _stations(predictor, "White Field Post Office"):
        connection = station.get("bus_connection")
        if connection:
            assert connection["final_walk_km"] <= MAX_FINAL_WALK_KM


# ── Walking survives where it is the right answer ───────────────────────────

def test_a_nearby_station_is_still_a_walk(predictor) -> None:
    """Kengeri Bus Terminal is 0.35 km away -- suggesting a bus would be noise."""
    stations = _stations(predictor, "Kengeri")
    close = [s for s in stations if (s.get("distance_km") or 99) <= COMFORTABLE_WALK_KM]
    assert close, "expected a station within easy walking distance"
    for station in close:
        assert station.get("bus_connection") is None
        assert station.get("walking_minutes")


def test_no_bus_is_invented_when_already_at_the_right_stop(predictor) -> None:
    """If the nearest stop to the station is where you stand, there is no bus."""
    stations = metro_service.find_nearest_stations(
        stop_name="Kengeri Bus Station", limit=3, distance_service=predictor.distance_service
    )
    for station in stations:
        connection = bus_connection_to_station("Kengeri Bus Station", station, predictor)
        if connection:
            assert connection["alight_stop"].lower() != "kengeri bus station"


# ── Both ends of the journey ────────────────────────────────────────────────

@pytest.mark.parametrize("stop", ["White Field Post Office", "Kengeri", "Silk Board"])
def test_connections_are_available_from_any_stop(predictor, stop: str) -> None:
    """The panel is rendered for the boarding stop and the destination alike."""
    stations = _stations(predictor, stop)
    assert stations
    for station in stations:
        assert "bus_connection" in station, "every station must carry the field, even if null"


# ── Failure modes are quiet, not wrong ──────────────────────────────────────

def test_a_station_without_coordinates_yields_no_connection(predictor) -> None:
    assert bus_connection_to_station("Kengeri", {"station_name": "Nowhere"}, predictor) is None


def test_missing_predictor_is_handled(predictor) -> None:
    stations = metro_service.find_nearest_stations(
        stop_name="Kengeri", limit=2, distance_service=predictor.distance_service
    )
    assert attach_bus_connections(stations, "Kengeri", None) == stations
    assert bus_connection_to_station("Kengeri", stations[0], None) is None


def test_thresholds_are_sane() -> None:
    assert 0.3 <= COMFORTABLE_WALK_KM <= 1.2
    assert COMFORTABLE_WALK_KM < MAX_FINAL_WALK_KM <= 2.0
