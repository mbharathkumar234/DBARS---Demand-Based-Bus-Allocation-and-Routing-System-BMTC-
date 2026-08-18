"""The vehicle feed interface, and the one observation type everything speaks."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol, runtime_checkable


@dataclass(slots=True)
class VehicleObservation:
    """One sighting of one vehicle, from whatever source produced it."""

    vehicle_id: str
    lat: float
    lon: float
    recorded_at: datetime
    """When the SOURCE observed this, not when we received it.

    This distinction is the whole basis of staleness detection. A feed that
    stalls keeps returning its last payload; if the timestamp were stamped on
    receipt, every stale position would look freshly observed and the map would
    show a fleet of ghosts sitting exactly where they died. Adapters that get
    no timestamp from upstream must say so by leaving this at the source's own
    last-known value rather than substituting now().
    """

    route_number: str | None = None
    direction_id: int | None = None
    bearing: float | None = None
    speed_kmph: float | None = None
    occupancy_pct: float | None = None
    trip_id: str | None = None
    source: str = ""
    is_live: bool = False
    """False marks an observation as synthetic. It travels with the data rather
    than being a property of the endpoint that serves it, so a simulated
    position cannot be laundered into a live-looking one by passing through
    another layer."""

    def age_seconds(self, now: datetime | None = None) -> float:
        reference = now or datetime.now(timezone.utc)
        recorded = self.recorded_at
        if recorded.tzinfo is None:
            recorded = recorded.replace(tzinfo=timezone.utc)
        return (reference - recorded).total_seconds()

    def as_dict(self) -> dict[str, Any]:
        return {
            "vehicle_id": self.vehicle_id,
            "bus_number": self.route_number or self.vehicle_id,
            "route_id": str(self.direction_id if self.direction_id is not None else ""),
            "latitude": round(self.lat, 6),
            "longitude": round(self.lon, 6),
            "heading": self.bearing,
            "speed_kmh": self.speed_kmph,
            "occupancy_pct": self.occupancy_pct,
            "trip_id": self.trip_id,
            "recorded_at": self.recorded_at.isoformat(),
            "age_seconds": round(self.age_seconds(), 1),
            "source": self.source,
            "is_live": self.is_live,
        }


@runtime_checkable
class VehicleFeed(Protocol):
    """A source of vehicle positions.

    Implementations must be honest about `is_live`. Every gate in this codebase
    that decides whether data may be published as real -- the GTFS-realtime
    vehicle feed most of all -- reads that flag and nothing else.
    """

    name: str
    is_live: bool

    async def start(self) -> None:
        """Acquire whatever the feed needs (HTTP client, seed state)."""

    async def stop(self) -> None:
        """Release it."""

    async def poll(self) -> list[VehicleObservation]:
        """Return the current set of observations.

        Called on a timer by the ingest loop. Implementations should return an
        empty list rather than raise on a transient upstream failure; the loop
        treats an exception as a feed error and backs off, which is right for a
        broken feed and wrong for one slow response.
        """
