from __future__ import annotations

import json
import csv
import math
import os
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlencode

import httpx

from .text import fuzzy_ratio, normalize_text, repair_route_text
from functools import lru_cache

_COORD_PUNCT_RE = re.compile(r"[^a-z0-9\s]")
_COORD_SPACE_RE = re.compile(r"\s+")


@dataclass(frozen=True, slots=True)
class StopRecord:
    """One physical stop as published in stops_cleaned.csv.

    The coordinate table used to hold bare (lat, lon) tuples, which is all
    routing and distance work ever needs. GTFS export needs the row's
    identity too -- stop_id and zone_id -- so the table holds the whole
    record and resolve_coordinate() returns record.point, leaving every
    existing caller unchanged. See resolve_stop_record() below.
    """

    stop_id: str
    stop_name: str
    zone_id: str
    lat: float
    lon: float

    @property
    def point(self) -> tuple[float, float]:
        return (self.lat, self.lon)


@lru_cache(maxsize=100_000)
def _minimal_normalize(value: str) -> str:
    """Lowercase/clean a stop name WITHOUT stripping distinguishing suffix
    words such as "layout", "circle", "station" -- used only for the
    physical stop_name -> coordinate lookup table below.

    normalize_text() (text.py) deliberately strips those suffix words so
    that e.g. "Majestic" and "Kempegowda Bus Station" are recognised as the
    same PLACE for route/alias matching. That same stripping is actively
    harmful here: Bengaluru has many stop-name pairs that share a root word
    but are genuinely different physical locations kilometres apart -- e.g.
    "Syndicate Bank" (a standalone stop near Ramakrishna Ashrama) and
    "Syndicate Bank Layout" (a residential layout ~9 km away, off Magadi
    Road). Once "Layout" is stripped, both collapse to the same key
    "syndicate bank", and a naive "first row wins" coordinate table would
    silently hand one stop's real coordinates to the other -- which is
    exactly what was happening, and is what fabricated bogus 12-25 km
    "distances" between stops that are actually only a few hundred metres
    apart.
    """
    value = repair_route_text(value).lower().strip()
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    value = _COORD_PUNCT_RE.sub(" ", value)
    value = _COORD_SPACE_RE.sub(" ", value).strip()
    return value


class GoogleMapsDistanceService:
    def __init__(
        self,
        cache_path: str | Path,
        api_key: str | None = None,
        *,
        stop_coordinates_path: str | Path | None = None,
        location_suffix: str = "Bengaluru, Karnataka, India",
        mode: str = "driving",
        timeout_seconds: float = 4.0,
        max_remote_lookups: int = 24,
        max_plausible_segment_km: float = 60.0,
    ) -> None:
        self.cache_path = Path(cache_path)
        self.api_key = (api_key or os.getenv("GOOGLE_MAPS_API_KEY") or "").strip()
        self.location_suffix = location_suffix
        self.mode = mode
        self.timeout_seconds = timeout_seconds
        self.max_remote_lookups = max_remote_lookups
        # A generous sanity ceiling, not a routine cap: with coordinate
        # lookups fixed (see _minimal_normalize above), a single hop
        # between two consecutive *listed* stops in Bengaluru's service
        # area should essentially never exceed this. If it does, that is
        # much more likely a remaining coordinate mismatch than a real
        # 60+ km unbroken hop, so it's reported honestly as an outlier
        # (see _coordinate_segment) instead of being silently trusted --
        # but the real computed number is still returned, never replaced
        # with an unrelated flat guess.
        self.max_plausible_segment_km = max_plausible_segment_km
        self.remote_lookups = 0
        self.cache: dict[str, dict] = self._load_cache()
        self.stop_coordinates = self._load_stop_coordinates(stop_coordinates_path)
        # Caches the fuzzy-matched candidate NAME for a query that had no
        # exact key in stop_coordinates (empty string = no match found) --
        # not the resolved point itself, since which point is best depends
        # on the `near` anchor, which can differ between calls for the same
        # stop name at different points along a route.
        self._coordinate_lookup_cache: dict[str, str] = {}

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def reset_budget(self) -> None:
        self.remote_lookups = 0

    def route_distance(self, stops: list[str], *, allow_remote: bool = False) -> dict:
        clean_stops = [stop for stop in stops if stop]
        if len(clean_stops) < 2:
            return self._fallback(0)

        total_meters = 0
        total_seconds = 0
        missing = False
        sources: set[str] = set()
        # Some real stop names (e.g. "Kodihalli") refer to several distinct
        # physical locations scattered across greater Bengaluru -- a common
        # pattern with "-halli"/"-pura"/"-nagara" village-suffix names. An
        # anchor (the last resolved point along this route) lets
        # resolve_coordinate() pick whichever candidate is actually near the
        # route's path instead of an arbitrary one, and gets carried forward
        # stop by stop so it tracks the route as it goes.
        anchor = self.resolve_coordinate(clean_stops[0])
        for origin, destination in zip(clean_stops, clean_stops[1:]):
            segment = self.segment_distance(origin, destination, allow_remote=allow_remote, anchor=anchor)
            updated_anchor = self.resolve_coordinate(destination, near=anchor)
            if updated_anchor:
                anchor = updated_anchor
            total_meters += int(segment.get("distance_meters") or 0)
            total_seconds += int(segment.get("duration_seconds") or 0)
            source = str(segment.get("source") or "unknown")
            if not segment.get("distance_meters") or "estimate" in source:
                missing = True
            sources.add(source)

        if total_meters <= 0:
            return self._fallback(len(clean_stops) - 1)
        if sources == {"google_maps"}:
            distance_source = "google_maps"
        elif sources == {"stop_coordinates"}:
            distance_source = "stop_coordinates"
        elif all("estimate" in source for source in sources):
            distance_source = "stop_count_estimate"
        else:
            distance_source = "mixed"

        return {
            "distance_km": round(total_meters / 1000, 2),
            "duration_minutes": round(total_seconds / 60, 1) if total_seconds else None,
            "distance_source": distance_source,
            "distance_complete": not missing,
        }

    def segment_distance(
        self,
        origin: str,
        destination: str,
        *,
        allow_remote: bool = False,
        anchor: tuple[float, float] | None = None,
    ) -> dict:
        key = self._cache_key(origin, destination)
        if key in self.cache:
            return self.cache[key]
        coordinate_segment = self._coordinate_segment(origin, destination, anchor=anchor)
        if coordinate_segment:
            return coordinate_segment
        if not allow_remote or not self.enabled or self.remote_lookups >= self.max_remote_lookups:
            return self._segment_fallback(origin, destination)

        self.remote_lookups += 1
        segment = self._fetch_google_segment(origin, destination)
        if segment:
            self.cache[key] = segment
            self._save_cache()
            return segment
        return self._segment_fallback(origin, destination)

    def _fetch_google_segment(self, origin: str, destination: str) -> dict | None:
        params = {
            "origins": self._place_query(origin),
            "destinations": self._place_query(destination),
            "mode": self.mode,
            "units": "metric",
            "key": self.api_key,
        }
        url = f"https://maps.googleapis.com/maps/api/distancematrix/json?{urlencode(params)}"
        try:
            response = httpx.get(url, timeout=self.timeout_seconds)
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError):
            return None

        rows = payload.get("rows") or []
        elements = rows[0].get("elements") if rows else []
        element = elements[0] if elements else {}
        if payload.get("status") != "OK" or element.get("status") != "OK":
            return None

        return {
            "distance_meters": int(element.get("distance", {}).get("value") or 0),
            "duration_seconds": int(element.get("duration", {}).get("value") or 0),
            "source": "google_maps",
        }

    def _place_query(self, stop: str) -> str:
        return f"{stop}, {self.location_suffix}"

    def _cache_key(self, origin: str, destination: str) -> str:
        return f"{normalize_text(origin)}|{normalize_text(destination)}"

    def _coordinate_segment(
        self, origin: str, destination: str, *, anchor: tuple[float, float] | None = None
    ) -> dict | None:
        origin_point = self.resolve_coordinate(origin, near=anchor)
        # Resolve the destination relative to the origin we just settled on
        # (not the older anchor) so a chain of same-named stops each picks
        # the candidate nearest to the previous one, tracking the route.
        destination_point = self.resolve_coordinate(destination, near=origin_point or anchor)
        if not origin_point or not destination_point:
            return None

        straight_line_km = self._haversine_km(origin_point, destination_point)
        road_distance_km = straight_line_km * 1.28

        # Previously: distances beyond a 12 km cap were discarded outright
        # and silently replaced (via _segment_fallback) with a flat 0.75 km
        # guess -- which is *never* more accurate than a real computed
        # distance, however large. That fabricated every long segment
        # (airport routes, satellite-town feeders, and any pair whose
        # coordinates had been mismatched) into a near-zero number with no
        # indication anything was wrong.
        #
        # Now: always report the real computed distance. If it exceeds the
        # generous sanity ceiling above, mark it honestly as an outlier
        # (callers already check "source"/"estimate" via route_distance's
        # `missing` flag and distance_complete) instead of masking it.
        source = "stop_coordinates" if road_distance_km <= self.max_plausible_segment_km else "coordinate_outlier_estimate"
        return {
            "distance_meters": int(round(road_distance_km * 1000)),
            "duration_seconds": int(round(road_distance_km / 18 * 3600)),
            "source": source,
        }

    def _load_stop_coordinates(self, path: str | Path | None) -> dict[str, list[StopRecord]]:
        if not path:
            return {}
        csv_path = Path(path)
        if not csv_path.exists():
            return {}

        # Names in Bengaluru's BMTC network are not unique: several genuinely
        # different places (usually "-halli"/"-pura"/"-nagara" village-suffix
        # names, e.g. "Kodihalli") repeat across the city, sometimes tens of
        # km apart. Keeping only the first CSV row per name (the previous
        # behaviour) silently picks an arbitrary one of them -- which
        # fabricated a ~35 km phantom hop in the middle of real routes when
        # the wrong "Kodihalli" got used. Instead we keep every genuinely
        # distinct candidate (collapsing only near-duplicate rows -- e.g.
        # "Towards X" / "Towards Y" direction variants of the same physical
        # stop, typically metres apart) and let resolve_coordinate() pick
        # among them using route context (see the `near` parameter there).
        coordinates: dict[str, list[StopRecord]] = {}
        with csv_path.open(newline="", encoding="utf-8", errors="replace") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                stop_name = (row.get("stop_name") or "").strip()
                if not stop_name:
                    continue
                try:
                    lat = float(row.get("stop_lat") or "")
                    lon = float(row.get("stop_lon") or "")
                except ValueError:
                    continue
                key = _minimal_normalize(stop_name)
                if not key:
                    continue
                record = StopRecord(
                    stop_id=(row.get("stop_id") or "").strip() or f"{key}-{lat:.5f}-{lon:.5f}",
                    stop_name=stop_name,
                    zone_id=(row.get("zone_id") or "").strip(),
                    lat=lat,
                    lon=lon,
                )
                bucket = coordinates.setdefault(key, [])
                if not any(self._haversine_km(record.point, existing.point) < 0.3 for existing in bucket):
                    bucket.append(record)
        return coordinates

    def resolve_coordinate(
        self, stop: str, *, near: tuple[float, float] | None = None
    ) -> tuple[float, float] | None:
        record = self.resolve_stop_record(stop, near=near)
        return record.point if record else None

    def resolve_stop_record(
        self, stop: str, *, near: tuple[float, float] | None = None
    ) -> StopRecord | None:
        """Resolve a stop name to the published stop row it refers to.

        Identical resolution to resolve_coordinate() -- which now delegates
        here -- but returns the whole record so callers that need the
        published stop_id (GTFS export) can have it. The `near` anchor
        disambiguates repeated names exactly as before; see _pick_candidate.
        """
        # Use the same minimal (non-noise-stripped) normalization as the
        # lookup table was built with -- see _minimal_normalize for why
        # normalize_text()'s noise-word stripping must NOT be used here.
        key = _minimal_normalize(stop)

        candidates = self.stop_coordinates.get(key)
        if candidates:
            return self._pick_candidate(candidates, near)

        # Only cache the "no exact name match, had to fuzzy-search" result,
        # since that search is the expensive part; an exact-name hit above
        # is already an O(1) dict lookup and doesn't need caching, and
        # caching it would ignore the `near` disambiguation on later calls
        # with a different anchor for the same ambiguous name.
        cache_key = key
        if cache_key in self._coordinate_lookup_cache:
            best_key = self._coordinate_lookup_cache[cache_key]
            return self._pick_candidate(self.stop_coordinates[best_key], near) if best_key else None

        query_tokens = {token for token in key.split() if len(token) >= 3}
        best_key = ""
        best_score = 0.0
        for candidate in self.stop_coordinates:
            candidate_tokens = {token for token in candidate.split() if len(token) >= 3}
            token_overlap = len(query_tokens & candidate_tokens) / max(len(query_tokens | candidate_tokens), 1)
            if token_overlap < 0.3 and not (key in candidate or candidate in key):
                continue
            score = max(fuzzy_ratio(key, candidate), token_overlap)
            if score > best_score:
                best_key = candidate
                best_score = score

        if best_key and best_score >= 0.72:
            self._coordinate_lookup_cache[cache_key] = best_key
            return self._pick_candidate(self.stop_coordinates[best_key], near)
        self._coordinate_lookup_cache[cache_key] = ""
        return None

    def _pick_candidate(
        self, candidates: list[StopRecord], near: tuple[float, float] | None
    ) -> StopRecord | None:
        if not candidates:
            return None
        if len(candidates) == 1 or near is None:
            return candidates[0]
        return min(candidates, key=lambda record: self._haversine_km(near, record.point))

    def _haversine_km(self, origin: tuple[float, float], destination: tuple[float, float]) -> float:
        origin_lat, origin_lon = origin
        destination_lat, destination_lon = destination
        radius_km = 6371.0088
        lat1 = math.radians(origin_lat)
        lat2 = math.radians(destination_lat)
        delta_lat = math.radians(destination_lat - origin_lat)
        delta_lon = math.radians(destination_lon - origin_lon)
        value = (
            math.sin(delta_lat / 2) ** 2
            + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2
        )
        return radius_km * 2 * math.atan2(math.sqrt(value), math.sqrt(max(0.0, 1 - value)))

    def _fallback(self, stop_count: int) -> dict:
        estimated_km = max(0, stop_count) * 0.75
        return {
            "distance_km": round(estimated_km, 2),
            "duration_minutes": round(estimated_km * 3.2, 1) if estimated_km else None,
            "distance_source": "stop_count_estimate",
            "distance_complete": False,
        }

    def _segment_fallback(self, origin: str, destination: str) -> dict:
        estimated_km = 0.75
        return {
            "distance_meters": int(estimated_km * 1000),
            "duration_seconds": int(estimated_km * 3.2 * 60),
            "source": "cache_miss_estimate" if self.enabled else "stop_count_estimate",
            "origin": origin,
            "destination": destination,
        }

    def _load_cache(self) -> dict[str, dict]:
        if not self.cache_path.exists():
            return {}
        try:
            payload = json.loads(self.cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def _save_cache(self) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(json.dumps(self.cache, indent=2, sort_keys=True), encoding="utf-8")