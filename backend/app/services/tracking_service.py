from __future__ import annotations

import asyncio
import logging
import math
import random
import time
from typing import Any

from app.db.database import get_db

logger = logging.getLogger("bmtc.services.tracking")

# How often the simulation is allowed to actually advance. Reads arriving more
# frequently than this get the current state rather than re-advancing it, so N
# concurrent viewers produce one shared timeline instead of N stacked ones.
MIN_TICK_INTERVAL_SECONDS = 2.0


class BusSimulator:
    """A lightweight engine to simulate live bus movements so the frontend map actually has moving markers."""

    def __init__(self) -> None:
        self._active_buses: dict[str, dict[str, Any]] = {}
        self._last_tick = time.time()
        # Serialises both seeding and advancing. Without it, two concurrent
        # requests could each seed a full fleet, or interleave a tick with a
        # delete_many/insert_many and leave bus_positions inconsistent.
        self._lock = asyncio.Lock()

    async def advance_if_due(self) -> None:
        """Advance the simulation if enough time has passed since the last step.

        This is what makes the simulation self-driving on read. Previously the
        only way to move the buses was an unauthenticated POST /tracking/tick
        that any caller could hammer -- each call mutating shared global state
        and rewriting the whole bus_positions collection.
        """
        if not self._active_buses:
            return
        if time.time() - self._last_tick < MIN_TICK_INTERVAL_SECONDS:
            return
        await self.tick()

    async def initialize_buses(self, routes: list, distance_service: Any = None) -> int:
        """Seed simulated buses along our most popular routes so the map isn't completely empty."""
        if self._active_buses:
            return len(self._active_buses)
        async with self._lock:
            # Re-check inside the lock: several concurrent first requests can
            # all pass the check above before any of them has seeded anything.
            if self._active_buses:
                return len(self._active_buses)
            return await self._initialize_locked(routes, distance_service)

    async def _initialize_locked(self, routes: list, distance_service: Any = None) -> int:
        # grab up to 30 valid routes to stick buses on
        eligible = [r for r in routes if len(r.stops) >= 4]
        sampled_routes = random.sample(eligible, min(30, len(eligible)))

        for route in sampled_routes:
            bus_key = f"{route.route_number}_{route.direction_id}"
            stops_with_coords = []
            anchor: tuple[float, float] | None = None
            for stop in route.stops:
                point = distance_service.resolve_coordinate(stop, near=anchor) if distance_service else None
                if point:
                    stops_with_coords.append({
                        "name": stop,
                        "lat": point[0],
                        "lon": point[1],
                    })
                    anchor = point
            if len(stops_with_coords) < 3:
                continue

            # plop the bus down at a random point along its path
            progress = random.uniform(0, len(stops_with_coords) - 1)
            segment_idx = int(progress)
            segment_progress = progress - segment_idx
            if segment_idx >= len(stops_with_coords) - 1:
                segment_idx = len(stops_with_coords) - 2
                segment_progress = 1.0

            lat = stops_with_coords[segment_idx]["lat"] + segment_progress * (
                stops_with_coords[segment_idx + 1]["lat"] - stops_with_coords[segment_idx]["lat"]
            )
            lon = stops_with_coords[segment_idx]["lon"] + segment_progress * (
                stops_with_coords[segment_idx + 1]["lon"] - stops_with_coords[segment_idx]["lon"]
            )

            next_stop_idx = min(segment_idx + 1, len(stops_with_coords) - 1)
            self._active_buses[bus_key] = {
                "bus_number": route.route_number,
                "route_id": str(route.direction_id),
                "latitude": round(lat, 6),
                "longitude": round(lon, 6),
                "speed_kmh": round(random.uniform(10, 35), 1),
                "occupancy_pct": round(random.uniform(20, 85), 1),
                "heading": self._compute_heading(lat, lon,
                    stops_with_coords[next_stop_idx]["lat"],
                    stops_with_coords[next_stop_idx]["lon"]),
                "next_stop": stops_with_coords[next_stop_idx]["name"],
                "stops": stops_with_coords,
                "progress": progress,
                "direction": route.full_name,
            }

        # sync the active fleet to the db so the frontend can pull it if db is up
        from app.db.database import db_available
        if db_available():
            from datetime import datetime, timezone
            async for db in get_db():
                await db.bus_positions.delete_many({})
                bus_payloads = []
                for key, bus in self._active_buses.items():
                    bus_payloads.append({
                        "bus_number": bus["bus_number"],
                        "route_id": bus["route_id"],
                        "latitude": bus["latitude"],
                        "longitude": bus["longitude"],
                        "speed_kmh": bus["speed_kmh"],
                        "occupancy_pct": bus["occupancy_pct"],
                        "heading": bus["heading"],
                        "next_stop": bus["next_stop"],
                        "updated_at": datetime.now(timezone.utc)
                    })
                if bus_payloads:
                    await db.bus_positions.insert_many(bus_payloads)

        logger.info("Spun up %d simulated buses on the map", len(self._active_buses))
        return len(self._active_buses)

    async def tick(self) -> list[dict]:
        """Advance all buses by one simulation step."""
        async with self._lock:
            return await self._tick_locked()

    async def _tick_locked(self) -> list[dict]:
        now = time.time()
        dt = min(now - self._last_tick, 5.0)  # Cap at 5s steps
        self._last_tick = now

        updated = []
        for key, bus in self._active_buses.items():
            stops = bus["stops"]
            if not stops or len(stops) < 2:
                continue

            # Advance progress based on speed (roughly 1 stop per ~2min at 25kmh)
            speed_factor = bus["speed_kmh"] / 25.0
            advance = dt * 0.008 * speed_factor  # ~1 stop per 2 min
            bus["progress"] += advance

            # Loop the route
            if bus["progress"] >= len(stops) - 1:
                bus["progress"] = 0.0

            idx = int(bus["progress"])
            frac = bus["progress"] - idx
            if idx >= len(stops) - 1:
                idx = len(stops) - 2
                frac = 1.0

            bus["latitude"] = round(
                stops[idx]["lat"] + frac * (stops[idx + 1]["lat"] - stops[idx]["lat"]), 6
            )
            bus["longitude"] = round(
                stops[idx]["lon"] + frac * (stops[idx + 1]["lon"] - stops[idx]["lon"]), 6
            )

            next_stop_idx = min(idx + 1, len(stops) - 1)
            bus["next_stop"] = stops[next_stop_idx]["name"]
            bus["heading"] = self._compute_heading(
                bus["latitude"], bus["longitude"],
                stops[next_stop_idx]["lat"], stops[next_stop_idx]["lon"]
            )

            # Add slight randomness to speed and occupancy
            bus["speed_kmh"] = round(max(5, bus["speed_kmh"] + random.uniform(-2, 2)), 1)
            bus["occupancy_pct"] = round(max(5, min(98, bus["occupancy_pct"] + random.uniform(-3, 3))), 1)

            updated.append({
                "bus_number": bus["bus_number"],
                "route_id": bus["route_id"],
                "latitude": bus["latitude"],
                "longitude": bus["longitude"],
                "speed_kmh": bus["speed_kmh"],
                "occupancy_pct": bus["occupancy_pct"],
                "heading": bus["heading"],
                "next_stop": bus["next_stop"],
                "direction": bus.get("direction", ""),
            })

        # Bulk update database if DB is available
        from app.db.database import db_available
        if updated and db_available():
            from datetime import datetime, timezone
            async for db in get_db():
                await db.bus_positions.delete_many({})
                docs = []
                for bus in updated:
                    docs.append({
                        "bus_number": bus["bus_number"],
                        "route_id": bus["route_id"],
                        "latitude": bus["latitude"],
                        "longitude": bus["longitude"],
                        "speed_kmh": bus["speed_kmh"],
                        "occupancy_pct": bus["occupancy_pct"],
                        "heading": bus["heading"],
                        "next_stop": bus["next_stop"],
                        "updated_at": datetime.now(timezone.utc)
                    })
                if docs:
                    await db.bus_positions.insert_many(docs)

        return updated

    def get_all_buses(self) -> list[dict]:
        """Return current positions of all simulated buses."""
        return [
            {
                "bus_number": bus["bus_number"],
                "route_id": bus["route_id"],
                "latitude": bus["latitude"],
                "longitude": bus["longitude"],
                "speed_kmh": bus["speed_kmh"],
                "occupancy_pct": bus["occupancy_pct"],
                "heading": bus["heading"],
                "next_stop": bus["next_stop"],
                "direction": bus.get("direction", ""),
            }
            for bus in self._active_buses.values()
        ]

    def get_bus(self, bus_number: str) -> list[dict]:
        """Return all active instances of a bus number."""
        return [
            {
                "bus_number": bus["bus_number"],
                "route_id": bus["route_id"],
                "latitude": bus["latitude"],
                "longitude": bus["longitude"],
                "speed_kmh": bus["speed_kmh"],
                "occupancy_pct": bus["occupancy_pct"],
                "heading": bus["heading"],
                "next_stop": bus["next_stop"],
                "direction": bus.get("direction", ""),
                "stops": [s["name"] for s in bus.get("stops", [])],
            }
            for bus in self._active_buses.values()
            if bus["bus_number"].upper() == bus_number.upper()
        ]

    @staticmethod
    def _compute_heading(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """Compute compass heading from point 1 to point 2."""
        d_lon = math.radians(lon2 - lon1)
        lat1_r, lat2_r = math.radians(lat1), math.radians(lat2)
        x = math.sin(d_lon) * math.cos(lat2_r)
        y = math.cos(lat1_r) * math.sin(lat2_r) - math.sin(lat1_r) * math.cos(lat2_r) * math.cos(d_lon)
        heading = math.degrees(math.atan2(x, y))
        return round((heading + 360) % 360, 1)


# Global simulator instance
bus_simulator = BusSimulator()


def estimate_eta_minutes(
    bus_lat: float, bus_lon: float,
    target_lat: float, target_lon: float,
    speed_kmh: float,
) -> dict:
    """Estimate ETA to a target stop based on straight-line distance and current speed."""
    # Haversine distance
    R = 6371.0  # Earth radius km
    lat1, lon1, lat2, lon2 = map(math.radians, [bus_lat, bus_lon, target_lat, target_lon])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    distance_km = R * c

    # Apply road factor (roads are ~1.4x longer than straight-line in urban areas)
    road_distance_km = distance_km * 1.4

    effective_speed = max(speed_kmh, 8.0)  # At least 8 km/h
    eta_minutes = (road_distance_km / effective_speed) * 60

    return {
        "distance_km": round(road_distance_km, 2),
        "eta_minutes": round(eta_minutes, 1),
        "eta_range": f"{max(1, int(eta_minutes - 3))}-{int(eta_minutes + 5)} min",
        "speed_kmh": round(effective_speed, 1),
    }
