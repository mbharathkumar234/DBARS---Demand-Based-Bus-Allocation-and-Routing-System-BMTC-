from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path

from fastapi import Request

from app.core.config import settings

logger = logging.getLogger("bmtc.fares")


@lru_cache(maxsize=1)
def _load_fare_table(path: str | None = None) -> dict:
    """Load the fare-stage reference data (dataset/fares.json).

    Previously every fare band was a hardcoded number baked directly into
    this file's if/elif chains -- meaning a real BMTC fare revision (which
    happens periodically; see fares.json's own notes) required a code
    change and redeploy, not a data update. Fares are now external,
    versioned data with per-stage confidence/source notes, so they can be
    corrected or updated without touching this module. Cached with
    lru_cache since the file only needs to be read once per process.
    """
    fares_path = Path(path) if path else settings.fares_dataset_path
    try:
        with open(fares_path, encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        logger.error("Fare table missing at %s -- /api/tickets/fare disabled", fares_path)
        raise


def _fare_for_stages(distance_km: float, stages: list[dict]) -> float:
    for stage in stages:
        max_km = stage.get("max_km")
        if max_km is None or distance_km <= max_km:
            return float(stage["fare_inr"])
    # Should be unreachable if the data file's last stage has max_km: null,
    # but fall back to the last stage's fare rather than raising, since a
    # missing fare is worse than a possibly-stale one for this use case.
    return float(stages[-1]["fare_inr"]) if stages else 0.0


def calculate_stage_fare(distance_km: float, is_airport: bool = False, is_ac: bool = False) -> float:
    """Calculates fare based on distance (km) using BMTC stage rules from fares.json.

    See fares.json for the per-category verification status -- the
    ordinary category's short-distance stages are cross-sourced and
    verified; several other stages (and the entire Vajra/Vayu Vajra
    tables) are carried over from a previous, unsourced implementation
    and are explicitly flagged there as needing verification against
    BMTC's official fare charts before being relied on for real fare
    collection.
    """
    table = _load_fare_table()
    if is_airport:
        category = table["categories"]["vayu_vajra_airport"]
    elif is_ac:
        category = table["categories"]["vajra_ac"]
    else:
        category = table["categories"]["ordinary"]
    return _fare_for_stages(distance_km, category["stages"])


def get_fare(source: str, destination: str, request: Request, is_ac: bool = False) -> float | None:
    """Fetches distance and calculates fare based on BMTC stages."""
    is_airport = "KIA" in source.upper() or "KIA" in destination.upper() or "AIRPORT" in source.upper() or "AIRPORT" in destination.upper()

    try:
        predictor = request.app.state.predictor
        distance_service = predictor.distance_service

        # Resolve through the same stop-name pipeline predict() uses
        # (aliases, fuzzy matching, depot-deprioritization -- see
        # predictor.py's _resolve_stop_name) before computing distance.
        #
        # Previously this passed `source`/`destination` straight through
        # to segment_distance() as typed. A colloquial name like
        # "Majestic" is a known ALIAS (predictor.py's normalize_text
        # expands it to "Kempegowda Bus Station"), but distance.py's
        # coordinate table is keyed by minimal-normalized real stop names
        # and does not know that alias -- resolve_coordinate("Majestic")
        # found nothing, and the segment silently fell back to a flat
        # 0.75km "no data" estimate. For a 28 km real trip, that meant a
        # fare of Rs 6 (the shortest-distance stage) instead of the
        # correct ~Rs 30 -- not a rounding difference, a wrong fare
        # class entirely, for any query using a colloquial stop name
        # rather than the exact official one.
        resolved_source, source_score = predictor._resolve_stop_name(source)
        resolved_destination, dest_score = predictor._resolve_stop_name(destination)
        if source_score < 0.5 or dest_score < 0.5:
            logger.warning(
                "Low-confidence stop resolution for fare lookup: %r -> %r (scores %.2f, %.2f)",
                source, destination, source_score, dest_score,
            )

        segment = distance_service.segment_distance(resolved_source, resolved_destination)

        distance_meters = segment.get("distance_meters")

        if distance_meters:
            distance_km = distance_meters / 1000.0

            # Previously this multiplied by another 1.3x here whenever the
            # segment's source was "stop_coordinates", on the assumption
            # that value was still raw straight-line distance needing a
            # road-distance approximation applied. It wasn't: distance.py's
            # _coordinate_segment() already applies its own 1.28x road-
            # distance multiplier internally before ever returning a
            # "stop_coordinates"-sourced value (see distance.py). Stacking
            # a second, independent 1.3x multiplier on top compounded to
            # roughly 1.28 * 1.3 = 1.664x the true straight-line distance
            # -- about 30% higher than intended -- silently inflating the
            # fare (and therefore which stage band it lands in) for the
            # large majority of routes, which use coordinate-based
            # distance. The value from segment_distance() is already the
            # right unit to feed straight into the fare table now.
            return calculate_stage_fare(distance_km, is_airport, is_ac)
    except Exception:
        logger.exception("Error calculating fare distance for %r -> %r", source, destination)

    return None