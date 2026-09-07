"""Guards for the geometry the route map is drawn from.

This is a silent class of bug: the numbers beside the map were always right,
because route_distance() walks an anchor. Only the drawn line was wrong, and a
wrong line still looks like a map. Route 335-G rendered a 69.4 km path for a
19.2 km journey because its "Kodihalli" matched the wrong Kodihalli 28 km east.

The invariant below catches all of it in one assertion: a route's drawn length
must be close to its stated length. Straight-line drawing is always SHORTER
than the road distance quoted beside it (distance.py applies a 1.28 road
factor), so a drawn path that is longer, or wildly shorter, means the line went
somewhere the journey does not.
"""

from __future__ import annotations

import pytest

from app.core.config import settings
from app.ml.blocking import haversine_km
from app.ml.predictor import BMTCBusPredictor
from app.ml.route_geometry import resolve_stop_sequence


@pytest.fixture(scope="module")
def predictor() -> BMTCBusPredictor:
    instance = BMTCBusPredictor(settings.dataset_path, settings.artifact_dir)
    instance.train()
    return instance


# Real journeys across the city, chosen to include several that used to draw
# the teleporting lines: 335-G's Kodihalli, and the transfers that changed at a
# name existing twice in Bengaluru.
JOURNEYS = [
    ("Majestic", "Marathahalli"),
    ("Banashankari", "Hebbal"),
    ("Shivajinagar", "Kengeri"),
    ("Hebbal", "Silk Board"),
    ("Majestic", "Whitefield"),
    ("Yelahanka", "Electronic City"),
    ("Banashankari", "Whitefield"),
    ("Jayanagar", "Yelahanka"),
    ("Whitefield", "Kengeri"),
    ("Marathahalli", "Peenya"),
]


def _drawn_path(coordinates: list[dict]) -> list[tuple[float, float]]:
    return [(c["lat"], c["lon"]) for c in coordinates if c.get("lat") is not None]


def _hops(points: list[tuple[float, float]]) -> list[float]:
    return [haversine_km(a, b) for a, b in zip(points, points[1:])]


@pytest.mark.parametrize("origin,destination", JOURNEYS)
def test_drawn_route_never_teleports(predictor, origin, destination):
    """No single hop between consecutive stops may be a cross-city jump.

    Consecutive stops on an ordinary route are a few hundred metres apart, and
    a multi-kilometre hop is a stop name resolved to the wrong side of the city
    -- what the user sees as a random straight line.

    Express services break the "few hundred metres" premise legitimately.
    V-EXP 500D runs the Outer Ring Road with 11 stops and 34 trips a day; its
    longest genuine hop is 7.2 km. A flat 5 km ceiling failed that route for
    doing exactly what an express is meant to do, so the limit scales with the
    journey instead: no hop may be a large fraction of the whole trip, and none
    may be a cross-city distance in absolute terms. The 335-G bug this guards
    against drew ~28 km hops on a 19.2 km journey and is still caught by both
    halves. `test_drawn_length_agrees_with_stated_distance` below remains the
    stronger invariant.
    """
    best = predictor.predict(origin, destination, 3)["best_match"]
    assert best is not None, f"{origin} -> {destination} became unroutable"

    points = _drawn_path(best["route_coordinates"])
    assert len(points) >= 2
    hops = _hops(points)
    worst = max(hops)
    stated = best["distance_km"] or 0.0
    limit = min(12.0, max(5.0, 0.45 * stated))
    assert worst <= limit, (
        f"{origin} -> {destination} draws a {worst:.1f} km jump between consecutive "
        f"stops (limit {limit:.1f} km for a {stated:.1f} km journey)"
    )


@pytest.mark.parametrize("origin,destination", JOURNEYS)
def test_drawn_length_agrees_with_stated_distance(predictor, origin, destination):
    """The line on the map and the number beside it must describe one journey."""
    best = predictor.predict(origin, destination, 3)["best_match"]
    assert best is not None

    drawn = sum(_hops(_drawn_path(best["route_coordinates"])))
    stated = best["distance_km"]
    assert stated > 0

    # Straight-line vs road distance: distance.py multiplies by 1.28, so the
    # drawn path should sit near 78% of the stated figure. The band is wide
    # enough for genuine route curvature and narrow enough that a single
    # cross-city excursion breaks it.
    ratio = drawn / stated
    assert 0.45 <= ratio <= 1.05, (
        f"{origin} -> {destination}: drew {drawn:.1f} km for a stated {stated:.1f} km journey"
    )


def test_transfers_change_at_one_physical_place(predictor):
    """A transfer is found by matching stop NAMES, and Bengaluru reuses them.
    Banashankari -> Hebbal was answered with "215-K to Avalahalli, then 285-M
    from Avalahalli" -- two real stops of that name, 28.6 km apart, and a
    journey nobody can make."""
    for origin, destination in JOURNEYS:
        best = predictor.predict(origin, destination, 3)["best_match"]
        legs = (best or {}).get("legs") or []
        for leaving, joining in zip(legs, legs[1:]):
            arrive = _drawn_path(leaving["route_coordinates"])[-1]
            depart = _drawn_path(joining["route_coordinates"])[0]
            gap = haversine_km(arrive, depart)
            assert gap <= predictor.MAX_INTERCHANGE_WALK_KM + 0.1, (
                f"{origin} -> {destination}: transfer between "
                f"{leaving['bus_number']} and {joining['bus_number']} spans {gap:.1f} km"
            )


def test_anchoring_is_what_prevents_the_teleport(predictor):
    """Pins the mechanism, not just the symptom.

    Resolving the same stop list without anchoring must produce a visibly worse
    path than resolving it with anchoring -- otherwise this route stopped being
    a regression test for the bug it was written for.
    """
    best = predictor.predict("Majestic", "Marathahalli", 3)["best_match"]
    path = best["route_path"]

    anchored = [
        (record.lat, record.lon)
        for record in resolve_stop_sequence(path, predictor.distance_service)
        if record
    ]
    naive = [
        point
        for point in (predictor.distance_service.resolve_coordinate(stop) for stop in path)
        if point
    ]

    assert max(_hops(anchored)) < 5.0
    # The unanchored path is the old behaviour: it drew 69.4 km for this
    # 19.2 km route.
    assert sum(_hops(naive)) > sum(_hops(anchored)) * 2


def test_unresolvable_names_keep_their_position(predictor):
    """resolve_stop_sequence returns one entry per input stop, so a caller can
    keep names and coordinates aligned and emit a null rather than silently
    shifting every later stop up by one."""
    stops = ["Majestic", "Not A Real Stop At All Xyzzy", "Marathahalli"]
    resolved = resolve_stop_sequence(stops, predictor.distance_service)
    assert len(resolved) == len(stops)
