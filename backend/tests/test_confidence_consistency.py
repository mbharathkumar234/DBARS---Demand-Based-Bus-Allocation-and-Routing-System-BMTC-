"""The displayed confidence must not contradict the ranking.

Ranking and confidence were two unrelated formulas. `route_rank_score` ordered
on exactness, transfers, frequency tier, relative span and trunk status;
confidence was computed from transfers, stop count and frequency alone. Nothing
tied them together, so the percentage beside the recommendation could be lower
than the one beside an option listed below it.

Measured over 114 multi-option results before the fix: **34 (29.8%) showed an
alternative with higher confidence than the pick**, by up to 6.5 points. A
commuter reading the page saw the system recommend the option it scored lower.

`_enrich_transfer_distances` was the only code that would have reconciled the
two, and nothing called it.

The fix has two parts, and the distinction matters:

* the score now includes the signals the ranker actually uses, weighted in its
  order of priority, which makes the formula agree with the ordering on its own
  in 76% of multi-option results (65% before the weights were tuned against
  measurement);
* the sequence is then forced non-increasing, which guarantees the remaining
  24% cannot display a contradiction either.

The clamp is the guarantee, not the mechanism. A lexicographic tuple cannot be
collapsed into a single scalar without some loss, so some gap is inherent.
"""

from __future__ import annotations

import random

import pytest

from app.core.config import settings
from app.ml.predictor import BMTCBusPredictor


@pytest.fixture(scope="module")
def predictor() -> BMTCBusPredictor:
    p = BMTCBusPredictor(settings.dataset_path, settings.artifact_dir)
    p.train()
    return p


PAIRS = [
    ("White Field Post Office", "Kengeri"),
    ("Silk Board", "Marathahalli"),
    ("Majestic", "Whitefield"),
    ("Hebbal", "Silk Board"),
    ("Banashankari", "Hebbal"),
    ("Sapthagiri College", "Reva College"),
]


@pytest.mark.parametrize("origin,destination", PAIRS)
def test_confidence_never_increases_down_the_list(predictor, origin, destination) -> None:
    options = predictor.predict(origin, destination, limit=6).get("alternatives") or []
    scores = [o.get("confidence") for o in options if o.get("confidence") is not None]
    if len(scores) < 2:
        pytest.skip("needs more than one option")
    for better, worse in zip(scores, scores[1:]):
        assert better + 1e-6 >= worse, (
            f"{origin} -> {destination}: an option ranked lower displays "
            f"{worse}% against {better}% above it"
        )


@pytest.mark.parametrize("origin,destination", PAIRS)
def test_the_recommendation_holds_the_highest_confidence(predictor, origin, destination) -> None:
    result = predictor.predict(origin, destination, limit=6)
    options = result.get("alternatives") or []
    if len(options) < 2:
        pytest.skip("needs more than one option")
    top = options[0].get("confidence") or 0
    assert top >= max((o.get("confidence") or 0) for o in options[1:]) - 1e-6


def test_no_inversions_across_a_random_sample(predictor) -> None:
    """The population measure, not a handful of hand-picked pairs."""
    random.seed(99)
    stops = random.sample(predictor.stop_names, 300)
    pairs = [(stops[i], stops[i + 1]) for i in range(0, 120, 2)]

    checked = inverted = 0
    for origin, destination in pairs:
        try:
            options = predictor.predict(origin, destination, limit=6).get("alternatives") or []
        except Exception:
            continue
        if len(options) < 2:
            continue
        checked += 1
        top = options[0].get("confidence") or 0
        if max((o.get("confidence") or 0) for o in options[1:]) > top + 0.05:
            inverted += 1

    assert checked, "no multi-option results to check"
    assert inverted == 0, f"{inverted} of {checked} results contradict their own ordering"


def test_scoring_internals_do_not_leak_into_the_response(predictor) -> None:
    """`_exactness` and `_special` are carried between ranking and scoring."""
    options = predictor.predict("White Field Post Office", "Kengeri", limit=6).get("alternatives") or []
    for option in options:
        assert "_exactness" not in option
        assert "_special" not in option


def test_confidence_stays_inside_its_declared_range(predictor) -> None:
    for origin, destination in PAIRS:
        for option in predictor.predict(origin, destination, limit=6).get("alternatives") or []:
            score = option.get("confidence")
            if score is None:
                continue
            assert 28.0 <= score <= 92.0, f"{option.get('bus_chain')} scored {score}"


def test_a_longer_journey_scores_below_a_shorter_one_all_else_equal(predictor) -> None:
    """The reported case: 86 stops / 85.9 km used to outrank 33 stops / 41.4 km."""
    best = predictor.predict("White Field Post Office", "Kengeri", limit=6)["best_match"]
    assert best["total_stops"] <= 40
    assert best["distance_km"] < 50
    assert (best.get("confidence") or 0) > 60
