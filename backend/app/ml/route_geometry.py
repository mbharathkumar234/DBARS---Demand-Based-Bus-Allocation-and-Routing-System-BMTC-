"""Resolving a route's stop names to published stops, in order, anchored.

Bengaluru repeats stop names across the city -- several "Kodihalli", several
"Hosahalli", usually "-halli"/"-pura"/"-nagara" village-suffix names tens of
kilometres apart. Resolving each name in isolation produces a sequence that
teleports between unrelated suburbs and inflates the route length wildly.

Two passes fix it, and the fix is needed identically by the GTFS exporter (to
emit stop_times against the right stop_id) and by vehicle tracking (to project
a bus onto the line it is running), so it lives here rather than being written
twice. BlockingEngine.route_polyline implements the same two-pass idea against
coordinates alone and predates this module.
"""

from __future__ import annotations

from dataclasses import dataclass

from .data_loader import RouteRecord
from .distance import GoogleMapsDistanceService, StopRecord


@dataclass(slots=True)
class RouteGeometry:
    """A route resolved to real stops, with distance along the line."""

    records: list[StopRecord]
    cumulative_km: list[float]
    unresolved: list[str]

    @property
    def points(self) -> list[tuple[float, float]]:
        return [record.point for record in self.records]

    @property
    def total_km(self) -> float:
        return self.cumulative_km[-1] if self.cumulative_km else 0.0

    @property
    def usable(self) -> bool:
        return len(self.records) >= 2 and self.total_km > 0


def resolve_stop_sequence(
    stops: list[str], distance_service: GoogleMapsDistanceService
) -> list[StopRecord | None]:
    """Resolve an ordered list of stop names, each anchored to the previous one.

    Returns a list the SAME LENGTH as the input, with None where a name could
    not be resolved, so callers can keep positional alignment with the names
    they passed in.

    Two passes. A rough unanchored pass establishes the sequence's centre; a
    sequential pass then re-resolves each stop against the last accepted point,
    which is what the resolver's `near` parameter exists for.

    Skipping the anchoring is not a small inaccuracy. Resolving BMTC route
    335-G's stops in isolation drew a 69.4 km line for a 19.2 km route: its
    "Kodihalli" matched the wrong Kodihalli 28 km east, so the drawn path
    spiked out and back as two enormous straight lines. Any code turning stop
    names into geometry must come through here.
    """
    rough = [distance_service.resolve_stop_record(stop) for stop in stops]
    known = [record.point for record in rough if record]
    if not known:
        return [None] * len(stops)

    centre = (
        sorted(point[0] for point in known)[len(known) // 2],
        sorted(point[1] for point in known)[len(known) // 2],
    )

    resolved: list[StopRecord | None] = []
    previous = centre
    for stop in stops:
        record = distance_service.resolve_stop_record(stop, near=previous)
        resolved.append(record)
        if record is not None:
            previous = record.point
    return resolved


def resolve_route_geometry(
    route: RouteRecord,
    distance_service: GoogleMapsDistanceService,
    *,
    circuity_factor: float = 1.0,
    drop_consecutive_duplicates: bool = True,
) -> RouteGeometry:
    """Resolve a route to published stops with distance along the line.

    Names that resolve to nothing are returned separately rather than skipped
    silently -- a caller emitting GTFS needs to count them, and a caller
    computing distance needs to know the line has a hole in it.
    """
    from .blocking import haversine_km

    resolved = resolve_stop_sequence(route.stops, distance_service)

    records: list[StopRecord] = []
    unresolved: list[str] = []
    for stop, record in zip(route.stops, resolved):
        if record is None:
            unresolved.append(stop)
            continue
        # Consecutive duplicates are the two platforms of one physical stop.
        # They add a zero-length segment and a stop_time that neither departs
        # nor arrives anywhere new.
        if drop_consecutive_duplicates and records and records[-1].stop_id == record.stop_id:
            continue
        records.append(record)

    cumulative = [0.0]
    for start, end in zip(records, records[1:]):
        cumulative.append(cumulative[-1] + haversine_km(start.point, end.point) * circuity_factor)

    return RouteGeometry(
        records=records,
        cumulative_km=cumulative if records else [],
        unresolved=unresolved,
    )
