"""Guards for crew duty scheduling.

Same split as test_blocking.py. The unit tests pin the cutting and pairing
rules on hand-built blocks where the right answer is countable by hand; the
dataset tests pin the network result against operational plausibility, because
a wrong crew model produces confident, plausible-looking numbers exactly the
way a wrong blocking model did (30,570 buses for a 6,000-bus operator).

The invariants that matter most are the ones a rostering officer would check
first: every trip is worked by exactly one person, and no duty breaks a rule
the parameters declared.
"""

from __future__ import annotations

import pytest

from app.ml.blocking import Block, BlockingParameters, Trip
from app.ml.crew import (
    CrewParameters,
    DutyPiece,
    combine_pieces_into_duties,
    cut_block_into_pieces,
    piece_concurrency_lower_bound,
    schedule_crew,
    summarize,
)


def _trip(depart: int, duration: int, origin: str = "a", destination: str = "b") -> Trip:
    return Trip(
        route_number="T",
        direction_id=0,
        depart_minute=depart,
        arrive_minute=depart + duration,
        origin=origin,
        destination=destination,
        revenue_km=10.0,
    )


def _block(*trips: Trip) -> Block:
    return Block(trips=list(trips))


# ── unit: cutting ───────────────────────────────────────────────────────────
def test_a_short_block_is_one_piece():
    block = _block(_trip(360, 60), _trip(450, 60))
    pieces = cut_block_into_pieces(block, 0, CrewParameters())
    assert len(pieces) == 1
    assert len(pieces[0].trips) == 2


def test_a_long_block_is_cut_into_the_fewest_legal_pieces():
    """Twelve hours of work cannot be one duty, and the cut must land at a
    legal relief opportunity rather than wherever the limit happens to fall.

    Three pieces, not two: with 10-minute turnarounds none of the gaps is long
    enough to count as a break, so the four-hour continuous-driving limit binds
    before the eight-hour working-day limit does. That is the rule doing its
    job -- a crew member who never gets 30 minutes off cannot work eight hours
    straight just because the day is short enough.
    """
    parameters = CrewParameters(
        max_working_minutes=480, max_continuous_driving_minutes=240,
        min_break_minutes=30, min_relief_gap_minutes=10,
    )
    # 06:00 to 18:00, hourly trips of 50 minutes with 10-minute turnarounds.
    block = _block(*[_trip(360 + offset * 60, 50) for offset in range(12)])
    pieces = cut_block_into_pieces(block, 0, parameters)

    assert pieces is not None and len(pieces) == 3
    for piece in pieces:
        assert piece.working_minutes <= parameters.max_working_minutes
        assert piece.longest_continuous_stretch(parameters.min_break_minutes) <= 240
    # Every trip is covered exactly once, in order, with nothing lost at the seam.
    covered = [trip for piece in pieces for trip in piece.trips]
    assert covered == block.trips


def test_a_real_break_lets_one_crew_work_more_trips():
    """The operational consequence of distinguishing a break from a layover:
    the same crew can cover seven trips when the timetable gives them half an
    hour off, and only four when it does not."""
    parameters = CrewParameters(
        max_working_minutes=480, max_continuous_driving_minutes=240,
        min_break_minutes=30, min_relief_gap_minutes=10,
    )
    # Four trips (06:00-09:50, 230 min continuous), a 35-minute break, then
    # three more (10:25-13:15, 170 min continuous). 465 minutes of duty.
    with_break = _block(
        *[_trip(360 + offset * 60, 50) for offset in range(4)],
        *[_trip(625 + offset * 60, 50) for offset in range(3)],
    )
    assert len(cut_block_into_pieces(with_break, 0, parameters)) == 1

    # The same seven trips run back to back exceed the continuous limit and
    # need a second crew, despite being a shorter working day.
    without_break = _block(*[_trip(360 + offset * 60, 50) for offset in range(7)])
    assert len(cut_block_into_pieces(without_break, 0, parameters)) == 2


def test_a_block_with_no_legal_relief_opportunity_is_reported_not_hidden():
    """Trips that run back to back with no gap offer nowhere to hand the bus
    over. Such a block is unstaffable and must be named, because silently
    dropping it makes the duty count look better than the schedule is."""
    parameters = CrewParameters(max_working_minutes=240, min_relief_gap_minutes=10)
    # Six hours of continuous running, each trip departing the instant the
    # previous arrives: no gap anywhere, so no legal cut.
    block = _block(*[_trip(360 + offset * 60, 60) for offset in range(6)])
    assert cut_block_into_pieces(block, 0, parameters) is None

    schedule = schedule_crew([block], parameters)
    assert schedule.duty_count == 0
    assert len(schedule.infeasible_blocks) == 1


def test_relief_points_restrict_where_a_cut_may_happen():
    parameters = CrewParameters(max_working_minutes=300)
    block = _block(
        _trip(360, 60, "depot", "far_end"),
        _trip(480, 60, "far_end", "depot"),
        _trip(600, 60, "depot", "far_end"),
        _trip(720, 60, "far_end", "depot"),
    )
    # With every terminal available, cutting is easy.
    permissive = cut_block_into_pieces(block, 0, parameters)
    assert permissive is not None

    # Restricting relief to "depot" only still works here, because the block
    # returns there -- but the cut must be at a depot arrival.
    restricted = cut_block_into_pieces(block, 0, replace_relief(parameters, {"depot"}))
    assert restricted is not None
    for piece in restricted[:-1]:
        assert piece.trips[-1].destination == "depot"


def replace_relief(parameters: CrewParameters, points: set[str]) -> CrewParameters:
    from dataclasses import replace
    return replace(parameters, relief_points=frozenset(points))


def test_break_resets_the_continuous_driving_clock():
    parameters = CrewParameters(max_continuous_driving_minutes=180, min_break_minutes=30)
    piece = DutyPiece(
        block_index=0,
        # Three hours, a 40-minute break, then three hours more. Six hours of
        # work but never more than three continuously.
        trips=[_trip(360, 180), _trip(580, 180)],
        sign_on_minutes=0,
        sign_off_minutes=0,
    )
    assert piece.longest_continuous_stretch(parameters.min_break_minutes) == 180

    # A 10-minute turnaround is layover, not a break: the crew stays with the
    # bus, so the clock keeps running across it.
    unbroken = DutyPiece(
        block_index=0,
        trips=[_trip(360, 180), _trip(550, 180)],
        sign_on_minutes=0,
        sign_off_minutes=0,
    )
    assert unbroken.longest_continuous_stretch(parameters.min_break_minutes) == 370


# ── unit: pairing ───────────────────────────────────────────────────────────
def _piece(start: int, end: int) -> DutyPiece:
    return DutyPiece(
        block_index=0, trips=[_trip(start, end - start)], sign_on_minutes=0, sign_off_minutes=0
    )


def test_two_short_pieces_become_one_split_duty():
    parameters = CrewParameters(max_working_minutes=480, max_spreadover_minutes=720)
    morning = _piece(360, 600)          # 06:00-10:00, 4h
    evening = _piece(840, 1080)         # 14:00-18:00, 4h
    duties = combine_pieces_into_duties([morning, evening], parameters)

    assert len(duties) == 1
    duty = duties[0]
    assert duty.is_split
    assert duty.working_minutes == 480              # 8h paid
    assert duty.spreadover_minutes == 720           # 06:00 to 18:00
    # The four unpaid hours in the middle are exactly what makes a split duty
    # cheap for the operator and unpopular with crew.
    assert duty.unpaid_gap_minutes == 240


def test_pairing_respects_the_spreadover_ceiling():
    """The constraint that makes split duties bounded rather than free."""
    parameters = CrewParameters(max_working_minutes=480, max_spreadover_minutes=600)
    morning = _piece(360, 600)          # 06:00-10:00
    late = _piece(1020, 1260)           # 17:00-21:00 -- 15h spreadover, too long
    duties = combine_pieces_into_duties([morning, late], parameters)
    assert len(duties) == 2
    assert all(not duty.is_split for duty in duties)


def test_overlapping_pieces_are_never_given_to_one_person():
    parameters = CrewParameters()
    duties = combine_pieces_into_duties([_piece(360, 600), _piece(480, 720)], parameters)
    assert len(duties) == 2


def test_disallowing_split_duties_costs_duties():
    pieces = [_piece(360, 600), _piece(840, 1080)]
    assert len(combine_pieces_into_duties(pieces, CrewParameters(allow_split_duties=True))) == 1
    assert len(combine_pieces_into_duties(pieces, CrewParameters(allow_split_duties=False))) == 2


def test_lower_bound_counts_simultaneous_pieces():
    # Three pieces all in progress at 09:00 need three people, whatever any
    # rostering heuristic does afterwards.
    pieces = [_piece(360, 660), _piece(400, 700), _piece(420, 720), _piece(800, 900)]
    assert piece_concurrency_lower_bound(pieces) == 3


# ── dataset: the real network ───────────────────────────────────────────────
@pytest.fixture(scope="module")
def network_schedule():
    from app.services.blocking_service import _build_engine

    engine = _build_engine(BlockingParameters())
    blocks = engine.block_interlined(engine.revenue_service())
    parameters = CrewParameters()
    return blocks, schedule_crew(blocks, parameters), parameters


def test_every_trip_is_worked_by_exactly_one_person(network_schedule):
    """The invariant a rostering officer checks first. A trip covered twice is
    a duplicated wage cost; a trip covered zero times is a bus with nobody to
    drive it, and both look identical in a summary table."""
    blocks, schedule, _ = network_schedule

    staffed = [id(trip) for duty in schedule.duties for piece in duty.pieces for trip in piece.trips]
    assert len(staffed) == len(set(staffed)), "a trip was assigned to more than one duty"

    unstaffable = len(schedule.infeasible_blocks)
    scheduled_trips = sum(len(block.trips) for block in blocks)
    # Everything except the handful of blocks reported as unstaffable is covered.
    assert len(staffed) <= scheduled_trips
    assert scheduled_trips - len(staffed) < scheduled_trips * 0.01
    assert unstaffable < len(blocks) * 0.01


def test_no_duty_breaks_a_rule_the_parameters_declared(network_schedule):
    _, schedule, parameters = network_schedule
    for duty in schedule.duties:
        assert duty.working_minutes <= parameters.max_working_minutes
        assert duty.spreadover_minutes <= parameters.max_spreadover_minutes
        assert len(duty.pieces) <= 2
        for piece in duty.pieces:
            assert piece.longest_continuous_stretch(parameters.min_break_minutes) <= (
                parameters.max_continuous_driving_minutes
            )
        # Two pieces of one duty must not overlap in time.
        if duty.is_split:
            first, second = sorted(duty.pieces, key=lambda piece: piece.start_minute)
            assert second.start_minute >= first.end_minute


def test_duty_count_never_falls_below_the_hard_floor(network_schedule):
    _, schedule, _ = network_schedule
    assert schedule.duty_count >= schedule.lower_bound
    assert schedule.is_provably_minimal == (schedule.duty_count == schedule.lower_bound)


def test_crew_to_bus_ratio_is_operationally_plausible(network_schedule):
    """A real STU runs roughly two to two-and-a-half daily duties per bus: two
    shifts covering a day longer than one person may work. A model returning
    1.0 has forgotten that buses outlast people; one returning 4 has forgotten
    that duties can be split across blocks."""
    _, schedule, parameters = network_schedule
    summary = summarize(schedule, parameters)
    assert 1.5 <= summary["crew_to_bus_ratio"] <= 3.0
    assert 4.0 <= summary["median_working_hours"] <= 9.0
    assert summary["max_spreadover_hours"] <= parameters.max_spreadover_minutes / 60


def test_forbidding_split_duties_costs_more_crew(network_schedule):
    """The result the whole model exists to produce: a crew agreement rule with
    a number attached to it."""
    blocks, schedule, parameters = network_schedule
    from dataclasses import replace

    strict = replace(parameters, allow_split_duties=False)
    strict_schedule = schedule_crew(blocks, strict)
    assert strict_schedule.duty_count > schedule.duty_count


def test_assumptions_are_reported_with_the_answer(network_schedule):
    """Same discipline as BlockingParameters: an assumption a reader cannot see
    is an assumption they will mistake for a measurement."""
    _, schedule, parameters = network_schedule
    summary = summarize(schedule, parameters)
    assert set(summary["assumptions"]) >= {
        "max_working_minutes",
        "max_spreadover_minutes",
        "max_continuous_driving_minutes",
        "relief_points",
    }
    assert "understates" in summary["assumptions"]["relief_points"]
