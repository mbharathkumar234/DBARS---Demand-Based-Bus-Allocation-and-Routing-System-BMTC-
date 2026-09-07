"""Regression tests for conversational context bleeding into the wrong intent.

Reported as "it is answering the previous question": after planning a journey,
asking "how crowded is 290-T SBS-HSH" replayed the earlier journey plan
(Iskcon Temple -> Marathahalli) instead of answering about crowding.

Two causes, both circular in the same way:

1. `extract_parameters` inherits origin and destination from the active journey
   whenever a turn names none. The orchestrator then classified the turn as a
   travel query *because* origin and destination were set -- so the inheritance
   manufactured the evidence that justified it. Any off-topic turn in a session
   with prior journey context became a journey re-plan.

2. "how crowded is <route>" matched none of the operations keywords, so nothing
   competed with the travel classification.

Fixing those exposed a third defect: the crowding branch extracted the route
with `(?:route|bus|for)\\s+(\\S+)` and fell back to a hardcoded "500-D" when
that failed. A question about 290-T SBS-HSH was answered, with metrics, about
a different route.
"""

from __future__ import annotations

import pytest

from app.ai.agents.operations_agent import operations_assistant
from app.ai.agents.travel_agent import travel_assistant
from app.ai.models import GroundingConfidence
from app.core.config import settings
from app.ml.predictor import BMTCBusPredictor
from app.ai.tools.routing_tools import get_shared_predictor, set_shared_predictor


@pytest.fixture(scope="module", autouse=True)
def _shared_predictor():
    try:
        get_shared_predictor()
    except Exception:  # pragma: no cover - defensive
        predictor = BMTCBusPredictor(settings.dataset_path, settings.artifact_dir)
        predictor.train()
        set_shared_predictor(predictor)


# ── Inherited context must not look like a journey request ──────────────────

JOURNEY_CONTEXT = {"origin": "Iskcon Temple", "destination": "Marathahalli"}


def test_a_turn_naming_no_stops_is_not_treated_as_a_journey_request() -> None:
    params = travel_assistant.extract_parameters(
        "how crowded is 290-T SBS-HSH", history=None, journey_context=JOURNEY_CONTEXT
    )
    # Context inheritance still happens -- follow-ups depend on it ...
    assert params.origin == "Iskcon Temple"
    # ... but it must be distinguishable from the user naming those stops.
    assert params.stops_from_query is False


def test_a_turn_naming_both_stops_is_marked_as_such() -> None:
    params = travel_assistant.extract_parameters(
        "plan a journey from majestic to whitefield", history=None, journey_context=JOURNEY_CONTEXT
    )
    assert params.stops_from_query is True


@pytest.mark.parametrize(
    "query",
    [
        "how crowded is 290-T SBS-HSH",
        "are there any service alerts",
        "how full is 335-E",
    ],
)
def test_offtopic_turns_do_not_inherit_journey_stops_as_evidence(query: str) -> None:
    params = travel_assistant.extract_parameters(
        query, history=None, journey_context=JOURNEY_CONTEXT
    )
    assert params.stops_from_query is False


# ── Route number resolution ─────────────────────────────────────────────────

@pytest.mark.parametrize(
    "query,expected",
    [
        ("how crowded is 290-T SBS-HSH", "290-T SBS-HSH"),
        ("how crowded is 335-E", "335-E"),
        ("crowding for route 500-D", "500-D"),
        ("is KIA-8E crowded", "KIA-8E"),
        ("how full is K-2", "K-2"),
        ("passenger load on 401-KB YTTMC-AIT", "401-KB YTTMC-AIT"),
    ],
)
def test_route_numbers_are_resolved_against_the_catalogue(query: str, expected: str) -> None:
    assert operations_assistant._extract_route_number(query) == expected


def test_the_longest_matching_route_wins() -> None:
    """"290" is also a real route, so a shorter match must not win."""
    assert operations_assistant._extract_route_number("how crowded is 290-T SBS-HSH") != "290"


@pytest.mark.parametrize("query", ["how crowded is 9999-ZZ", "how crowded is the bus"])
def test_an_unnamed_or_unknown_route_resolves_to_nothing(query: str) -> None:
    assert operations_assistant._extract_route_number(query) is None


def test_crowding_never_falls_back_to_a_hardcoded_route() -> None:
    """The old code answered about "500-D" whenever extraction failed."""
    answer = operations_assistant.answer("how crowded is the bus")
    assert answer.confidence == GroundingConfidence.UNKNOWN
    assert "500-D" not in answer.operational_summary
    assert "could not identify which BMTC route" in answer.operational_summary


def test_crowding_answers_about_the_route_that_was_asked_about() -> None:
    answer = operations_assistant.answer("how crowded is 290-T SBS-HSH")
    assert answer.key_metrics.get("route_number") == "290-T SBS-HSH"
    assert "290-T SBS-HSH" in answer.operational_summary


def test_absent_crowd_reports_are_not_reported_as_normal() -> None:
    """No submissions means no measurement, not a low one."""
    answer = operations_assistant.answer("how crowded is 290-T SBS-HSH")
    if answer.key_metrics.get("crowding_status") == "insufficient_data":
        assert "not enough recent commuter crowd reports" in answer.operational_summary
        assert "sustained peak crowding" not in answer.operational_summary
