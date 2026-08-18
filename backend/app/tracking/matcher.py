"""Projecting vehicles onto routes, matching them to trips, and real ETAs.

Three things live here because they are one chain of reasoning:

  1. project a vehicle onto its route's polyline (where along the route is it?)
  2. match it to a scheduled trip (which trip is it running, and is it late?)
  3. sum the remaining distance to a stop (when will it actually arrive?)

The ETA this produces replaces a straight-line haversine multiplied by 1.4 and
divided by the vehicle's current speed. That estimate is wrong in a specific
and misleading way: it measures through buildings, ignores the route entirely,
and is confidently precise. A bus 400 m away as the crow flies can be fifteen
minutes from you if the route loops; the old estimate said two.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Sequence

from app.ml.blocking import Trip, haversine_km

logger = logging.getLogger("bmtc.tracking.matcher")

Point = tuple[float, float]


@dataclass(slots=True)
class Projection:
    """Where a vehicle sits along a route, and how far off it is."""

    segment_index: int
    distance_along_km: float
    offset_km: float
    """Distance from the vehicle to the route line. A large offset means the
    vehicle is not on this route -- diverted, mis-tagged, or a different
    service -- and callers should treat the projection as unreliable rather
    than reporting a confident position along a line the bus is nowhere near.
    """


def project_onto_polyline(point: Point, polyline: Sequence[Point], cumulative_km: Sequence[float]) -> Projection | None:
    """Nearest point on the route line, in route distance.

    Walks every segment rather than assuming the vehicle is near its last known
    position: a feed can drop out for minutes, and a route that doubles back on
    itself defeats any local search. Routes here are tens of points, so the
    exhaustive scan is cheaper than the bookkeeping to avoid it.
    """
    if len(polyline) < 2:
        return None

    best: Projection | None = None
    for index in range(len(polyline) - 1):
        start, end = polyline[index], polyline[index + 1]
        segment_km = cumulative_km[index + 1] - cumulative_km[index]
        if segment_km <= 0:
            continue

        # Fraction along the segment of the closest point, in flat lat/lon
        # space. Over a segment of a few hundred metres the distortion from
        # treating degrees as planar is far below the GPS noise floor.
        dx, dy = end[0] - start[0], end[1] - start[1]
        denominator = dx * dx + dy * dy
        if denominator <= 0:
            continue
        t = ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / denominator
        t = max(0.0, min(1.0, t))
        nearest = (start[0] + t * dx, start[1] + t * dy)

        offset = haversine_km(point, nearest)
        if best is None or offset < best.offset_km:
            best = Projection(
                segment_index=index,
                distance_along_km=cumulative_km[index] + t * segment_km,
                offset_km=offset,
            )
    return best


# A vehicle further than this from the route line is not running it. Bengaluru
# stop coordinates and the stop-to-stop polyline together are good to a few
# hundred metres, so this is generous enough to tolerate that plus GPS noise
# and narrow enough to reject a bus on a parallel corridor.
MAX_ROUTE_OFFSET_KM = 1.5


@dataclass(slots=True)
class TripMatch:
    trip: Trip
    projection: Projection
    schedule_deviation_minutes: float
    """Positive means late, negative means early. This is the number a
    controller acts on, and it is the first thing that becomes available the
    moment vehicle positions are real."""

    confidence: str


def match_trip(
    observation_minute: int,
    projection: Projection,
    route_length_km: float,
    candidates: Sequence[Trip],
    *,
    tolerance_minutes: int = 30,
) -> TripMatch | None:
    """Which scheduled trip is this vehicle running?

    A vehicle a given fraction of the way along the route should, if it is on
    time, be that same fraction of the way through its trip's duration. The
    trip whose implied progress best matches the observed progress wins.

    Returns None rather than guessing when the vehicle is too far off the route
    or no trip is plausibly in progress. An unmatched vehicle is still shown on
    the map; it simply has no schedule adherence figure, which is honest -- a
    wrong trip match produces a confident and completely fictional "8 minutes
    late" that a controller would act on.
    """
    if projection.offset_km > MAX_ROUTE_OFFSET_KM or route_length_km <= 0:
        return None

    progress = min(max(projection.distance_along_km / route_length_km, 0.0), 1.0)

    best: TripMatch | None = None
    for trip in candidates:
        duration = trip.duration
        if duration <= 0:
            continue
        # Where this trip should be right now, if running to time.
        expected_progress = (observation_minute - trip.depart_minute) / duration
        if not -0.5 <= expected_progress <= 1.5:
            continue

        # Convert the progress gap into minutes of lateness: the vehicle is
        # where the trip expects to be `deviation` minutes from now.
        deviation = (expected_progress - progress) * duration
        if abs(deviation) > tolerance_minutes:
            continue

        if best is None or abs(deviation) < abs(best.schedule_deviation_minutes):
            best = TripMatch(
                trip=trip,
                projection=projection,
                schedule_deviation_minutes=round(deviation, 1),
                confidence="high" if abs(deviation) <= 5 else "medium",
            )
    return best


@dataclass(slots=True)
class EtaEstimate:
    minutes: float
    low_minutes: int
    high_minutes: int
    remaining_km: float
    confidence: str
    basis: str

    def as_dict(self) -> dict:
        return {
            "eta_minutes": round(self.minutes, 1),
            "eta_range": f"{self.low_minutes}-{self.high_minutes} min",
            "distance_km": round(self.remaining_km, 2),
            "confidence": self.confidence,
            "basis": self.basis,
        }


def estimate_arrival(
    projection: Projection,
    target_distance_km: float,
    *,
    stops_between: int,
    observed_speed_kmph: float | None,
    segment_speed_kmph: float | None = None,
    default_speed_kmph: float = 16.0,
    dwell_minutes_per_stop: float = 0.3,
) -> EtaEstimate | None:
    """Time to reach a point further along the route.

    Returns None if the target is behind the vehicle -- a bus that has already
    passed your stop is not arriving in negative minutes, and the caller should
    look for the next vehicle instead.

    The confidence label is derived from which speed source was available, not
    guessed. That is the honest way to publish an estimate built on a fallback
    chain: a rider told "8-14 min, low confidence" can plan; one told "11 min"
    by a number that came from a hard-coded default cannot.
    """
    remaining_km = target_distance_km - projection.distance_along_km
    if remaining_km < 0:
        return None

    if segment_speed_kmph and segment_speed_kmph > 1:
        speed, confidence, basis = segment_speed_kmph, "high", "observed speed on this stretch"
    elif observed_speed_kmph and observed_speed_kmph > 1:
        speed, confidence, basis = observed_speed_kmph, "medium", "this vehicle's current speed"
    else:
        speed, confidence, basis = default_speed_kmph, "low", "assumed average running speed"

    minutes = (remaining_km / speed) * 60 + dwell_minutes_per_stop * max(stops_between, 0)

    # The band widens as confidence falls, which is the point: a low-confidence
    # estimate that quotes a two-minute window is worse than no estimate.
    spread = {"high": 0.15, "medium": 0.25, "low": 0.40}[confidence]
    return EtaEstimate(
        minutes=minutes,
        low_minutes=max(1, int(minutes * (1 - spread))),
        high_minutes=max(2, int(minutes * (1 + spread)) + 1),
        remaining_km=remaining_km,
        confidence=confidence,
        basis=basis,
    )


def cumulative_distances(polyline: Sequence[Point]) -> list[float]:
    cumulative = [0.0]
    for start, end in zip(polyline, polyline[1:]):
        cumulative.append(cumulative[-1] + haversine_km(start, end))
    return cumulative
