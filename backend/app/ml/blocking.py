"""Vehicle blocking: how many buses a timetable actually needs, and how many
kilometres of that are run empty.

A physical bus does not run "a route". It runs a BLOCK: it pulls out of its
home depot, performs a chain of trips back to back, and pulls back in at the
end of the day. Two operational costs follow from how those chains are built:

  * peak vehicle requirement -- the number of buses that must exist to hold
    the timetable, which is what actually sizes the fleet; and
  * dead kilometres -- distance run with no passengers aboard, which for a
    single-route block is the depot -> first origin pull-out plus the last
    destination -> depot pull-in.

Both are computed here from `routes_cleaned.csv` alone (its `trip_list` column
is the real departure timetable) plus the depot list. Nothing here needs data
BMTC has not already published.

WHAT IS MEASURED VS WHAT IS ASSUMED
-----------------------------------
Measured directly from the dataset, exact:
    departure times, trip counts, headways, terminal names, stop sequences.

Assumed, and therefore configurable via BlockingParameters:
    average running speed, dwell time per stop, terminal layover, the maximum
    idle a bus will wait at a terminal before being sent back to the depot,
    and the road-circuity factor that converts straight-line stop-to-stop
    distance into road distance.

Every assumption is surfaced in the report output rather than buried, because
the honest version of this analysis for BMTC is "here is the structure, please
replace our four assumptions with your observed running times". Do not quote
a fuel or rupee figure from these numbers without doing that first.
"""

from __future__ import annotations

import math
import re
from collections import defaultdict
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from .data_loader import RouteRecord
from .distance import GoogleMapsDistanceService
from .text import normalize_text

# "295-B BYB-D48G-AGP" -> depot 48. BMTC encodes the operating depot in ~14% of
# route names as D<number>, optionally suffixed with a schedule letter. The
# numbers seen in the dataset (2..52) match the depot list exactly, which is
# what makes this trustworthy rather than a guess at a naming convention.
_DEPOT_CODE_RE = re.compile(r"\bD(\d{1,2})[A-Z]?\b")

# "D44-ANP10", "D14G-AFG", "D38G-HLG-ANK" -- schedules whose name BEGINS with a
# depot code are the depot's own pull-out/pull-in runs: 325 route-directions and
# 7,123 trips in this dataset, mostly two stops, running "Depot-NN Gate" to a
# terminal and back. These are the only dead kilometres the dataset states
# outright rather than leaving to be inferred from depot geometry, so they are
# tracked separately -- measured dead running is worth far more in a pitch than
# estimated dead running.
_DEPOT_RUN_RE = re.compile(r"^D\d{1,2}[A-Z]?[-\s]", re.IGNORECASE)

EARTH_RADIUS_KM = 6371.0


def haversine_km(origin: tuple[float, float], destination: tuple[float, float]) -> float:
    lat1, lon1 = origin
    lat2, lon2 = destination
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = (
        math.sin(d_lat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(d_lon / 2) ** 2
    )
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def parse_clock(value: str) -> int | None:
    """"17:45:00" -> minutes after midnight. Hours >= 24 mean "next morning",
    which GTFS-style timetables use for post-midnight trips; they are kept as
    is (24:30 -> 1470) so that a block spanning midnight stays contiguous."""
    parts = (value or "").strip().split(":")
    if len(parts) < 2:
        return None
    try:
        hours = int(parts[0])
        minutes = int(parts[1])
    except ValueError:
        return None
    if hours < 0 or not 0 <= minutes < 60:
        return None
    return hours * 60 + minutes


@dataclass(frozen=True)
class BlockingParameters:
    """The four operational assumptions, all replaceable with BMTC's real figures."""

    average_speed_kmph: float = 16.0
    """Bengaluru city-bus running average. BMTC's own scheduled speeds vary by
    corridor and time band; this single figure is the crudest assumption here
    and the first one worth replacing."""

    dwell_minutes_per_stop: float = 0.3
    """Time absorbed boarding/alighting at each intermediate stop."""

    layover_minutes: int = 10
    """Minimum recovery time at a terminal before the bus may start its next
    trip. Real BMTC layovers are crew-agreement dependent."""

    max_terminal_idle_minutes: int | None = None
    """Cap on how long a bus will stand at a terminal before being sent back to
    the depot, ending its block.

    Default None -- NO cap -- because the headline figure this module exists to
    produce is the MINIMUM fleet that can hold the timetable, and imposing an
    idle cap makes the answer a scenario rather than a minimum. With no cap the
    greedy chaining below reduces to the classic maximum-overlap result, which
    is provably optimal; total idle time is reported separately so the
    inefficiency stays visible instead of being hidden inside the bus count.

    Set it (e.g. 45) to model the operationally realistic case where a bus
    waiting hours at a terminal would in practice go home."""

    max_deadhead_km: float = 5.0
    """How far a bus may be repositioned empty between finishing one trip and
    starting the next.

    Without this, a bus can only take a following trip that departs from the
    exact terminal it just arrived at -- and BMTC's network has ~1,400 distinct
    terminals, so most buses arrive somewhere nothing else departs from soon and
    are stranded for the rest of the day. That restriction alone held the fleet
    at roughly twice the hard lower bound. Real schedulers reposition buses a
    few kilometres between duties; this is that, and the empty distance it costs
    is booked as dead km rather than quietly ignored.

    Set to 0 to forbid repositioning entirely."""

    duty_limit_minutes: int = 480
    """Longest block one crew duty is assumed to cover, for the feasibility
    flag in blocks_exceeding_duty(). Eight hours is a placeholder for BMTC's
    real crew-agreement spreadover, which is not in any published dataset."""

    circuity_factor: float = 1.2
    """Straight-line stop-to-stop distance under-states road distance. Because
    consecutive stops are close together the summed chain is already close to
    the road path, so this correction is small."""


@dataclass(frozen=True)
class Depot:
    number: str
    place: str
    zone: str
    point: tuple[float, float] | None = None

    @property
    def label(self) -> str:
        return f"D{self.number} {self.place}"


@dataclass(slots=True)
class Trip:
    route_number: str
    direction_id: int
    depart_minute: int
    arrive_minute: int
    origin: str
    destination: str
    revenue_km: float

    @property
    def duration(self) -> int:
        return self.arrive_minute - self.depart_minute


@dataclass(slots=True)
class Block:
    """One physical bus's day: pull out, run these trips, pull in."""

    trips: list[Trip] = field(default_factory=list)
    pull_out_km: float = 0.0
    pull_in_km: float = 0.0
    deadhead_km: float = 0.0
    """Empty repositioning between trips, within the block."""

    @property
    def revenue_km(self) -> float:
        return sum(trip.revenue_km for trip in self.trips)

    @property
    def dead_km(self) -> float:
        return self.pull_out_km + self.pull_in_km + self.deadhead_km

    @property
    def start_minute(self) -> int:
        return self.trips[0].depart_minute

    @property
    def end_minute(self) -> int:
        return self.trips[-1].arrive_minute

    @property
    def idle_minutes(self) -> int:
        """Time spent waiting at terminals between trips."""
        return sum(
            nxt.depart_minute - cur.arrive_minute
            for cur, nxt in zip(self.trips, self.trips[1:])
        )


MIN_PLAUSIBLE_ROUTE_KM = 1.0
MAX_PLAUSIBLE_ROUTE_KM = 60.0
"""A Bengaluru city bus route runs roughly 10-40 km one way (dataset median is
22 km). Outside this band the computed geometry is not trustworthy -- either
the stop names did not resolve, or the schedule is an outstation service
(the dataset contains a handful: KALABURAGI, DHARMASTHALA) that has no place
in a city fleet calculation. Such routes are flagged and excluded from
headline totals rather than silently averaged in."""


@dataclass(slots=True)
class RouteBlocking:
    route_number: str
    depot: Depot | None
    depot_source: str  # "route_code" (explicit) or "nearest_terminal" (inferred)
    blocks: list[Block]
    trip_count: int
    concurrency_lower_bound: int
    directions: dict[int, float]  # direction_id -> one-way km
    unresolved_geometry: bool
    is_depot_run: bool = False
    geometry_suspect: bool = False

    @property
    def buses_required(self) -> int:
        return len(self.blocks)

    @property
    def is_provably_minimal(self) -> bool:
        """Greedy chaining matched the hard lower bound, so no schedule of this
        timetable can use fewer buses (without deadheading between routes)."""
        return len(self.blocks) == self.concurrency_lower_bound

    @property
    def revenue_km(self) -> float:
        return sum(block.revenue_km for block in self.blocks)

    @property
    def dead_km(self) -> float:
        return sum(block.dead_km for block in self.blocks)

    @property
    def total_km(self) -> float:
        return self.revenue_km + self.dead_km

    @property
    def dead_km_pct(self) -> float:
        total = self.total_km
        return (self.dead_km / total * 100.0) if total else 0.0


def format_clock(minute: int) -> str:
    """1470 -> "24:30". Hours past 24 are kept, GTFS-style, so a trip that
    departs after midnight still reads as part of the previous service day."""
    return f"{minute // 60:02d}:{minute % 60:02d}"


ACTION_SET_HEADWAY = "set_headway"
ACTION_ADD_TRIPS = "add_trips"
ACTION_REMOVE_TRIPS = "remove_trips"


@dataclass(frozen=True)
class ScenarioChange:
    """One "what if" against the published timetable.

    The whole point of the blocking engine is to answer this question before a
    change is made rather than after: a frequency increase is easy to ask for
    and its true cost -- extra buses, from which depot, at what dead-km and
    crew-duty consequence -- is exactly what is hard to see by hand.
    """

    route_number: str
    action: str
    start_minute: int
    end_minute: int
    headway_minutes: int | None = None
    trips: int | None = None
    direction_id: int | None = None
    """None applies the change to both directions -- which is almost always
    what is meant, since a bus that runs out has to come back."""

    def describe(self) -> str:
        window = f"{format_clock(self.start_minute)}-{format_clock(self.end_minute)}"
        scope = "both directions" if self.direction_id is None else f"direction {self.direction_id}"
        if self.action == ACTION_SET_HEADWAY:
            return f"Run {self.route_number} every {self.headway_minutes} min, {window} ({scope})"
        if self.action == ACTION_ADD_TRIPS:
            return f"Add {self.trips} trips to {self.route_number}, {window} ({scope})"
        return f"Remove {self.route_number} trips in {window} ({scope})"


def _rewrite_trip_list(existing: list[str], change: ScenarioChange) -> list[str]:
    minutes = sorted(m for m in (parse_clock(value) for value in existing) if m is not None)
    outside = [m for m in minutes if not (change.start_minute <= m <= change.end_minute)]

    if change.action == ACTION_REMOVE_TRIPS:
        kept = outside
    elif change.action == ACTION_SET_HEADWAY:
        headway = max(int(change.headway_minutes or 0), 1)
        replacement = list(range(change.start_minute, change.end_minute + 1, headway))
        kept = outside + replacement
    elif change.action == ACTION_ADD_TRIPS:
        extra = max(int(change.trips or 0), 0)
        span = max(change.end_minute - change.start_minute, 0)
        # Space the additions evenly across the window rather than bunching
        # them at one end, which is what a scheduler adding capacity would do.
        step = span / extra if extra else 0
        additions = [int(round(change.start_minute + step * i)) for i in range(extra)]
        kept = minutes + additions
    else:
        raise ValueError(f"Unknown scenario action: {change.action!r}")

    return [f"{format_clock(m)}:00" for m in sorted(kept)]


def apply_scenario(
    records: list[RouteRecord], change: ScenarioChange
) -> tuple[list[RouteRecord], dict[str, Any]]:
    """Return a copy of `records` with the change applied to the named route.

    Non-destructive on purpose: the cached baseline plan must stay exactly as
    computed, so a scenario can never contaminate the numbers it is being
    compared against.
    """
    target = change.route_number.strip().casefold()
    updated: list[RouteRecord] = []
    trips_before = 0
    trips_after = 0
    touched = 0

    for route in records:
        matches_route = route.route_number.strip().casefold() == target
        matches_direction = change.direction_id is None or route.direction_id == change.direction_id
        if not (matches_route and matches_direction):
            if matches_route:
                trips_before += len(route.trip_list)
                trips_after += len(route.trip_list)
            updated.append(route)
            continue

        new_trip_list = _rewrite_trip_list(route.trip_list, change)
        trips_before += len(route.trip_list)
        trips_after += len(new_trip_list)
        touched += 1
        # dataclasses.replace re-runs __post_init__, so stop_positions and the
        # other derived fields stay consistent with the new trip list.
        updated.append(
            replace(route, trip_list=new_trip_list, trip_count=len(new_trip_list))
        )

    return updated, {
        "route_directions_changed": touched,
        "trips_before": trips_before,
        "trips_after": trips_after,
        "trips_delta": trips_after - trips_before,
    }


def load_depots(path: str | Path) -> list[Depot]:
    """Read BMTC_depot_place_zone.xlsx.

    The sheet mixes numbered operating depots (2..52) with a handful of named
    bus stands / TTMCs that have no depot number. Both are kept: the named ones
    are real pull-out points even though they are not numbered depots.
    """
    try:
        import openpyxl
    except ImportError as exc:  # pragma: no cover - dependency is declared
        raise RuntimeError(
            "openpyxl is required to read the depot workbook; add it to requirements.txt"
        ) from exc

    workbook = openpyxl.load_workbook(Path(path), data_only=True, read_only=True)
    sheet = workbook.worksheets[0]
    depots: list[Depot] = []
    for index, row in enumerate(sheet.iter_rows(values_only=True)):
        if index == 0 or not row or row[0] is None:
            continue
        number = str(row[0]).strip()
        place = str(row[1] or "").strip()
        zone = str(row[2] or "").strip().strip("-").strip()
        # Rows whose "depot" cell is itself a place name are the unnumbered
        # bus stands; their place column holds a bare "-".
        if not place or place == "-":
            place, number = number, ""
        depots.append(Depot(number=number, place=place, zone=zone))
    workbook.close()
    return depots


class BlockingEngine:
    def __init__(
        self,
        routes: list[RouteRecord],
        depots: list[Depot],
        distance_service: GoogleMapsDistanceService,
        parameters: BlockingParameters | None = None,
    ) -> None:
        self.routes = routes
        self.distance_service = distance_service
        self.parameters = parameters or BlockingParameters()
        self.depots = self._geocode_depots(depots)
        self._depot_by_number = {d.number: d for d in self.depots if d.number}
        self._point_cache: dict[str, tuple[float, float] | None] = {}
        self._geometry_cache: dict[tuple[str, int], float | None] = {}
        self._neighbour_cache: dict[tuple, dict[str, tuple[tuple[str, float], ...]]] = {}

    # ── geometry ────────────────────────────────────────────────────────────
    def _geocode_depots(self, depots: list[Depot]) -> list[Depot]:
        """Give each depot a coordinate by matching its place name against the
        stop-coordinate table. Depot places are Bengaluru localities that almost
        always also exist as a stop name ("Peenya", "Koramangala", "Hebbal"),
        so this reuses the fuzzy resolver rather than needing a new gazetteer."""
        located: list[Depot] = []
        for depot in depots:
            # "Kamakya/Katriguppe", "I.T.I/Dooravani Nagar", "Puttenahalli(Yelahanka)"
            # -- try each alternative spelling the sheet offers before giving up.
            candidates = [
                part.strip()
                for part in re.split(r"[/()]", depot.place)
                if part and part.strip()
            ]
            point = None
            for candidate in candidates:
                point = self.distance_service.resolve_coordinate(candidate)
                if point:
                    break
            located.append(
                Depot(number=depot.number, place=depot.place, zone=depot.zone, point=point)
            )
        return located

    def _stop_point(self, stop: str, near: tuple[float, float] | None = None) -> tuple[float, float] | None:
        if near is None:
            cached = self._point_cache.get(stop)
            if cached is not None or stop in self._point_cache:
                return cached
            point = self.distance_service.resolve_coordinate(stop)
            self._point_cache[stop] = point
            return point
        return self.distance_service.resolve_coordinate(stop, near=near)

    def route_polyline(self, route: RouteRecord) -> list[tuple[float, float] | None]:
        """Resolve every stop on the route to a coordinate, anchored.

        Bengaluru repeats stop names across the city (several "Kodihalli",
        several "Hosahalli"), so resolving each name independently produces a
        polyline that teleports between unrelated suburbs and inflates the route
        length wildly. Two passes fix that: an unanchored pass establishes a
        rough centre for this route, then a sequential pass re-resolves every
        stop against the previous accepted point, which is what the resolver's
        `near` parameter exists for.
        """
        rough = [self._stop_point(stop) for stop in route.stops]
        known = [p for p in rough if p]
        if not known:
            return rough
        centre = (
            sorted(p[0] for p in known)[len(known) // 2],
            sorted(p[1] for p in known)[len(known) // 2],
        )
        anchored: list[tuple[float, float] | None] = []
        previous = centre
        for stop in route.stops:
            point = self._stop_point(stop, near=previous)
            anchored.append(point)
            if point:
                previous = point
        return anchored

    def route_length_km(self, route: RouteRecord) -> float | None:
        key = (route.route_number, route.direction_id)
        if key in self._geometry_cache:
            return self._geometry_cache[key]
        points = [p for p in self.route_polyline(route) if p]
        if len(points) < 2:
            self._geometry_cache[key] = None
            return None
        straight = sum(haversine_km(points[i], points[i + 1]) for i in range(len(points) - 1))
        length = straight * self.parameters.circuity_factor
        self._geometry_cache[key] = length
        return length

    def running_time_minutes(self, route: RouteRecord, length_km: float) -> int:
        driving = (length_km / self.parameters.average_speed_kmph) * 60.0
        dwell = self.parameters.dwell_minutes_per_stop * max(len(route.stops) - 2, 0)
        return max(int(round(driving + dwell)), 1)

    # ── depot assignment ────────────────────────────────────────────────────
    def assign_depot(self, route_group: list[RouteRecord]) -> tuple[Depot | None, str]:
        """Explicit D<n> code wins; otherwise nearest depot to a terminal.

        The inferred branch is a stand-in for the operating-depot mapping BMTC
        holds internally. It is reported separately from the explicit branch so
        that nobody reads an inferred assignment as a stated fact.
        """
        for route in route_group:
            match = _DEPOT_CODE_RE.search(route.route_number.upper())
            if match:
                depot = self._depot_by_number.get(str(int(match.group(1))))
                if depot:
                    return depot, "route_code"

        terminals: list[tuple[float, float]] = []
        for route in route_group:
            for stop in (route.stops[0], route.stops[-1]):
                point = self._stop_point(stop)
                if point:
                    terminals.append(point)
        if not terminals:
            return None, "unknown"

        best: Depot | None = None
        best_km = float("inf")
        for depot in self.depots:
            if not depot.point:
                continue
            distance = min(haversine_km(depot.point, terminal) for terminal in terminals)
            if distance < best_km:
                best, best_km = depot, distance
        return best, "nearest_terminal" if best else "unknown"

    # ── blocking ────────────────────────────────────────────────────────────
    def build_trips(self, route_group: list[RouteRecord]) -> tuple[list[Trip], dict[int, float], bool]:
        trips: list[Trip] = []
        directions: dict[int, float] = {}
        unresolved = False
        for route in route_group:
            length = self.route_length_km(route)
            if length is None:
                unresolved = True
                continue
            directions[route.direction_id] = length
            duration = self.running_time_minutes(route, length)
            for clock in route.trip_list:
                depart = parse_clock(clock)
                if depart is None:
                    continue
                trips.append(
                    Trip(
                        route_number=route.route_number,
                        direction_id=route.direction_id,
                        depart_minute=depart,
                        arrive_minute=depart + duration,
                        origin=normalize_text(route.stops[0]),
                        destination=normalize_text(route.stops[-1]),
                        revenue_km=length,
                    )
                )
        trips.sort(key=lambda t: (t.depart_minute, t.route_number, t.direction_id))
        return trips, directions, unresolved

    @staticmethod
    def concurrency_lower_bound(trips: list[Trip]) -> int:
        """Maximum number of trips simultaneously in progress.

        This is a hard lower bound on the fleet: no scheduling cleverness can
        operate two overlapping trips with one bus. Reported alongside the
        greedy result so the output states whether it is provably optimal
        rather than merely the best this heuristic found.
        """
        events: list[tuple[int, int]] = []
        for trip in trips:
            events.append((trip.depart_minute, 1))
            events.append((trip.arrive_minute, -1))
        events.sort(key=lambda e: (e[0], e[1]))
        current = peak = 0
        for _, delta in events:
            current += delta
            peak = max(peak, current)
        return peak

    def chain_blocks(self, trips: list[Trip]) -> list[Block]:
        """Greedy earliest-available chaining, in departure order.

        A bus already standing at this trip's origin terminal, free for at
        least `layover_minutes` and no longer than `max_terminal_idle_minutes`,
        takes the trip; otherwise a new bus pulls out. Among eligible buses the
        one that has been waiting longest is chosen, which keeps terminals
        turning over and avoids one bus absorbing every trip while others idle.

        Without the idle cap this greedy is optimal for a single route (it
        reduces to the classic maximum-overlap bound). The cap can push it above
        that bound -- deliberately, because a bus held four hours at a terminal
        is not what happens in practice; it goes home, and that costs real dead
        kilometres we want counted.
        """
        blocks: list[Block] = []
        # available[terminal] -> list of (free_at_minute, block)
        available: dict[str, list[tuple[int, Block]]] = defaultdict(list)
        cap = self.parameters.max_terminal_idle_minutes
        layover = self.parameters.layover_minutes
        neighbours = self._terminal_neighbours(trips)
        speed = self.parameters.average_speed_kmph

        for trip in trips:
            chosen: Block | None = None
            deadhead = 0.0
            # Same terminal first (free), then progressively further ones.
            for from_terminal, distance_km in neighbours.get(trip.origin, ((trip.origin, 0.0),)):
                pool = available.get(from_terminal)
                if not pool:
                    continue
                travel = int(round((distance_km / speed) * 60)) if distance_km else 0
                if cap is not None:
                    # A bus that has now been standing longer than the cap has
                    # gone back to its depot; drop it from the pool entirely.
                    # Leaving it in was a real bug: it could never satisfy the
                    # cap again, so it lingered forever, was never reused, and
                    # its block ended after one or two trips -- which is what
                    # inflated the fleet to roughly double the plausible size.
                    stale = [
                        entry for entry in pool
                        if trip.depart_minute - entry[0] > cap
                    ]
                    for entry in stale:
                        pool.remove(entry)

                ready = [
                    (free_at, block)
                    for free_at, block in pool
                    if free_at + layover + travel <= trip.depart_minute
                ]
                if ready:
                    # Longest-waiting bus goes first, so terminals turn over
                    # instead of one bus absorbing every trip.
                    ready.sort(key=lambda item: item[0])
                    free_at, chosen = ready[0]
                    pool.remove((free_at, chosen))
                    deadhead = distance_km
                    break
            if chosen is None:
                chosen = Block()
                blocks.append(chosen)
            elif deadhead:
                chosen.deadhead_km += deadhead
            chosen.trips.append(trip)
            available[trip.destination].append((trip.arrive_minute, chosen))

        return blocks

    def _terminal_neighbours(
        self, trips: list[Trip]
    ) -> dict[str, tuple[tuple[str, float], ...]]:
        """For each origin terminal, the terminals a bus could be repositioned
        from, nearest first, with the same terminal always first at 0 km.

        Cached per distinct terminal set, since chaining consults it once per
        trip and the geometry does not change between calls.
        """
        terminals = sorted({t.origin for t in trips} | {t.destination for t in trips})
        # Key on the full terminal tuple, not a digest of it: {A,B,E} and
        # {A,D,E} share size, first and last, so a shorter key would silently
        # hand one route's neighbour index to another.
        key = tuple(terminals)
        cached = self._neighbour_cache.get(key)
        if cached is not None:
            return cached

        limit = self.parameters.max_deadhead_km
        points = {name: self._stop_point(name) for name in terminals}
        index: dict[str, tuple[tuple[str, float], ...]] = {}
        for name in terminals:
            here = points.get(name)
            nearby: list[tuple[str, float]] = [(name, 0.0)]
            if here and limit > 0:
                for other in terminals:
                    if other == name:
                        continue
                    there = points.get(other)
                    if not there:
                        continue
                    distance = haversine_km(here, there) * self.parameters.circuity_factor
                    if distance <= limit:
                        nearby.append((other, distance))
                nearby.sort(key=lambda item: item[1])
            index[name] = tuple(nearby)
        self._neighbour_cache[key] = index
        return index

    def apply_dead_km(self, blocks: list[Block], depot: Depot | None) -> None:
        """Book the pull-out and pull-in distance for each block."""
        if not depot or not depot.point:
            return
        circuity = self.parameters.circuity_factor
        for block in blocks:
            if not block.trips:
                continue
            origin = self._stop_point_by_norm(block.trips[0].origin)
            destination = self._stop_point_by_norm(block.trips[-1].destination)
            if origin:
                block.pull_out_km = haversine_km(depot.point, origin) * circuity
            if destination:
                block.pull_in_km = haversine_km(destination, depot.point) * circuity

    def _stop_point_by_norm(self, normalized_stop: str) -> tuple[float, float] | None:
        return self._stop_point(normalized_stop)

    # ── top level ───────────────────────────────────────────────────────────
    def block_by_route(self) -> list[RouteBlocking]:
        """Baseline: every route number gets its own dedicated buses.

        Grouping is by route NUMBER, not route-direction: a bus runs out and
        back, so direction 0 and direction 1 belong to the same vehicle's day.
        Blocking them separately would double-count the fleet and hide exactly
        the out-and-back chaining that removes dead kilometres.

        This is deliberately the PESSIMISTIC case. BMTC's 3,940 distinct route
        names collapse to roughly 1,159 numeric bases -- 2,344 of those names
        carry fewer than 5 trips a day and 878 carry exactly one, because they
        are schedule variants of the same corridor rather than separate lines.
        A real bus runs 401-M and then 401-K. Forbidding that here is what makes
        this the baseline to improve on, not an estimate of BMTC's real fleet.
        """
        by_number: dict[str, list[RouteRecord]] = defaultdict(list)
        for route in self.routes:
            by_number[route.route_number].append(route)

        results: list[RouteBlocking] = []
        for route_number, group in sorted(by_number.items()):
            trips, directions, unresolved = self.build_trips(group)
            if not trips:
                continue
            depot, source = self.assign_depot(group)
            blocks = self.chain_blocks(trips)
            self.apply_dead_km(blocks, depot)
            lengths = list(directions.values())
            results.append(
                RouteBlocking(
                    route_number=route_number,
                    depot=depot,
                    depot_source=source,
                    blocks=blocks,
                    trip_count=len(trips),
                    concurrency_lower_bound=self.concurrency_lower_bound(trips),
                    directions=directions,
                    unresolved_geometry=unresolved,
                    is_depot_run=bool(_DEPOT_RUN_RE.match(route_number)),
                    geometry_suspect=any(
                        km < MIN_PLAUSIBLE_ROUTE_KM or km > MAX_PLAUSIBLE_ROUTE_KM
                        for km in lengths
                    ),
                )
            )
        return results

    def all_trips(self, routes: list[RouteRecord] | None = None) -> list[Trip]:
        records = self.routes if routes is None else routes
        by_number: dict[str, list[RouteRecord]] = defaultdict(list)
        for route in records:
            by_number[route.route_number].append(route)
        trips: list[Trip] = []
        for group in by_number.values():
            group_trips, _, _ = self.build_trips(group)
            trips.extend(group_trips)
        trips.sort(key=lambda t: (t.depart_minute, t.route_number, t.direction_id))
        return trips

    def block_interlined(self, routes: list[RouteRecord] | None = None) -> list[Block]:
        """Optimised: one pool of buses serving every trip that chains.

        Identical chaining rule as the baseline -- a bus takes the next trip
        departing from the terminal it just arrived at -- with the single
        restriction removed that the next trip must carry the same route number.
        That restriction is an artefact of how the timetable is *named*, not a
        physical constraint on the vehicle.

        The difference between this and block_by_route() is the interlining
        saving, and it is the one number in this module that needs no data BMTC
        has not already published: no depot mapping, no ridership, no assumed
        running times beyond the ones declared in BlockingParameters.
        """
        return self.chain_blocks(self.all_trips(routes))

    def blocks_exceeding_duty(self, blocks: list[Block], limit_minutes: int) -> int:
        """How many blocks run longer than one crew duty can cover.

        A block is a vehicle's day; a duty is a person's. A re-block that saves
        buses by stretching each one across fourteen hours has not saved
        anything -- it has produced a schedule no crew roster can staff, which
        is the standard reason an otherwise-sound optimisation is rejected by a
        transport operator.

        This is a coarse proxy: BMTC's real duty rules come from crew
        agreements (spreadover limits, break placement, home-depot return) that
        are not in any published dataset. Counting blocks that exceed a plain
        span limit flags the schedules a rostering officer would have to split,
        without pretending to model rules we do not have.
        """
        return sum(
            1 for block in blocks
            if block.trips and (block.end_minute - block.start_minute) > limit_minutes
        )

    def revenue_service(self) -> list[RouteRecord]:
        """Passenger routes only: no depot pull-out schedules, no implausible
        geometry. This is the set any fleet figure should be quoted against."""
        keep: list[RouteRecord] = []
        for route in self.routes:
            if _DEPOT_RUN_RE.match(route.route_number):
                continue
            length = self.route_length_km(route)
            if length is None or not (MIN_PLAUSIBLE_ROUTE_KM <= length <= MAX_PLAUSIBLE_ROUTE_KM):
                continue
            keep.append(route)
        return keep
