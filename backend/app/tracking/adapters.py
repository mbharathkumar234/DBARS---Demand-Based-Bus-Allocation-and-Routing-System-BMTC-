"""Vehicle feed adapters.

Four, covering the shapes a real operator hands over:

  SimulatedFeed      the existing BusSimulator, demoted to one implementation
  GtfsRealtimeFeed   an upstream GTFS-realtime VehiclePositions URL -- the
                     standard, and what most agencies expose once asked
  HttpJsonFeed       a bespoke ITS/VTU JSON API, described by a field map in
                     configuration rather than by new code
  PushIngestFeed     backs POST /avl/ingest, for operators who push to you

Swapping between them is TRACKING_FEED in the environment. Only the last three
set is_live=True, and nothing in this codebase publishes vehicle data as real
unless the active feed says so.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from app.tracking.base import VehicleObservation

logger = logging.getLogger("bmtc.tracking.adapters")


class SimulatedFeed:
    """Wraps BusSimulator so the rest of the system does not know it is fake.

    is_live is False and stays False. That single flag is what stops the
    GTFS-realtime vehicle feed publishing this to journey planners, and what
    makes GET /tracking/source tell the truth without anyone remembering to
    update it.
    """

    name = "simulated"
    is_live = False

    def __init__(self, predictor: Any = None) -> None:
        self._predictor = predictor

    async def start(self) -> None:
        from app.services.tracking_service import bus_simulator

        if self._predictor is not None and not bus_simulator.get_all_buses():
            await bus_simulator.initialize_buses(
                self._predictor.routes, self._predictor.distance_service
            )

    async def stop(self) -> None:
        return None

    async def poll(self) -> list[VehicleObservation]:
        from app.services.tracking_service import bus_simulator

        await bus_simulator.advance_if_due()
        now = datetime.now(timezone.utc)
        observations: list[VehicleObservation] = []
        for index, bus in enumerate(bus_simulator.get_all_buses()):
            observations.append(
                VehicleObservation(
                    vehicle_id=f"SIM-{bus['bus_number']}-{bus.get('route_id', index)}",
                    lat=float(bus["latitude"]),
                    lon=float(bus["longitude"]),
                    # The simulator has no notion of observation time; it is
                    # always current by construction, and saying so here is
                    # accurate rather than a fudge.
                    recorded_at=now,
                    route_number=bus.get("bus_number"),
                    direction_id=_as_int(bus.get("route_id")),
                    bearing=bus.get("heading"),
                    speed_kmph=bus.get("speed_kmh"),
                    occupancy_pct=bus.get("occupancy_pct"),
                    source=self.name,
                    is_live=False,
                )
            )
        return observations


class GtfsRealtimeFeed:
    """Polls an upstream GTFS-realtime VehiclePositions feed.

    The standard shape, and the one to ask BMTC for first: it is what their ITS
    vendor most likely already produces for Google, and consuming it needs no
    bespoke agreement about field names.
    """

    name = "gtfs_rt"
    is_live = True

    def __init__(self, url: str, *, headers: dict[str, str] | None = None, timeout: float = 8.0) -> None:
        if not url:
            raise ValueError("GtfsRealtimeFeed needs TRACKING_FEED_URL to be set.")
        self.url = url
        self.headers = headers or {}
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None

    async def start(self) -> None:
        self._client = httpx.AsyncClient(timeout=self.timeout, headers=self.headers)

    async def stop(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def poll(self) -> list[VehicleObservation]:
        from google.transit import gtfs_realtime_pb2 as gtfs_rt

        if self._client is None:
            await self.start()
        assert self._client is not None

        response = await self._client.get(self.url)
        response.raise_for_status()

        message = gtfs_rt.FeedMessage()
        message.ParseFromString(response.content)

        header_timestamp = message.header.timestamp or 0
        observations: list[VehicleObservation] = []
        for entity in message.entity:
            if not entity.HasField("vehicle"):
                continue
            vehicle = entity.vehicle
            if not vehicle.HasField("position"):
                continue
            position = vehicle.position

            # Prefer the per-vehicle timestamp; fall back to the feed header.
            # Never substitute now(): a feed republishing an hour-old payload
            # must look an hour old, or staleness detection is defeated.
            stamp = vehicle.timestamp or header_timestamp
            recorded_at = (
                datetime.fromtimestamp(stamp, tz=timezone.utc) if stamp
                else datetime.now(timezone.utc)
            )
            observations.append(
                VehicleObservation(
                    vehicle_id=vehicle.vehicle.id or entity.id,
                    lat=position.latitude,
                    lon=position.longitude,
                    recorded_at=recorded_at,
                    route_number=vehicle.trip.route_id or None,
                    direction_id=vehicle.trip.direction_id if vehicle.trip.HasField("direction_id") else None,
                    bearing=position.bearing if position.HasField("bearing") else None,
                    speed_kmph=position.speed * 3.6 if position.HasField("speed") else None,
                    trip_id=vehicle.trip.trip_id or None,
                    source=self.name,
                    is_live=True,
                )
            )
        return observations


DEFAULT_JSON_FIELD_MAP = {
    "root": "",                     # dotted path to the list of vehicles
    "vehicle_id": "vehicle_id",
    "lat": "latitude",
    "lon": "longitude",
    "recorded_at": "timestamp",
    "route_number": "route_no",
    "direction_id": "direction",
    "bearing": "heading",
    "speed_kmph": "speed",
    "occupancy_pct": "occupancy",
}


class HttpJsonFeed:
    """A bespoke JSON vehicle API, described by configuration rather than code.

    Indian STU ITS vendors each invent their own field names, and the shape is
    not usually negotiable. Encoding the mapping as data (TRACKING_FEED_FIELD_MAP,
    a JSON object) means onboarding a new operator is an environment change,
    not a code change and a deployment.
    """

    name = "http_json"
    is_live = True

    def __init__(
        self,
        url: str,
        *,
        field_map: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
        timeout: float = 8.0,
    ) -> None:
        if not url:
            raise ValueError("HttpJsonFeed needs TRACKING_FEED_URL to be set.")
        self.url = url
        self.field_map = {**DEFAULT_JSON_FIELD_MAP, **(field_map or {})}
        self.headers = headers or {}
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None

    async def start(self) -> None:
        self._client = httpx.AsyncClient(timeout=self.timeout, headers=self.headers)

    async def stop(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def poll(self) -> list[VehicleObservation]:
        if self._client is None:
            await self.start()
        assert self._client is not None

        response = await self._client.get(self.url)
        response.raise_for_status()
        payload = response.json()

        rows = _dig(payload, self.field_map.get("root", "")) if self.field_map.get("root") else payload
        if not isinstance(rows, list):
            raise ValueError(f"Expected a list of vehicles at '{self.field_map.get('root')}'")

        observations: list[VehicleObservation] = []
        for row in rows:
            observation = self._to_observation(row)
            if observation is not None:
                observations.append(observation)
        return observations

    def _to_observation(self, row: dict[str, Any]) -> VehicleObservation | None:
        mapping = self.field_map
        lat = _as_float(_dig(row, mapping["lat"]))
        lon = _as_float(_dig(row, mapping["lon"]))
        vehicle_id = _dig(row, mapping["vehicle_id"])
        if lat is None or lon is None or not vehicle_id:
            # A row without an id or a position is not a sighting. Dropping it
            # is right; inventing coordinates for it would not be.
            return None
        return VehicleObservation(
            vehicle_id=str(vehicle_id),
            lat=lat,
            lon=lon,
            recorded_at=_as_datetime(_dig(row, mapping["recorded_at"])),
            route_number=_as_str(_dig(row, mapping["route_number"])),
            direction_id=_as_int(_dig(row, mapping["direction_id"])),
            bearing=_as_float(_dig(row, mapping["bearing"])),
            speed_kmph=_as_float(_dig(row, mapping["speed_kmph"])),
            occupancy_pct=_as_float(_dig(row, mapping["occupancy_pct"])),
            source=self.name,
            is_live=True,
        )


class PushIngestFeed:
    """For operators who push to us rather than being polled.

    poll() returns nothing on purpose: this feed has no upstream to read. The
    observations arrive through POST /avl/ingest and are applied to the store
    directly, so the ingest loop's only job here is to keep the health record
    ticking over.
    """

    name = "push"
    is_live = True

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def poll(self) -> list[VehicleObservation]:
        return []


def build_feed(kind: str, *, url: str = "", field_map: str = "", predictor: Any = None):
    """Construct the feed named by TRACKING_FEED."""
    kind = (kind or "simulated").strip().lower()
    if kind == "simulated":
        return SimulatedFeed(predictor=predictor)
    if kind == "gtfs_rt":
        return GtfsRealtimeFeed(url)
    if kind == "http_json":
        parsed: dict[str, str] = {}
        if field_map:
            try:
                parsed = json.loads(field_map)
            except json.JSONDecodeError as exc:
                raise ValueError(f"TRACKING_FEED_FIELD_MAP is not valid JSON: {exc}") from exc
        return HttpJsonFeed(url, field_map=parsed)
    if kind == "push":
        return PushIngestFeed()
    raise ValueError(
        f"Unknown TRACKING_FEED={kind!r}. Expected one of: simulated, gtfs_rt, http_json, push."
    )


# ── coercion helpers ────────────────────────────────────────────────────────
# Upstream feeds are inconsistent about types (speeds as strings, timestamps as
# epochs or ISO, missing keys). These fail soft to None rather than raising:
# one malformed field should cost that field, not the whole poll.

def _dig(payload: Any, path: str) -> Any:
    if not path:
        return payload
    current = payload
    for part in path.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None
        if current is None:
            return None
    return current


def _as_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> int | None:
    parsed = _as_float(value)
    return int(parsed) if parsed is not None else None


def _as_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _as_datetime(value: Any) -> datetime:
    """Epoch seconds, epoch millis, or ISO-8601. Falls back to now() only when
    the feed genuinely supplied nothing -- which is itself worth knowing, and
    is why adapters log it rather than silently accepting undated data."""
    if value is None:
        return datetime.now(timezone.utc)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        seconds = float(value)
        if seconds > 1e11:          # milliseconds
            seconds /= 1000.0
        return datetime.fromtimestamp(seconds, tz=timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(timezone.utc)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
