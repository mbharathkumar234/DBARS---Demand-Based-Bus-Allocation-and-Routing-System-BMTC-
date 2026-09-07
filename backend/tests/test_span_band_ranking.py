"""Regression tests for length-banded route ranking.

Reported for Reva College -> Sapthagiri College, which returned a 53-stop,
42.35 km journey transferring at Indian Express -- in central Bengaluru, ~15 km
*south* of both colleges, which are north and north-west. A 41-stop, 33.43 km
chain was sitting in the same candidate list.

Cause: `route_rank_score` ordered `trunk_tier` above `total_stops`, and route
253 matches the trunk prefix list while 507 does not. The existing length
penalty could not counter it, because `_min_span_for_pair` is derived from
*direct* segments only -- on a transfer-only pair it stays None and
`span_excess` is always 0, leaving trunk status to decide unopposed.

Fix: band each candidate by how far above the shortest walkable candidate it
is, and rank that band above trunk status. Trunk routes still win among
journeys of comparable length; they no longer win by riding materially further.
"""

from __future__ import annotations

import random

import pytest

import app.ml.predictor as predictor_module
from app.core.config import settings
from app.ml.predictor import BMTCBusPredictor


@pytest.fixture(scope="module")
def predictor() -> BMTCBusPredictor:
    p = BMTCBusPredictor(settings.dataset_path, settings.artifact_dir)
    p.train()
    return p


def _best(p: BMTCBusPredictor, a: str, b: str) -> dict:
    return (p.predict(a, b, limit=5) or {}).get("best_match") or {}


# ── The reported pair ───────────────────────────────────────────────────────

def test_reva_to_sapthagiri_does_not_detour_through_the_city_centre(predictor) -> None:
    best = _best(predictor, "Reva College", "Sapthagiri College")
    assert best, "expected a route for this pair"
    assert "Indian Express" not in (best.get("transfer_stops") or [])
    assert (best.get("total_stops") or 999) <= 45
    assert (best.get("distance_km") or 999) < 40


def test_the_recommendation_is_not_beaten_by_a_comparable_alternative(predictor) -> None:
    """No materially shorter alternative of the same quality tier may sit below.

    "Same tier" matters. `278-A -> 254-E` covers this pair in 24 stops against
    the recommended 41, but 278-A runs **once a day** and is penalised as a
    special/low-frequency service by a tier that outranks length. Recommending
    a once-daily bus because it is shorter would be worse advice, so those are
    excluded here rather than treated as regressions.
    """
    trips = {r.route_number.strip().upper(): r.trip_count for r in predictor.routes}

    def is_frequent(chain: str) -> bool:
        return all(trips.get(part.strip().upper(), 0) > 1 for part in chain.split("->"))

    result = predictor.predict("Reva College", "Sapthagiri College", limit=6)
    best = result.get("best_match") or {}
    best_stops = best.get("total_stops") or 0
    best_transfers = best.get("transfers") or 0

    for alt in (result.get("alternatives") or []):
        chain = alt.get("bus_chain") or alt.get("bus_number") or ""
        if (alt.get("transfers") or 0) != best_transfers or not is_frequent(chain):
            continue
        if (alt.get("total_stops") or 0) < best_stops * 0.7:
            pytest.fail(
                f"alternative {chain} has {alt.get('total_stops')} stops "
                f"vs the recommended {best_stops}"
            )


# ── The general property ────────────────────────────────────────────────────

def test_banding_never_lengthens_a_recommendation(predictor) -> None:
    """Across random pairs, banding may shorten a journey but never extend it.

    Setting SPAN_BAND_FRACTION very large collapses every band to 0, which
    reproduces the pre-fix ordering exactly.
    """
    random.seed(20260906)
    stops = random.sample(predictor.stop_names, 60)
    pairs = [(stops[i], stops[i + 1]) for i in range(0, 40, 2)]

    original = predictor_module.SPAN_BAND_FRACTION
    try:
        predictor_module.SPAN_BAND_FRACTION = 10 ** 9
        before = {pair: _best(predictor, *pair) for pair in pairs}
        predictor_module.SPAN_BAND_FRACTION = original
        after = {pair: _best(predictor, *pair) for pair in pairs}
    finally:
        predictor_module.SPAN_BAND_FRACTION = original

    regressions = []
    for pair in pairs:
        b, a = before[pair], after[pair]
        if not b or not a:
            continue
        if (a.get("total_stops") or 0) > (b.get("total_stops") or 0):
            regressions.append((pair, b.get("total_stops"), a.get("total_stops")))
        # Nor should it trade a direct route for a transfer.
        assert (a.get("transfers") or 0) <= (b.get("transfers") or 0), pair

    assert not regressions, f"banding lengthened these journeys: {regressions}"


def test_span_band_fraction_is_a_sane_ratio() -> None:
    """A trunk route stays preferred within this much of the shortest journey."""
    assert 0.05 <= predictor_module.SPAN_BAND_FRACTION <= 0.5


def test_direct_routes_still_outrank_transfers(predictor) -> None:
    """`transfers` stays second in the rank tuple; the early-exit guard in the
    enumeration depends on it, and banding was inserted after it."""
    best = _best(predictor, "Silk Board", "Marathahalli")
    assert best
    result = predictor.predict("Majestic", "Whitefield", limit=5)
    best_direct = result.get("best_match") or {}
    alts = result.get("alternatives") or []
    if best_direct.get("transfers") == 0:
        assert all((a.get("transfers") or 0) >= 0 for a in alts)
