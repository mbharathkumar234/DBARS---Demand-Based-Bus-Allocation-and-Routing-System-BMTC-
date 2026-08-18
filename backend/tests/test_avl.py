"""Guards for the vehicle location layer.

The failures that matter here are ones that look fine on a map. A stale
position renders identically to a fresh one. A vehicle matched to the wrong
trip produces a confident "8 minutes late" that a controller would act on. A
straight-line ETA is a plausible number that is simply wrong when the route
loops. None of these throw; all of them mislead, so they are what the tests
are aimed at.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.ml.blocking import Trip
from app.tracking.adapters import HttpJsonFeed, SimulatedFeed, build_feed
from app.tracking.base import VehicleObservation
from app.tracking.matcher import (
    cumulative_distances,
    estimate_arrival,
    match_trip,
    project_onto_polyline,
)
from app.tracking.store import VehicleStateStore


def _observation(**overrides) -> VehicleObservation:
    base = dict(
        vehicle_id="KA01F1234",
        lat=12.9716,
        lon=77.5946,
        recorded_at=datetime.now(timezone.utc),
        route_number="500-D",
        source="test",
        is_live=True,
    )
    base.update(overrides)
    return VehicleObservation(**base)


# ── store: staleness ────────────────────────────────────────────────────────
def test_stale_observations_are_withheld_not_shown():
    """A stalled feed keeps returning its last payload. Rendering that as the
    current position produces a map of buses frozen mid-road that riders will
    stand and wait for."""
    store = VehicleStateStore(stale_after_seconds=60)
    old = datetime.now(timezone.utc) - timedelta(seconds=300)
    store.replace_all([_observation(vehicle_id="fresh"), _observation(vehicle_id="stale", recorded_at=old)])

    assert {observation.vehicle_id for observation in store.fresh()} == {"fresh"}
    assert store.stale_count() == 1
    assert store.get("stale") is None
    assert store.get("fresh") is not None
    # The stall stays visible rather than silently shrinking the fleet.
    assert store.health()["vehicles_tracked"] == 2
    assert store.health()["vehicles_stale"] == 1


def test_push_merge_keeps_the_newest_fix_per_vehicle():
    """Pushes arrive out of order. An older fix overwriting a newer one makes a
    bus appear to jump backwards down the road."""
    store = VehicleStateStore()
    now = datetime.now(timezone.utc)
    store.apply([_observation(lat=12.90, recorded_at=now)])
    store.apply([_observation(lat=12.80, recorded_at=now - timedelta(seconds=30))])

    assert store.get("KA01F1234").lat == pytest.approx(12.90)

    store.apply([_observation(lat=12.95, recorded_at=now + timedelta(seconds=30))])
    assert store.get("KA01F1234").lat == pytest.approx(12.95)


# ── adapters ────────────────────────────────────────────────────────────────
def test_simulated_feed_never_claims_to_be_live():
    """The one flag every honesty gate in the codebase reads."""
    assert SimulatedFeed().is_live is False
    assert build_feed("simulated").is_live is False
    assert build_feed("gtfs_rt", url="http://example.invalid/feed").is_live is True
    assert build_feed("push").is_live is True


def test_unknown_feed_kind_is_refused_loudly():
    with pytest.raises(ValueError, match="Unknown TRACKING_FEED"):
        build_feed("telepathy")
    # A live adapter without a URL is a misconfiguration, not a feed that
    # silently returns nothing.
    with pytest.raises(ValueError, match="TRACKING_FEED_URL"):
        build_feed("gtfs_rt")


def test_http_json_feed_maps_vendor_field_names():
    """Every ITS vendor invents its own field names and none are negotiable, so
    the mapping is configuration rather than code."""
    feed = HttpJsonFeed(
        "http://example.invalid/vehicles",
        field_map={
            "vehicle_id": "busId",
            "lat": "gps.lat",
            "lon": "gps.lng",
            "recorded_at": "ts",
            "route_number": "routeName",
            "speed_kmph": "spd",
        },
    )
    observation = feed._to_observation({
        "busId": "KA57F9999",
        "gps": {"lat": 12.9, "lng": 77.6},
        "ts": 1786000000,
        "routeName": "500-D",
        "spd": "24.5",
    })
    assert observation is not None
    assert observation.vehicle_id == "KA57F9999"
    assert observation.lat == pytest.approx(12.9)
    assert observation.speed_kmph == pytest.approx(24.5)      # coerced from a string
    assert observation.is_live is True

    # A row with no position is not a sighting. Dropping it is right;
    # inventing coordinates for it would not be.
    assert feed._to_observation({"busId": "X", "gps": {}}) is None


# ── projection ──────────────────────────────────────────────────────────────
def _straight_line() -> tuple[list[tuple[float, float]], list[float]]:
    # Four points due north, roughly 1.1 km apart.
    polyline = [(12.90, 77.60), (12.91, 77.60), (12.92, 77.60), (12.93, 77.60)]
    return polyline, cumulative_distances(polyline)


def test_projection_locates_a_vehicle_along_the_route():
    polyline, cumulative = _straight_line()
    projection = project_onto_polyline((12.915, 77.60), polyline, cumulative)

    assert projection is not None
    assert projection.offset_km == pytest.approx(0.0, abs=0.02)
    assert projection.distance_along_km == pytest.approx(cumulative[1] + 0.55, abs=0.1)


def test_projection_reports_how_far_off_route_a_vehicle_is():
    """A large offset means the vehicle is not running this route -- diverted,
    mis-tagged, or a different service. Reporting a confident position along a
    line the bus is nowhere near would be worse than reporting nothing."""
    polyline, cumulative = _straight_line()
    projection = project_onto_polyline((12.915, 77.70), polyline, cumulative)
    assert projection is not None
    assert projection.offset_km > 5


# ── trip matching ───────────────────────────────────────────────────────────
def _trip(depart: int, duration: int = 60) -> Trip:
    return Trip(
        route_number="500-D", direction_id=0, depart_minute=depart,
        arrive_minute=depart + duration, origin="a", destination="b", revenue_km=10.0,
    )


def test_trip_match_reports_schedule_deviation():
    polyline, cumulative = _straight_line()
    length = cumulative[-1]
    # Halfway along the route at 09:30, on a trip that departed 09:00 and takes
    # 60 minutes: exactly on time.
    projection = project_onto_polyline((12.915, 77.60), polyline, cumulative)
    match = match_trip(9 * 60 + 30, projection, length, [_trip(9 * 60)])

    assert match is not None
    assert match.schedule_deviation_minutes == pytest.approx(0, abs=2)
    assert match.confidence == "high"


def test_a_vehicle_far_off_route_matches_nothing():
    """An unmatched vehicle is still shown on the map; it simply has no
    adherence figure. A wrong match produces a confident and completely
    fictional 'late by 8 minutes' that a controller would act on."""
    polyline, cumulative = _straight_line()
    projection = project_onto_polyline((12.915, 77.90), polyline, cumulative)
    assert match_trip(9 * 60 + 30, projection, cumulative[-1], [_trip(9 * 60)]) is None


def test_no_plausible_trip_returns_none_rather_than_the_nearest_one():
    polyline, cumulative = _straight_line()
    projection = project_onto_polyline((12.915, 77.60), polyline, cumulative)
    # Only trip of the day departed at 05:00; it is now 21:00.
    assert match_trip(21 * 60, projection, cumulative[-1], [_trip(5 * 60)]) is None


# ── ETA ─────────────────────────────────────────────────────────────────────
def test_eta_confidence_reflects_which_speed_source_was_available():
    """The label is derived, not guessed. A rider told '8-14 min, low
    confidence' can plan; one told '11 min' by a hard-coded default cannot."""
    polyline, cumulative = _straight_line()
    projection = project_onto_polyline((12.90, 77.60), polyline, cumulative)
    target = cumulative[-1]

    high = estimate_arrival(projection, target, stops_between=2, observed_speed_kmph=20, segment_speed_kmph=18)
    medium = estimate_arrival(projection, target, stops_between=2, observed_speed_kmph=20)
    low = estimate_arrival(projection, target, stops_between=2, observed_speed_kmph=None)

    assert (high.confidence, medium.confidence, low.confidence) == ("high", "medium", "low")
    # The band widens as confidence falls: a low-confidence estimate quoting a
    # two-minute window is worse than no estimate at all.
    assert (low.high_minutes - low.low_minutes) > (high.high_minutes - high.low_minutes)


def test_eta_is_none_when_the_bus_has_already_passed():
    """A bus past your stop is not arriving in negative minutes -- the caller
    must look for the next vehicle instead."""
    polyline, cumulative = _straight_line()
    projection = project_onto_polyline((12.93, 77.60), polyline, cumulative)
    assert estimate_arrival(projection, cumulative[1], stops_between=0, observed_speed_kmph=20) is None


def test_eta_follows_the_route_not_the_crow():
    """The reason the whole projection layer exists. On a route that loops, a
    bus a few hundred metres away as the crow flies is most of a lap from your
    stop, and the old straight-line estimate said two minutes."""
    # A closed loop: out east, then back west to near the start.
    polyline = [(12.90, 77.60), (12.90, 77.65), (12.95, 77.65), (12.95, 77.60), (12.905, 77.60)]
    cumulative = cumulative_distances(polyline)
    # Vehicle just after the start; target is the LAST point, geographically
    # ~500 m away but a full loop by road.
    projection = project_onto_polyline((12.901, 77.601), polyline, cumulative)
    estimate = estimate_arrival(projection, cumulative[-1], stops_between=4, observed_speed_kmph=20)

    assert estimate is not None
    assert estimate.remaining_km > 15          # the loop, not the 0.5 km crow-line
    assert estimate.minutes > 40
