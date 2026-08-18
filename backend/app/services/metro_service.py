from __future__ import annotations

import csv
import math
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.ml.text import fuzzy_ratio, normalize_text


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate the great circle distance in kilometers between two points on the earth."""
    radius_km = 6371.0088
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2.0) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2.0) ** 2
    )
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1.0 - a)))
    return radius_km * c


class MetroService:
    def __init__(self, dataset_path: str | Path | None = None) -> None:
        self.dataset_path = Path(dataset_path or settings.metro_dataset_path)
        self.stations: list[dict[str, Any]] = []
        self._load_stations()

    def _load_stations(self) -> None:
        if not self.dataset_path.exists():
            return

        stations: list[dict[str, Any]] = []
        with self.dataset_path.open(newline="", encoding="utf-8", errors="replace") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                station_name = (row.get("station_name") or "").strip()
                if not station_name:
                    continue
                try:
                    lat = float(row.get("latitude") or "0")
                    lon = float(row.get("longitude") or "0")
                except ValueError:
                    lat, lon = 0.0, 0.0

                is_interchange = str(row.get("is_interchange", "0")).strip() in ("1", "true", "True")
                line_name = (row.get("line") or "Purple Line").strip()
                line_color = (row.get("line_color") or "#7E22CE").strip()

                stations.append({
                    "station_code": (row.get("station_code") or "").strip(),
                    "station_name": station_name,
                    "line": line_name,
                    "sequence": int(row.get("sequence") or 0),
                    "is_interchange": is_interchange,
                    "latitude": lat,
                    "longitude": lon,
                    "distance_to_next_km": float(row.get("distance_to_next_km") or 0.0),
                    "line_color": line_color,
                })

        self.stations = stations

    def get_all_stations(self) -> list[dict[str, Any]]:
        return self.stations

    def get_stations_grouped_by_line(self) -> dict[str, list[dict[str, Any]]]:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for st in self.stations:
            line = st["line"]
            grouped.setdefault(line, []).append(st)
        return grouped

    def find_nearest_stations(
        self,
        stop_name: str | None = None,
        lat: float | None = None,
        lon: float | None = None,
        limit: int = 3,
        distance_service: Any = None,
    ) -> list[dict[str, Any]]:
        if not self.stations:
            return []

        target_lat = lat
        target_lon = lon

        # Attempt to resolve lat/lon from stop_name using distance_service coordinate mapping
        if (target_lat is None or target_lon is None) and stop_name and distance_service:
            point = distance_service.resolve_coordinate(stop_name)
            if point:
                target_lat, target_lon = point

        # Fallback: fuzzy match stop_name directly against station names if
        # coordinates remain unknown.
        #
        # Previously this branch fabricated identical, flat values for
        # EVERY result -- distance_km: 0.5, walking_minutes: 6,
        # auto_minutes: 2 -- regardless of the real distance to that
        # station, which could genuinely be anywhere from a few hundred
        # metres to many kilometres away. Without a resolved coordinate
        # for the query, there is no real distance to compute, so this now
        # returns the name-matched stations honestly (ranked by text
        # similarity, which is a real signal) without inventing proximity
        # numbers that look precise but aren't real.
        if target_lat is None or target_lon is None:
            if stop_name:
                norm_stop = normalize_text(stop_name)
                scored = []
                for st in self.stations:
                    score = fuzzy_ratio(norm_stop, normalize_text(st["station_name"]))
                    scored.append((score, st))
                scored.sort(key=lambda x: x[0], reverse=True)
                top_matches = [
                    {
                        **st,
                        "distance_km": None,
                        "distance_meters": None,
                        "walking_minutes": None,
                        "auto_minutes": None,
                        "distance_unavailable_reason": (
                            "Could not resolve a coordinate for this stop, so real "
                            "distance/walking time cannot be computed -- shown by name "
                            "match only."
                        ),
                        "match_score": round(score, 2),
                    }
                    for score, st in scored[:limit]
                ]
                return top_matches
            return []

        # Haversine distance calculation grouped by station_name
        grouped_by_name: dict[str, dict] = {}
        for st in self.stations:
            if st["latitude"] == 0.0 or st["longitude"] == 0.0:
                continue
            name = st["station_name"]
            if name not in grouped_by_name:
                dist_km = haversine_km(target_lat, target_lon, st["latitude"], st["longitude"])
                dist_meters = int(round(dist_km * 1000))
                walk_mins = max(1, int(round(dist_km * 12.5)))
                auto_mins = max(1, int(round(dist_km * 3.0)))
                grouped_by_name[name] = {
                    **st,
                    "lines": [st["line"]],
                    "line_colors": [st["line_color"]],
                    "distance_km": round(dist_km, 2),
                    "distance_meters": dist_meters,
                    "walking_minutes": walk_mins,
                    "auto_minutes": auto_mins,
                }
            else:
                entry = grouped_by_name[name]
                if st["line"] not in entry["lines"]:
                    entry["lines"].append(st["line"])
                if st["line_color"] not in entry["line_colors"]:
                    entry["line_colors"].append(st["line_color"])

        results = list(grouped_by_name.values())
        results.sort(key=lambda item: item["distance_km"])
        return results[:limit]


# Global singleton instance
metro_service = MetroService()