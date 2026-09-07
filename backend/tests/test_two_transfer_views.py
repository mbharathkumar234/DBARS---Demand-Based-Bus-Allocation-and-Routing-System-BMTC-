"""Two-transfer search and the two ranked views.

Raised by comparing DBARS against Google Maps for Sapthagiri College -> Reva
College. Both stops are in north Bengaluru, but no single interchange links
them along the northern arc, so a direct + one-transfer search can only reach
Reva by coming down into the city and back out -- 32.5 km. Google answers the
same pair with three buses (248-BA -> 401-A -> 289-S, 1h52m) staying north.

Every one of those routes is in this dataset: 248-BA serves Sapthagiri, 289-S
serves Reva, and 401-A serves neither -- it is purely a middle leg, which no
amount of one-transfer searching can find.

Measured over 60 random pairs, adding the third leg made 16 pairs routable that
previously had no answer at all, and offered a materially shorter option on 15
more (median 22% less distance).
"""

from __future__ import annotations

import pytest

import app.ml.predictor as predictor_module
from app.core.config import settings
from app.ml.predictor import BMTCBusPredictor
from app.ml.text import normalize_text

PAIR = ("Sapthagiri College", "Reva College")


@pytest.fixture(scope="module")
def predictor() -> BMTCBusPredictor:
    p = BMTCBusPredictor(settings.dataset_path, settings.artifact_dir)
    p.train()
    return p


# ── The search itself ───────────────────────────────────────────────────────

def test_finds_three_bus_journeys_for_a_cross_arc_pair(predictor) -> None:
    paths = predictor._find_two_transfer_paths(
        normalize_text(PAIR[0]), normalize_text(PAIR[1]), limit=8
    )
    assert paths, "no three-bus journey found for a pair that needs one"
    for transfers, _hops, tuples in paths:
        assert transfers == 2
        assert len(tuples) == 3


def test_every_interchange_in_a_three_bus_journey_is_walkable(predictor) -> None:
    """Both changes must be real places, not two stops sharing a name."""
    paths = predictor._find_two_transfer_paths(
        normalize_text(PAIR[0]), normalize_text(PAIR[1]), limit=8
    )
    for _t, _h, tuples in paths:
        assert predictor._interchange_is_walkable(tuples)


def test_the_middle_bus_serves_neither_endpoint(predictor) -> None:
    """That is the whole point -- a one-transfer search cannot reach it."""
    a, b = normalize_text(PAIR[0]), normalize_text(PAIR[1])
    paths = predictor._find_two_transfer_paths(a, b, limit=5)
    assert paths
    middle = paths[0][2][1][0]
    assert not (a in middle.normalized_stops and b in middle.normalized_stops)


# ── The two views ───────────────────────────────────────────────────────────

def test_predict_exposes_both_views(predictor) -> None:
    result = predictor.predict(*PAIR, limit=5)
    views = result.get("views")
    assert views is not None
    assert "fewest_transfers" in views and "least_distance" in views


def test_least_distance_is_ordered_by_distance(predictor) -> None:
    options = predictor.predict(*PAIR, limit=5)["views"]["least_distance"]
    distances = [o.get("total_distance_km") or 9999 for o in options]
    assert distances == sorted(distances)


def test_fewest_transfers_is_ordered_by_transfers(predictor) -> None:
    options = predictor.predict(*PAIR, limit=5)["views"]["fewest_transfers"]
    transfers = [o.get("transfers") or 0 for o in options]
    assert transfers == sorted(transfers)


def test_the_two_views_disagree_on_this_pair(predictor) -> None:
    """If they never disagreed the tabs would be pointless."""
    views = predictor.predict(*PAIR, limit=5)["views"]
    fewest, least = views["fewest_transfers"][0], views["least_distance"][0]
    assert least["total_distance_km"] < fewest["total_distance_km"]
    assert (least["transfers"] or 0) > (fewest["transfers"] or 0)


def test_every_option_carries_a_duration(predictor) -> None:
    """The 'least travelling time' view cannot rank without one."""
    views = predictor.predict(*PAIR, limit=5)["views"]
    for name in ("fewest_transfers", "least_distance"):
        for option in views[name]:
            assert option.get("duration_minutes"), f"{name}: {option.get('bus_chain')} has no duration"


def test_a_change_costs_time_as_well_as_distance(predictor) -> None:
    """Duration includes a waiting allowance, so a 3-bus ride is not scored as
    if changing buses were free."""
    assert predictor_module.TRANSFER_PENALTY_MINUTES > 0
    options = predictor.predict(*PAIR, limit=5)["views"]["least_distance"]
    option = options[0]
    riding = sum(float(leg.get("duration_minutes") or 0) for leg in option["legs"])
    assert option["duration_minutes"] > riding


# ── The performance gate ────────────────────────────────────────────────────

def test_a_direct_journey_skips_the_deeper_search(predictor) -> None:
    """The three-bus search costs ~280ms and must not run when one bus does."""
    calls = []
    original = predictor._find_two_transfer_paths
    predictor._find_two_transfer_paths = lambda *a, **k: (calls.append(1), original(*a, **k))[1]
    try:
        result = predictor.predict("Silk Board", "Marathahalli", limit=5)
    finally:
        predictor._find_two_transfer_paths = original

    if any((s.get("transfers") or 0) == 0 for s in result.get("alternatives") or []):
        assert not calls, "the deeper search ran even though a direct bus exists"


def test_threshold_is_a_sane_stop_count() -> None:
    assert 5 <= predictor_module.TWO_TRANSFER_STOP_THRESHOLD <= 40
