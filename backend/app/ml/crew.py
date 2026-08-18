"""Crew duty scheduling: how many people a timetable needs, not how many buses.

blocking.py answers the vehicle question and stops at the crew one. Its
blocks_exceeding_duty() says exactly why that is not enough:

    "A block is a vehicle's day; a duty is a person's. A re-block that saves
    buses by stretching each one across fourteen hours has not saved anything
    -- it has produced a schedule no crew roster can staff, which is the
    standard reason an otherwise-sound optimisation is rejected by a transport
    operator."

This module replaces that counter with the actual calculation. It takes the
blocks blocking.py produces, cuts them at legal relief opportunities into
PIECES of work, and combines those pieces into DUTIES that a real person could
be rostered onto.

WHAT IS MEASURED VS WHAT IS ASSUMED
-----------------------------------
Measured, inherited from the blocks and ultimately from BMTC's own timetable:
    which trips exist, when they depart and arrive, where they start and end,
    and which of them a single bus runs back to back.

Assumed, and therefore configurable via CrewParameters:
    every crew rule. BMTC's duty rules come from crew agreements -- spreadover
    limits, break placement, relief point lists, sign-on allowances -- and none
    of that is in any published dataset. The defaults below are ordinary
    Indian STU practice, not BMTC's agreement, and the output says so.

The honest version of this analysis for BMTC is "here is the structure, please
replace our seven assumptions with your crew agreement". Do not quote a crew
headcount or a wage figure from these numbers without doing that first.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass, field
from typing import Iterable

from .blocking import Block, Trip, format_clock


@dataclass(frozen=True)
class CrewParameters:
    """The seven crew-agreement assumptions, all replaceable with BMTC's real rules."""

    sign_on_minutes: int = 15
    """Paid time before the first trip: reporting, taking the waybill,
    pre-trip checks. Applied to every piece of work, not only a block's first,
    because a crew taking a bus over at a relief point signs on too."""

    sign_off_minutes: int = 15
    """Paid time after the last trip: handing over, cash remittance."""

    max_continuous_driving_minutes: int = 240
    """Longest stretch of work before a break is required."""

    min_break_minutes: int = 30
    """Idle time at a terminal long enough to count as that break. Anything
    shorter is a layover the crew spends with the bus, not a break."""

    max_working_minutes: int = 480
    """Longest paid working day for one duty, sign-on to sign-off, summed
    across the pieces of a split duty."""

    max_spreadover_minutes: int = 720
    """Longest elapsed time from sign-on to final sign-off, INCLUDING the
    unpaid gap in the middle of a split duty. This is the constraint that
    makes split duties bounded rather than free: a duty that starts at 05:00
    and ends at 22:00 is cheap on paper and unacceptable in practice."""

    min_relief_gap_minutes: int = 10
    """Time needed at a terminal to hand a bus from one crew to the next. A
    trip boundary with less gap than this is not a legal place to cut."""

    allow_split_duties: bool = True
    """Whether two separate pieces may be combined into one duty. Turning this
    off models an operator whose agreement forbids split shifts, and the cost
    of that shows up directly in the duty count."""

    relief_points: frozenset[str] = frozenset()
    """Normalised terminal names where a crew changeover may happen. Empty
    means every terminal is a relief point -- the permissive assumption, which
    UNDERSTATES the duty count. A real relief point list is short (depots and
    a handful of major terminals) and would raise it."""

    @property
    def assumptions(self) -> dict[str, object]:
        return {
            "sign_on_minutes": self.sign_on_minutes,
            "sign_off_minutes": self.sign_off_minutes,
            "max_continuous_driving_minutes": self.max_continuous_driving_minutes,
            "min_break_minutes": self.min_break_minutes,
            "max_working_minutes": self.max_working_minutes,
            "max_spreadover_minutes": self.max_spreadover_minutes,
            "min_relief_gap_minutes": self.min_relief_gap_minutes,
            "allow_split_duties": self.allow_split_duties,
            "relief_points": (
                "every terminal (permissive -- understates duties)"
                if not self.relief_points else f"{len(self.relief_points)} named terminals"
            ),
        }


@dataclass(slots=True)
class DutyPiece:
    """One unbroken stretch of work: take a bus, run these trips, hand it over.

    A piece is the atom of crew scheduling. It cannot be split further (there
    is no legal relief opportunity inside it) and it cannot be shared (one
    person works all of it).
    """

    block_index: int
    trips: list[Trip]
    sign_on_minutes: int
    sign_off_minutes: int

    @property
    def start_minute(self) -> int:
        return self.trips[0].depart_minute - self.sign_on_minutes

    @property
    def end_minute(self) -> int:
        return self.trips[-1].arrive_minute + self.sign_off_minutes

    @property
    def working_minutes(self) -> int:
        return self.end_minute - self.start_minute

    @property
    def driving_minutes(self) -> int:
        """Time actually running trips, excluding sign-on, sign-off and waiting."""
        return sum(trip.duration for trip in self.trips)

    def longest_continuous_stretch(self, min_break_minutes: int) -> int:
        """Longest run of work uninterrupted by a gap that counts as a break.

        Short waits at a terminal are layover -- the crew stays with the bus --
        so they do not reset the clock. Only a gap of at least
        min_break_minutes does.
        """
        longest = 0
        stretch_start = self.trips[0].depart_minute
        for current, following in zip(self.trips, self.trips[1:]):
            gap = following.depart_minute - current.arrive_minute
            if gap >= min_break_minutes:
                longest = max(longest, current.arrive_minute - stretch_start)
                stretch_start = following.depart_minute
        return max(longest, self.trips[-1].arrive_minute - stretch_start)


@dataclass(slots=True)
class Duty:
    """One person's day: one piece, or two with an unpaid gap between them."""

    pieces: list[DutyPiece] = field(default_factory=list)

    @property
    def start_minute(self) -> int:
        return min(piece.start_minute for piece in self.pieces)

    @property
    def end_minute(self) -> int:
        return max(piece.end_minute for piece in self.pieces)

    @property
    def working_minutes(self) -> int:
        """Paid time. The unpaid gap in a split duty is deliberately excluded --
        that is what makes split duties attractive to an operator and unpopular
        with crew, and the spreadover below is what bounds the practice."""
        return sum(piece.working_minutes for piece in self.pieces)

    @property
    def spreadover_minutes(self) -> int:
        return self.end_minute - self.start_minute

    @property
    def is_split(self) -> bool:
        return len(self.pieces) > 1

    @property
    def unpaid_gap_minutes(self) -> int:
        return self.spreadover_minutes - self.working_minutes


@dataclass
class CrewSchedule:
    duties: list[Duty] = field(default_factory=list)
    pieces: int = 0
    blocks: int = 0
    infeasible_blocks: list[str] = field(default_factory=list)
    """Blocks with no legal split at all -- typically a single trip longer than
    one duty, or a block whose terminals never offer a long enough gap. Named,
    not silently dropped: an unstaffable piece of timetable is real information
    for a rostering officer, and hiding it would make the duty count look
    better than the schedule actually is."""

    lower_bound: int = 0
    """Maximum number of pieces in progress simultaneously.

    A hard floor on the crew count, by the same argument
    BlockingEngine.concurrency_lower_bound uses for buses: no rostering
    cleverness can have one person work two pieces at once. Reported alongside
    the achieved figure so the output can say whether it is provably minimal
    rather than merely the best this heuristic found.
    """

    @property
    def duty_count(self) -> int:
        return len(self.duties)

    @property
    def is_provably_minimal(self) -> bool:
        return self.duty_count == self.lower_bound

    @property
    def split_duties(self) -> int:
        return sum(1 for duty in self.duties if duty.is_split)

    @property
    def working_minutes(self) -> int:
        return sum(duty.working_minutes for duty in self.duties)


def piece_concurrency_lower_bound(pieces: Iterable[DutyPiece]) -> int:
    """Peak simultaneous pieces -- the hard floor on duties. See CrewSchedule."""
    events: list[tuple[int, int]] = []
    for piece in pieces:
        events.append((piece.start_minute, 1))
        events.append((piece.end_minute, -1))
    events.sort(key=lambda event: (event[0], event[1]))
    current = peak = 0
    for _, delta in events:
        current += delta
        peak = max(peak, current)
    return peak


def _is_feasible(trips: list[Trip], parameters: CrewParameters) -> bool:
    piece = DutyPiece(
        block_index=-1,
        trips=trips,
        sign_on_minutes=parameters.sign_on_minutes,
        sign_off_minutes=parameters.sign_off_minutes,
    )
    if piece.working_minutes > parameters.max_working_minutes:
        return False
    return piece.longest_continuous_stretch(parameters.min_break_minutes) <= parameters.max_continuous_driving_minutes


def cut_block_into_pieces(
    block: Block, block_index: int, parameters: CrewParameters
) -> list[DutyPiece] | None:
    """Split one vehicle's day into the fewest legal pieces of crew work.

    A cut is legal only between two consecutive trips, at a terminal that is a
    relief point, with at least min_relief_gap_minutes between arrival and the
    next departure -- you cannot hand a bus over in a place nobody can get to,
    or in no time at all.

    Exact, not greedy: a dynamic program over the legal cut positions, because
    greedy cutting ("run until the limit, then cut") can be forced into an
    extra piece when a slightly earlier cut would have fitted the remainder.
    Blocks hold tens of trips, so the O(n^2) is free.

    Returns None if no legal split exists, which the caller reports rather than
    working around.
    """
    trips = block.trips
    if not trips:
        return []

    count = len(trips)
    legal_cut = [False] * (count + 1)
    for index in range(1, count):
        previous, following = trips[index - 1], trips[index]
        if following.depart_minute - previous.arrive_minute < parameters.min_relief_gap_minutes:
            continue
        if parameters.relief_points and previous.destination not in parameters.relief_points:
            continue
        legal_cut[index] = True
    legal_cut[count] = True     # the block always ends

    # best[i] = fewest pieces covering trips[i:], or None if impossible.
    best: list[int | None] = [None] * (count + 1)
    choice: list[int] = [0] * (count + 1)
    best[count] = 0
    for start in range(count - 1, -1, -1):
        for end in range(start + 1, count + 1):
            if not legal_cut[end]:
                continue
            if not _is_feasible(trips[start:end], parameters):
                # Pieces only get longer as `end` grows, and both limits are
                # monotone in length, so nothing beyond this point can fit.
                break
            if best[end] is None:
                continue
            candidate = best[end] + 1
            if best[start] is None or candidate < best[start]:
                best[start] = candidate
                choice[start] = end

    if best[0] is None:
        return None

    pieces: list[DutyPiece] = []
    cursor = 0
    while cursor < count:
        end = choice[cursor]
        pieces.append(
            DutyPiece(
                block_index=block_index,
                trips=trips[cursor:end],
                sign_on_minutes=parameters.sign_on_minutes,
                sign_off_minutes=parameters.sign_off_minutes,
            )
        )
        cursor = end
    return pieces


# How many still-unpaired candidates are examined before settling for the best
# partner found so far. The spreadover window is twelve hours wide, which on a
# full network covers most of the day's ~21,000 pieces, so an unbounded scan is
# quadratic and takes ~36s. Bounding it costs a small number of extra duties
# (an over-estimate, which is the safe direction) and takes ~2s.
MAX_PAIRING_CANDIDATES = 300


def combine_pieces_into_duties(pieces: list[DutyPiece], parameters: CrewParameters) -> list[Duty]:
    """Pair up pieces that one person could work as a single duty.

    Every piece starts as its own duty. Where two pieces fit inside one
    working-time and spreadover budget without overlapping, they are combined,
    which is what an operator means by a split duty.

    Greedy, earliest piece first, taking the partner that uses the most of the
    remaining working-time budget among the candidates examined. Optimal
    pairing here is a maximum-matching problem and not worth solving exactly:
    pairing only ever REDUCES the duty count, so any greedy result is a safe
    over-estimate of the crew required, and over-estimating crew is the right
    direction to be wrong in when the output is a staffing number.

    Two things keep this near-linear rather than quadratic: candidates are
    restricted to the spreadover window by binary search, and already-paired
    pieces are skipped in O(1) through `next_free` rather than re-examined on
    every later piece.
    """
    if not parameters.allow_split_duties or not pieces:
        return [Duty(pieces=[piece]) for piece in pieces]

    ordered = sorted(pieces, key=lambda piece: (piece.start_minute, piece.end_minute))
    starts = [piece.start_minute for piece in ordered]
    count = len(ordered)
    used = [False] * count

    # next_free[i] is the lowest index >= i that is still unpaired, maintained
    # with path compression. Without it, the pieces paired early in the day are
    # re-scanned by every later piece and the whole scan degenerates to O(n^2).
    next_free = list(range(count + 1))

    def first_free(index: int) -> int:
        root = index
        while root < count and used[root]:
            root = next_free[root + 1]
        # Path-compress so the same run of paired pieces is never walked twice.
        while index < root:
            next_free[index], index = root, next_free[index]
        return root

    duties: list[Duty] = []
    for index, piece in enumerate(ordered):
        if used[index]:
            continue
        used[index] = True

        remaining_work = parameters.max_working_minutes - piece.working_minutes
        latest_start = piece.start_minute + parameters.max_spreadover_minutes
        # Only pieces beginning after this one ends can be worked by the same
        # person, and only those starting inside the spreadover window.
        window_end = bisect.bisect_right(starts, latest_start)

        best_partner = -1
        best_work = 0
        examined = 0
        candidate_index = first_free(bisect.bisect_left(starts, piece.end_minute, lo=index + 1))
        while candidate_index < window_end and examined < MAX_PAIRING_CANDIDATES:
            candidate = ordered[candidate_index]
            examined += 1
            if (
                candidate.working_minutes <= remaining_work
                and candidate.end_minute - piece.start_minute <= parameters.max_spreadover_minutes
                and candidate.working_minutes > best_work
            ):
                best_work = candidate.working_minutes
                best_partner = candidate_index
            candidate_index = first_free(candidate_index + 1)

        if best_partner >= 0:
            used[best_partner] = True
            duties.append(Duty(pieces=[piece, ordered[best_partner]]))
        else:
            duties.append(Duty(pieces=[piece]))

    return duties


def schedule_crew(blocks: list[Block], parameters: CrewParameters | None = None) -> CrewSchedule:
    """Turn a set of vehicle blocks into the duties needed to staff them."""
    parameters = parameters or CrewParameters()
    schedule = CrewSchedule(blocks=len(blocks))

    all_pieces: list[DutyPiece] = []
    for index, block in enumerate(blocks):
        if not block.trips:
            continue
        pieces = cut_block_into_pieces(block, index, parameters)
        if pieces is None:
            first, last = block.trips[0], block.trips[-1]
            schedule.infeasible_blocks.append(
                f"{first.route_number} {format_clock(first.depart_minute)}"
                f"-{format_clock(last.arrive_minute)}"
            )
            continue
        all_pieces.extend(pieces)

    schedule.pieces = len(all_pieces)
    schedule.lower_bound = piece_concurrency_lower_bound(all_pieces)
    schedule.duties = combine_pieces_into_duties(all_pieces, parameters)
    return schedule


def summarize(schedule: CrewSchedule, parameters: CrewParameters) -> dict[str, object]:
    """The figures a depot manager actually quotes."""
    duties = schedule.duties
    working = sorted(duty.working_minutes for duty in duties)
    spreads = sorted(duty.spreadover_minutes for duty in duties)
    return {
        "blocks": schedule.blocks,
        "pieces": schedule.pieces,
        "duties": schedule.duty_count,
        "duties_floor": schedule.lower_bound,
        "provably_minimal": schedule.is_provably_minimal,
        # The number a depot manager quotes. Below 1.0 would be impossible;
        # a real STU sits somewhere near 2 once weekly offs and relief crew
        # are added on top of the daily duties counted here.
        "crew_to_bus_ratio": round(schedule.duty_count / schedule.blocks, 2) if schedule.blocks else 0.0,
        "split_duties": schedule.split_duties,
        "split_duty_pct": round(schedule.split_duties / len(duties) * 100, 1) if duties else 0.0,
        "paid_hours": round(schedule.working_minutes / 60, 1),
        "median_working_hours": round(working[len(working) // 2] / 60, 1) if working else 0.0,
        "median_spreadover_hours": round(spreads[len(spreads) // 2] / 60, 1) if spreads else 0.0,
        "max_spreadover_hours": round(spreads[-1] / 60, 1) if spreads else 0.0,
        "unstaffable_blocks": len(schedule.infeasible_blocks),
        "unstaffable_examples": schedule.infeasible_blocks[:10],
        "assumptions": parameters.assumptions,
    }
