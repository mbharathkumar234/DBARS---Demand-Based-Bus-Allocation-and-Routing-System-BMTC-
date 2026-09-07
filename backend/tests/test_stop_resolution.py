"""Regression tests for free-text stop resolution.

Reported as "the copilot is reading wrong": asking for a journey from
"dasarahalli metro station" produced a plan from **Vajarahalli** Metro Station
-- a different station at the opposite end of the Green Line -- and reported it
with full confidence. The AI layer was relaying the deterministic engine
faithfully; `_resolve_stop_name` was the source, so `/predict` and the commuter
prediction page were equally wrong.

Cause: character similarity let a shared *generic* word plus a similar ending
outrank an exact match on the *distinctive* word.

    fuzzy_ratio("dasarahalli metro station", "Vajarahalli Metro Station") = 0.882
    fuzzy_ratio("dasarahalli metro station", "Dasarahalli")               = 0.860

No ratio threshold separates that from a genuine typo -- "majestc" vs
"majestic" scores 0.93 while "dasarahalli" vs "vajarahalli" scores 0.82 -- so
the fix keys on whether the network actually uses the word, and how often.
"""

from __future__ import annotations

import pytest

from app.core.config import settings
from app.ml.predictor import BMTCBusPredictor


@pytest.fixture(scope="module")
def predictor() -> BMTCBusPredictor:
    p = BMTCBusPredictor(settings.dataset_path, settings.artifact_dir)
    p.train()
    return p


# ── The reported bug ────────────────────────────────────────────────────────

def test_dasarahalli_does_not_resolve_to_vajarahalli(predictor: BMTCBusPredictor) -> None:
    resolved, _ = predictor._resolve_stop_name("dasarahalli metro station")
    assert "Vajarahalli" not in resolved
    assert "Dasarahalli" in resolved


def test_dasarahalli_journey_starts_at_dasarahalli(predictor: BMTCBusPredictor) -> None:
    """End to end: the whole journey plan was anchored on the wrong station."""
    result = predictor.predict("dasarahalli metro station", "iskcon temple", limit=3)
    best = result.get("best_match") or {}
    assert "Dasarahalli" in (best.get("matched_current_stop") or "")
    assert "Vajarahalli" not in (best.get("matched_current_stop") or "")


def test_vajarahalli_still_resolves_to_itself(predictor: BMTCBusPredictor) -> None:
    """The fix must not simply invert the confusion."""
    resolved, score = predictor._resolve_stop_name("vajarahalli metro station")
    assert resolved == "Vajarahalli Metro Station"
    assert score == pytest.approx(1.0)


# ── The wider class: a distinctive word must beat a generic one ─────────────

@pytest.mark.parametrize(
    "query,expected_fragment",
    [
        ("dasarahalli metro station", "Dasarahalli"),
        ("jalahalli metro station", "Jalahalli"),
        ("mahalakshmi metro station", "Mahalakshmi"),
        ("peenya metro station", "Peenya"),
        ("nagasandra metro station", "Nagasandra"),
        ("rajajinagar metro station", "Rajajinagar"),
        ("trinity metro station", "Trinity"),
        ("cubbon park metro station", "Cubbon Park"),
        ("lalbagh metro station", "Lalbagh"),
        ("thalaghattapura metro station", "Thalaghattapura"),
    ],
)
def test_place_name_survives_the_generic_suffix(
    predictor: BMTCBusPredictor, query: str, expected_fragment: str
) -> None:
    resolved, _ = predictor._resolve_stop_name(query)
    assert expected_fragment.lower() in resolved.lower(), f"{query!r} resolved to {resolved!r}"


def test_a_purely_generic_stop_never_wins_a_named_query(predictor: BMTCBusPredictor) -> None:
    """This dataset contains a stop named literally "Metro".

    It used to swallow "<place> metro station" queries whose place name was not
    recognised, so "yeshwanthpur metro station" resolved to "Metro".
    """
    for query in [
        "yeshwanthpur metro station",
        "dasarahalli metro station",
        "jalahalli metro station",
    ]:
        resolved, _ = predictor._resolve_stop_name(query)
        assert resolved.strip().lower() != "metro", f"{query!r} resolved to {resolved!r}"


def test_a_query_naming_no_place_can_still_reach_it(predictor: BMTCBusPredictor) -> None:
    """The rule keys on the query naming a place, so a bare "metro" is exempt."""
    resolved, _ = predictor._resolve_stop_name("metro")
    assert resolved.strip().lower() == "metro"


# ── Typo tolerance must be untouched ────────────────────────────────────────

@pytest.mark.parametrize(
    "typo,expected_fragment",
    [
        ("isckon temple", "Iskcon"),
        ("marathhalli", "Marathahalli"),
        ("koramangla", "Koramangala"),
        ("indranagar", "Indiranagar"),
        ("silk board", "Silk Board"),
    ],
)
def test_misspellings_still_resolve(
    predictor: BMTCBusPredictor, typo: str, expected_fragment: str
) -> None:
    resolved, _ = predictor._resolve_stop_name(typo)
    assert expected_fragment.lower() in resolved.lower(), f"{typo!r} resolved to {resolved!r}"


def test_a_dataset_misspelling_defers_to_the_common_spelling(
    predictor: BMTCBusPredictor,
) -> None:
    """The dataset contains "KSRTC-BANASHANKRI BUS STAND".

    That makes "banashankri" a real token, so an early version of the fix let
    the typo outrank the correctly spelled stop. Frequency decides: the rare
    spelling (1 stop) defers to the common one (18).
    """
    resolved, _ = predictor._resolve_stop_name("banashankri")
    assert "Banashankari" in resolved


def test_a_common_word_is_not_absorbed_by_a_rare_lookalike(
    predictor: BMTCBusPredictor,
) -> None:
    """"jalahalli" (15 stops) must not defer to "alahalli" (1), despite a 0.94
    character ratio between them -- the frequency comparison is one-way."""
    resolved, _ = predictor._resolve_stop_name("jalahalli")
    assert "alahalli" in resolved.lower()
    assert resolved.strip().lower() != "alahalli"


def test_anchor_tokens_are_empty_for_an_unknown_word(predictor: BMTCBusPredictor) -> None:
    """Nothing recognised means plain fuzzy matching stays in charge."""
    assert predictor._anchor_place_tokens({"zzzznotaplacezzzz"}) == frozenset()
    assert predictor._anchor_place_tokens(set()) == frozenset()
