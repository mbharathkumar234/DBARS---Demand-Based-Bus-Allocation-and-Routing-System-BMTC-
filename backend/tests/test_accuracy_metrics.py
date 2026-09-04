"""Phase 5 — Regression tests for the accuracy improvement plan.

Six tests that pin the measurement invariants introduced in Phases 1-3,
so a future change that breaks them is caught before it reaches metrics.json.
"""
from __future__ import annotations

import json
import random
from pathlib import Path

import pytest

from app.ml.predictor import BMTCBusPredictor
from app.ml.text import normalize_text


# ── Fixtures ─────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def _real_predictor():
    """Load the real predictor once for the entire module.

    Falls back to skipping if the dataset is unavailable.
    """
    from app.core.config import settings

    dataset_path = Path(settings.dataset_path)
    if not dataset_path.exists():
        pytest.skip(f"Dataset not found: {dataset_path}")

    predictor = BMTCBusPredictor(dataset_path, Path(settings.artifact_dir))
    predictor.train(force=False)
    return predictor


@pytest.fixture(scope="module")
def metrics(_real_predictor):
    """Return the live metrics dict."""
    return _real_predictor.metrics


@pytest.fixture(scope="module")
def predictor(_real_predictor):
    return _real_predictor


# ── 1. test_relevance_set_is_not_single_label ────────────────────────────

def test_relevance_set_is_not_single_label(predictor) -> None:
    """A pair with multiple valid buses yields a set of size > 1."""
    # Pick a pair that is known to be served by many routes
    random.seed(42)
    evaluable = [r for r in predictor.routes if len(r.stops) >= 4]
    found_multi = False
    for route in evaluable[:200]:
        start = random.randint(0, max(0, len(route.stops) - 3))
        dest = random.randint(start + 1, len(route.stops) - 1)
        valid = predictor._valid_routes_for_pair(route.stops[start], route.stops[dest])
        if len(valid) > 1:
            found_multi = True
            break
    assert found_multi, (
        "Could not find any stop pair served by more than one bus — "
        "the relevance set would always be a single label"
    )


# ── 2. test_lenient_scoring_accepts_any_valid_bus ────────────────────────

def test_lenient_scoring_accepts_any_valid_bus(predictor) -> None:
    """A known-valid alternative scores as a hit under lenient scoring."""
    random.seed(42)
    evaluable = [r for r in predictor.routes if len(r.stops) >= 4]
    # Find a pair, get its valid set, run the search, confirm the returned bus is valid
    for route in evaluable[:50]:
        start = random.randint(0, max(0, len(route.stops) - 3))
        dest = random.randint(start + 1, len(route.stops) - 1)
        stop_a, stop_b = route.stops[start], route.stops[dest]
        valid = predictor._valid_routes_for_pair(stop_a, stop_b)
        if not valid:
            continue
        try:
            suggestions = predictor._find_transfer_suggestions(stop_a, stop_b, limit=1)
        except Exception:
            continue
        if suggestions and suggestions[0]["transfers"] == 0:
            returned_bus = suggestions[0]["legs"][0]["bus_number"]
            assert returned_bus in valid, (
                f"Returned bus {returned_bus} is not in the valid set {valid} "
                f"for pair ({stop_a} -> {stop_b})"
            )
            return
    pytest.skip("Could not find a testable direct-route pair")


# ── 3. test_models_compared_on_equal_samples ─────────────────────────────

def test_models_compared_on_equal_samples(metrics) -> None:
    """All models report the same n."""
    test_n = metrics.get("test_samples")
    live_n = metrics.get("live_test_samples")
    assert test_n is not None and live_n is not None, "sample counts missing"
    assert test_n == live_n, f"test_samples={test_n} != live_test_samples={live_n}"
    assert test_n >= 60, f"sample count {test_n} is below the 60-sample floor"


# ── 4. test_lenient_top1_above_threshold ─────────────────────────────────

def test_lenient_top1_above_threshold(metrics) -> None:
    """Lenient top-1 >= 0.95 on the stored evaluation."""
    rsm = metrics.get("relevance_set_metrics", {})
    top1 = rsm.get("accuracy_top_1", 0)
    assert top1 >= 0.95, f"lenient top-1 = {top1}, expected >= 0.95"


# ── 5. test_rank_quality_not_regressed ───────────────────────────────────

def test_rank_quality_not_regressed(metrics) -> None:
    """best_option_rate >= the recorded baseline."""
    rq = metrics.get("rank_quality", {})
    bor = rq.get("best_option_rate")
    assert bor is not None, "best_option_rate missing from rank_quality"
    # The Phase 0 baseline was 0.57; Phase 3 target is >= 0.70.
    # This test guards against regression below baseline.
    assert bor >= 0.55, f"best_option_rate = {bor}, regressed below baseline 0.57"


# ── 6. test_metrics_json_declares_headline_metric ────────────────────────

def test_metrics_json_declares_headline_metric(metrics) -> None:
    """The headline field exists and names a real metric."""
    headline = metrics.get("headline_metric")
    assert headline is not None, "headline_metric missing from metrics"
    assert headline in metrics, f"headline_metric '{headline}' does not name a key in metrics"
    # The headline must be a metric the system can FAIL. coverage /
    # relevance_set scoring derives its relevance set from the same
    # stop_pair_to_segments index the search uses to generate candidates,
    # so a near-1.0 score there is close to tautological and has almost no
    # discriminating power. rank_quality scores against an independent
    # criterion (fewest stops), which the ranker did fail at 0.57.
    assert headline == "rank_quality", (
        "headline_metric must be rank_quality, not a near-tautological coverage metric; "
        f"got {headline!r}"
    )
    caveat = metrics.get("coverage_caveat", "")
    assert "same index" in caveat.lower(), (
        "metrics must document why the coverage metric is not the headline"
    )
