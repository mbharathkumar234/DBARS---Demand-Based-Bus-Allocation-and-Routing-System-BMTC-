from __future__ import annotations

import ast
import csv
from dataclasses import dataclass, field
from pathlib import Path

from .text import normalize_text, repair_route_text


@dataclass(slots=True)
class RouteRecord:
    route_number: str
    full_name: str
    trip_count: int
    trip_list: list[str]
    stop_count: int
    stops: list[str]
    route_id: str
    direction_id: int
    source: str
    destination: str
    normalized_stops: list[str] = field(default_factory=list)

    # Derived once at load time because the route search recomputes them
    # otherwise -- see __post_init__. Profiling a single worst-case query
    # ("KR Market" -> "Kempegowda Bus Station") showed 512,956 normalize_text
    # calls costing 7.0s, all of them re-deriving is_self_loop for the same
    # few thousand routes, plus 1,730,080 scans of normalized_stops looking up
    # positions that never change.
    stop_positions: dict[str, list[int]] = field(default_factory=dict)
    is_self_loop: bool = False
    search_text: str = ""

    def __post_init__(self) -> None:
        positions: dict[str, list[int]] = {}
        for index, normalized in enumerate(self.normalized_stops):
            positions.setdefault(normalized, []).append(index)
        self.stop_positions = positions
        self.is_self_loop = bool(
            self.source
            and self.destination
            and normalize_text(self.source) == normalize_text(self.destination)
        )
        self.search_text = f"{self.route_number} {self.full_name}".lower()

    @property
    def key(self) -> str:
        return f"{self.route_id}:{self.direction_id}:{self.route_number}"

    @property
    def document(self) -> str:
        return " ".join(
            [
                self.route_number,
                self.full_name,
                self.source,
                self.destination,
                " ".join(self.stops),
            ]
        )


def _parse_list(value: str) -> list[str]:
    if not value:
        return []
    parsed = ast.literal_eval(value)
    if not isinstance(parsed, list):
        return []
    return [str(item).strip() for item in parsed if str(item).strip()]


def _parse_full_name(full_name: str, stops: list[str]) -> tuple[str, str]:
    cleaned = repair_route_text(full_name)
    if "->" in cleaned:
        left, right = cleaned.split("->", 1)
        source = left.strip()
        destination = right.strip()
    else:
        source = stops[0] if stops else ""
        destination = stops[-1] if stops else ""
    return source or (stops[0] if stops else ""), destination or (stops[-1] if stops else "")


def load_routes(csv_path: str | Path) -> list[RouteRecord]:
    path = Path(csv_path)
    if not path.exists():
        raise FileNotFoundError(f"Dataset not found: {path}")

    routes: list[RouteRecord] = []
    seen: set[tuple[str, int, str, tuple[str, ...]]] = set()
    with path.open(newline="", encoding="utf-8", errors="replace") as handle:
        reader = csv.DictReader(handle)
        required = {"name", "full_name", "trip_count", "trip_list", "stop_count", "stop_list", "id", "direction_id"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"Dataset missing required columns: {sorted(missing)}")

        for row in reader:
            stops = _parse_list(row.get("stop_list", "[]"))
            trips = _parse_list(row.get("trip_list", "[]"))
            direction_id = int(row.get("direction_id") or 0)
            route_number = (row.get("name") or "").strip()
            route_id = str(row.get("id") or route_number).strip()
            source, destination = _parse_full_name(row.get("full_name") or "", stops)
            key = (route_id, direction_id, route_number, tuple(stops))
            if not route_number or len(stops) < 2 or key in seen:
                continue
            seen.add(key)
            routes.append(
                RouteRecord(
                    route_number=route_number,
                    full_name=repair_route_text(row.get("full_name") or ""),
                    trip_count=int(float(row.get("trip_count") or len(trips) or 0)),
                    trip_list=trips,
                    stop_count=int(float(row.get("stop_count") or len(stops))),
                    stops=stops,
                    route_id=route_id,
                    direction_id=direction_id,
                    source=source,
                    destination=destination,
                    normalized_stops=[normalize_text(stop) for stop in stops],
                )
            )
    return routes


def dataset_profile(routes: list[RouteRecord]) -> dict:
    stops = {stop for route in routes for stop in route.stops}
    route_numbers = {route.route_number for route in routes}
    direction_counts: dict[int, int] = {}
    stop_lengths = [len(route.stops) for route in routes]
    for route in routes:
        direction_counts[route.direction_id] = direction_counts.get(route.direction_id, 0) + 1
    return {
        "rows": len(routes),
        "unique_bus_numbers": len(route_numbers),
        "unique_stops": len(stops),
        "direction_counts": direction_counts,
        "min_stops_per_route": min(stop_lengths) if stop_lengths else 0,
        "max_stops_per_route": max(stop_lengths) if stop_lengths else 0,
        "avg_stops_per_route": round(sum(stop_lengths) / max(len(stop_lengths), 1), 2),
    }
