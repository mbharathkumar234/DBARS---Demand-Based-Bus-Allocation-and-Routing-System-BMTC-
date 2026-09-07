"""Regression tests for travel query parsing and stop-confidence gating.

Two defects, both reported as "it is not answering the journey plan questions":

1. **The request wrapper was parsed as a stop name.** "plan a journey between
   jalahalli metro station to lulu mall" matched only the bare
   "<origin> to <destination>" pattern, whose lazy left group starts at the
   beginning of the string. The origin became the literal text "plan a journey
   between jalahalli metro station", and the commuter was told no such stop
   existed. "between X to Y" was unsupported -- only "between X and Y" was.

2. **A weak match was planned as fact.** Fixing the parse exposed something
   worse: "lulu mall" resolved to "Forum Mall" -- a different mall -- and
   produced a confident 1-transfer itinerary. The acceptance bar was
   `score >= 0.65 or ratio >= 0.60`, and the second clause matched on the
   shared " mall" suffix alone.
"""

from __future__ import annotations

import pytest

from app.ai.agents.travel_agent import MIN_STOP_CONFIDENCE, travel_assistant


# ── Query parsing ───────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "query,origin,destination",
    [
        # The reported query.
        ("plan a journey between jalahalli metro station to lulu mall",
         "jalahalli metro station", "lulu mall"),
        # "between X and Y" must keep working.
        ("plan a journey between majestic and whitefield", "majestic", "whitefield"),
        ("suggest buses between hebbal and majestic", "hebbal", "majestic"),
        # Other request wrappers.
        ("plan a journey from dasarahalli metro station to iskcon temple",
         "dasarahalli metro station", "iskcon temple"),
        ("show me a bus from hebbal to jayanagar", "hebbal", "jayanagar"),
        ("find me a journey between banashankari to majestic", "banashankari", "majestic"),
        ("plan a route for silk board to marathahalli", "silk board", "marathahalli"),
        # No wrapper at all.
        ("majestic to whitefield", "majestic", "whitefield"),
        ("how do i get from silk board to marathahalli", "silk board", "marathahalli"),
        ("connect silk board and marathahalli", "silk board", "marathahalli"),
        # Transliterated forms.
        ("silk board inda marathahalli ge", "silk board", "marathahalli"),
        ("hebbal se majestic", "hebbal", "majestic"),
    ],
)
def test_origin_and_destination_are_extracted(query: str, origin: str, destination: str) -> None:
    got_origin, got_destination = travel_assistant._extract_stops_from_text(query)
    assert got_origin == origin, f"{query!r} -> origin {got_origin!r}"
    assert got_destination == destination, f"{query!r} -> destination {got_destination!r}"


@pytest.mark.parametrize(
    "query,origin",
    [
        # The preamble stripper must start at a command verb, so stops whose
        # names begin with an ordinary word survive intact.
        ("Forum Mall to Majestic", "Forum Mall"),
        ("Bus Stand to Majestic", "Bus Stand"),
        ("Market Road to Majestic", "Market Road"),
    ],
)
def test_stop_names_starting_with_a_generic_word_are_not_eaten(query: str, origin: str) -> None:
    got_origin, got_destination = travel_assistant._extract_stops_from_text(query)
    assert got_origin == origin
    assert got_destination == "Majestic"


def test_the_request_wrapper_never_becomes_the_origin() -> None:
    origin, _ = travel_assistant._extract_stops_from_text(
        "plan a journey between jalahalli metro station to lulu mall"
    )
    assert origin is not None
    for wrapper_word in ("plan", "journey", "between", "show", "find"):
        assert wrapper_word not in origin.lower()


# ── Stop confidence gating ──────────────────────────────────────────────────

@pytest.mark.parametrize(
    "stop",
    [
        "majestic", "silk board", "marathahalli", "whitefield", "hebbal",
        "iskcon temple", "forum mall", "dasarahalli metro station",
        "jalahalli metro station", "isckon temple", "marathhalli", "koramangla",
    ],
)
def test_real_stops_and_misspellings_are_accepted(stop: str) -> None:
    resolved, score, valid = travel_assistant.resolve_stop(stop)
    assert valid, f"{stop!r} was refused (score {score})"
    assert resolved


@pytest.mark.parametrize(
    "stop",
    ["lulu mall", "phoenix mall", "lulu hypermarket", "shangri la temple", "zzzqqq nagar"],
)
def test_places_absent_from_the_network_are_refused(stop: str) -> None:
    """Refusing is the correct answer; substituting a different place is not."""
    resolved, _, valid = travel_assistant.resolve_stop(stop)
    assert not valid, f"{stop!r} was accepted as {resolved!r}"


def test_lulu_mall_does_not_become_forum_mall() -> None:
    """The specific substitution that produced a confident wrong itinerary."""
    resolved, _, valid = travel_assistant.resolve_stop("lulu mall")
    assert not valid
    assert resolved is None


def test_unrecognised_destination_is_named_and_suggestions_offered() -> None:
    answer = travel_assistant.answer(
        "plan a journey between jalahalli metro station to lulu mall",
        history=None,
        journey_context=None,
    )
    assert answer.route_found is False
    assert answer.confirmation_status == "UNKNOWN"
    # The message must name what was actually unrecognised, not the wrapper.
    assert "lulu mall" in answer.content.lower()
    assert "plan a journey" not in answer.content.lower()
    # And it should point at stops that really exist.
    assert "Closest real stops" in answer.content


def test_a_recognised_journey_still_plans() -> None:
    answer = travel_assistant.answer(
        "plan a journey between jalahalli metro station to majestic",
        history=None,
        journey_context=None,
    )
    assert answer.route_found is True
    assert answer.confirmation_status == "CONFIRMED"
    assert "Jalahalli" in answer.content


def test_confidence_threshold_sits_between_the_measured_populations() -> None:
    """Guards the constant itself: real matches bottom out at 0.828, false ones
    top out at 0.800."""
    assert 0.800 < MIN_STOP_CONFIDENCE <= 0.828
