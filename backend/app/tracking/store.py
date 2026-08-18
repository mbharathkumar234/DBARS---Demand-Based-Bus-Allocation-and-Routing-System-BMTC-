"""Current vehicle state, plus the staleness rule that keeps it honest."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from app.tracking.base import VehicleObservation

logger = logging.getLogger("bmtc.tracking.store")


class VehicleStateStore:
    """Latest observation per vehicle, with stale ones withheld.

    The staleness rule is the important part. A feed that stalls keeps its last
    payload, and rendering that as the current position produces a map of buses
    frozen mid-road that riders will wait for. Anything older than
    `stale_after_seconds` is therefore not returned as a position at all --
    it is counted, so the stall is visible in /tracking/source, but it is not
    shown as if it were now.
    """

    def __init__(self, stale_after_seconds: float = 120.0) -> None:
        self._observations: dict[str, VehicleObservation] = {}
        self.stale_after_seconds = stale_after_seconds
        self.last_poll_at: datetime | None = None
        self.last_poll_count = 0
        self.last_error: str | None = None
        self.polls = 0

    def replace_all(self, observations: list[VehicleObservation]) -> None:
        self._observations = {observation.vehicle_id: observation for observation in observations}
        self.last_poll_at = datetime.now(timezone.utc)
        self.last_poll_count = len(observations)
        self.last_error = None
        self.polls += 1

    def apply(self, observations: list[VehicleObservation]) -> None:
        """Merge observations in, keeping the newest per vehicle.

        Used by the push-ingest path, where each request carries only the
        vehicles that reported, not the whole fleet. An out-of-order arrival
        must not overwrite a newer fix, which is why this compares timestamps
        rather than trusting arrival order.
        """
        for observation in observations:
            existing = self._observations.get(observation.vehicle_id)
            if existing and existing.recorded_at > observation.recorded_at:
                continue
            self._observations[observation.vehicle_id] = observation
        self.last_poll_at = datetime.now(timezone.utc)
        self.last_poll_count = len(observations)
        self.last_error = None
        self.polls += 1

    def record_error(self, message: str) -> None:
        self.last_error = message

    def fresh(self) -> list[VehicleObservation]:
        now = datetime.now(timezone.utc)
        return [
            observation for observation in self._observations.values()
            if observation.age_seconds(now) <= self.stale_after_seconds
        ]

    def stale_count(self) -> int:
        now = datetime.now(timezone.utc)
        return sum(
            1 for observation in self._observations.values()
            if observation.age_seconds(now) > self.stale_after_seconds
        )

    def for_route(self, route_number: str) -> list[VehicleObservation]:
        needle = route_number.strip().casefold()
        return [
            observation for observation in self.fresh()
            if (observation.route_number or "").casefold() == needle
        ]

    def get(self, vehicle_id: str) -> VehicleObservation | None:
        observation = self._observations.get(vehicle_id)
        if observation and observation.age_seconds() <= self.stale_after_seconds:
            return observation
        return None

    def clear(self) -> None:
        self._observations.clear()
        self.last_poll_at = None
        self.last_poll_count = 0
        self.polls = 0

    def health(self) -> dict[str, Any]:
        return {
            "vehicles_fresh": len(self.fresh()),
            "vehicles_stale": self.stale_count(),
            "vehicles_tracked": len(self._observations),
            "last_poll_at": self.last_poll_at.isoformat() if self.last_poll_at else None,
            "last_poll_count": self.last_poll_count,
            "last_poll_age_seconds": (
                round((datetime.now(timezone.utc) - self.last_poll_at).total_seconds(), 1)
                if self.last_poll_at else None
            ),
            "polls": self.polls,
            "last_error": self.last_error,
            "stale_after_seconds": self.stale_after_seconds,
        }


vehicle_store = VehicleStateStore()
