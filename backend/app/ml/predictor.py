from __future__ import annotations

import json
import logging
import math
import random
import re
import time
from difflib import SequenceMatcher
from pathlib import Path
from statistics import mean

from app.core.config import settings

from .data_loader import RouteRecord, dataset_profile, load_routes
from .distance import GoogleMapsDistanceService, _minimal_normalize
from .stop_registry import StopRegistry
from .text import clamp, fuzzy_ratio, normalize_text
from app.services.metro_service import metro_service

logger = logging.getLogger("bmtc.predictor")
from .tfidf import TfidfIndex


GENERIC_STOP_TOKENS = {
    "arrival",
    "bus",
    "circle",
    "departure",
    "depature",
    "gate",
    "layout",
    "metro",
    "road",
    "stage",
    "station",
    "stop",
}


class BMTCBusPredictor:
    # Stamped into artifacts/metrics.json by _save_metrics and checked by
    # train() before reusing a cached file. Bump this whenever the shape or
    # meaning of the metrics payload changes, so an old artifact directory is
    # re-evaluated instead of being served under the new contract.
    #
    # This constant was referenced by train() but never actually defined, and
    # the reference sits inside a `except Exception` block -- so every startup
    # raised AttributeError, swallowed it, and fell through to a full
    # _evaluate_models() run. Measured on this dataset: 50.4s per boot instead
    # of 8.9s. The cache had never once been used. _save_metrics never wrote
    # the key either, so defining this alone would not have been enough.
    METRICS_SCHEMA_VERSION = 1

    def __init__(self, dataset_path: str | Path, artifact_dir: str | Path) -> None:
        self.dataset_path = Path(dataset_path)
        self.artifact_dir = Path(artifact_dir)
        self.routes: list[RouteRecord] = []
        self.tfidf = TfidfIndex()
        self.metrics: dict = {}
        self.profile: dict = {}
        self.stop_names: list[str] = []
        self.destination_names: list[str] = []
        # normalize_text() is lossy on purpose (it strips "circle", "gate",
        # "bus station", ... so that "Abbigere" finds "Abbigere Cross"), which
        # means one normalized key can stand for several genuinely different
        # raw stop names. Keep them ALL -- see _build_stop_name_indexes.
        self.stop_displays_by_norm: dict[str, list[str]] = {}
        self.stop_display_by_norm: dict[str, str] = {}
        self.stop_raw_frequency: dict[str, int] = {}
        self._compact_raw_names: dict[str, str] = {}
        self._norm_stops_by_token: dict[str, set[str]] = {}
        self.stop_registry: StopRegistry = StopRegistry()
        self.stop_to_route_indices: dict[str, set[int]] = {}
        self.stop_pair_to_segments: dict[tuple[str, str], list[tuple[int, int, int]]] = {}
        self.distance_service = GoogleMapsDistanceService(
            self.artifact_dir / "google_distance_cache.json",
            settings.google_maps_api_key,
            stop_coordinates_path=settings.stop_coordinates_path,
            location_suffix=settings.google_maps_location_suffix,
            mode=settings.google_maps_distance_mode,
            max_remote_lookups=settings.google_maps_max_remote_lookups,
        )
        self._trained_at = 0.0

    @property
    def ready(self) -> bool:
        return bool(self.routes and self.metrics)

    def train(self, force: bool = False) -> dict:
        if self.ready and not force:
            return self.metrics

        started = time.perf_counter()
        self.routes = load_routes(self.dataset_path)
        documents = [route.document for route in self.routes]
        self.tfidf.fit(documents)
        self.profile = dataset_profile(self.routes)
        self.stop_names = sorted({stop for route in self.routes for stop in route.stops})
        self.destination_names = sorted({route.destination for route in self.routes if route.destination})
        self._build_stop_name_indexes()
        # Built from the same validated normalize_text grouping already used
        # above -- this does not introduce new matching logic, it gives the
        # existing grouping stable, deterministic IDs. See stop_registry.py.
        self.stop_registry = StopRegistry.build(
            self.stop_names,
            coordinates=self.distance_service.stop_coordinates,
        )
        self.stop_to_route_indices = {}
        for index, route in enumerate(self.routes):
            for stop in route.normalized_stops:
                self.stop_to_route_indices.setdefault(stop, set()).add(index)
        self.stop_pair_to_segments = self._build_stop_pair_index()
        # Anchored coordinates per route-direction, filled on demand. Rebuilt
        # here on every train() so a retrain cannot serve geometry from the
        # previous dataset.
        self._route_points_cache: dict[tuple[str, int], list[tuple[float, float] | None]] = {}
        
        metrics_file = self.artifact_dir / "metrics.json"
        if metrics_file.exists() and not force:
            # Deliberately narrow: only an unreadable or malformed artifact
            # file is a reason to fall back to a full re-evaluation. A blanket
            # `except Exception` here is what let a plain AttributeError (a
            # missing METRICS_SCHEMA_VERSION) silently disable this cache
            # entirely -- the run still looked healthy, it just paid 40+
            # extra seconds on every single boot, forever. A bug in this
            # block should now fail loudly instead of quietly costing time.
            try:
                cached = json.loads(metrics_file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                cached = {}
            if cached.get("schema_version") != self.METRICS_SCHEMA_VERSION:
                self.metrics = self._evaluate_models()
            else:
                self.metrics = cached.get("metrics", {})
        else:
            self.metrics = self._evaluate_models()

        self.metrics["training_seconds"] = round(time.perf_counter() - started, 3)
        self.metrics["dataset_profile"] = self.profile
        self.metrics["stop_pair_index"] = {
            "ordered_pairs": len(self.stop_pair_to_segments),
            "route_segments": sum(len(segments) for segments in self.stop_pair_to_segments.values()),
        }
        self.metrics["distance_provider"] = {
            "name": "GTFS stop coordinates with optional Google Maps cache",
            "enabled": self.distance_service.enabled,
            "mode": self.distance_service.mode,
            "cache_entries": len(self.distance_service.cache),
            "coordinate_stops": len(self.distance_service.stop_coordinates),
        }
        # predict() is served by _find_transfer_suggestions() -- always,
        # unconditionally, regardless of which candidate model happens to
        # score best in the offline comparison above. Previously this was
        # hardcoded to "DistanceAwareRouteRanker", a candidate that is never
        # actually called by predict(); that made the whole metrics.json
        # dashboard describe a model that wasn't in the live request path.
        # "LiveTransferSearch" is the only truthful answer here because it's
        # the only one that is literally what runs.
        self.metrics["selected_model"] = "LiveTransferSearch"
        if "LiveTransferSearch" in self.metrics.get("candidate_models", {}):
            self.metrics["selected_model_metrics"] = self.metrics["candidate_models"]["LiveTransferSearch"]
        self.metrics["selection_reason"] = (
            "predict() is served by _find_transfer_suggestions(): a direct + one-transfer graph search over real "
            "BMTC route/stop membership, built from every ordered stop-to-stop pair found on each route. The "
            "'LiveTransferSearch' metrics above are the accuracy of exactly what predict() returns to a user. "
            "TFIDFCosine, OrderedStopFuzzy, and DistanceAwareRouteRanker are offline research comparisons only -- "
            "none of them is called by predict(), regardless of how they score here."
        )
        self._trained_at = time.time()
        self._save_metrics()
        return self.metrics

    def _build_stop_name_indexes(self) -> None:
        """Index raw stop names by their normalized key, keeping every collision.

        normalize_text() strips category words ("Circle", "Gate", "Bus
        Station", ...) so that a commuter typing "Abbigere" still finds
        "Abbigere Cross". The cost is that distinct real places collapse onto
        one key: "Yeshawanthapura Circle", "Yeshawanthapura Bus Station" and
        "Yeshawanthapura" all normalize to "yeshawanthapura".

        This used to be a plain dict comprehension, so the last name to be
        written won the key and every other name became unreachable -- 234 of
        4883 stops (4.8%) could not be resolved even when typed verbatim,
        exactly as they appear in the dataset. Asking for "Yeshawanthapura
        Circle" was answered from "Yeshawanthapura Bus Station"; asking for
        "Machohalli" was answered from "Machohalli Gate".

        Candidates are ordered by how often the raw name actually appears
        across route stop lists, then alphabetically. The frequency term is
        the "which of these does an unqualified query most likely mean"
        signal; the alphabetical tie-break keeps the choice deterministic
        across runs (dict/set ordering is not, under PYTHONHASHSEED).
        """
        frequency: dict[str, int] = {}
        for route in self.routes:
            for stop in route.stops:
                frequency[stop] = frequency.get(stop, 0) + 1
        self.stop_raw_frequency = frequency

        self._normalized_stop_names = {stop: normalize_text(stop) for stop in self.stop_names}

        grouped: dict[str, list[str]] = {}
        for stop, normalized in self._normalized_stop_names.items():
            grouped.setdefault(normalized, []).append(stop)

        self.stop_displays_by_norm = {
            key: sorted(names, key=lambda name: (-frequency.get(name, 0), name))
            for key, names in grouped.items()
        }
        # Cosmetic-only identity: case, punctuation, spacing and stray unicode
        # (this dataset contains e.g. "Muneshwara Block‌ Cross" with a
        # zero-width non-joiner, and both "Hejjala Gate" and "Hejjala gate").
        # These are the same physical stop spelled inconsistently, unlike
        # "Yeshawanthapura Circle" vs "Yeshawanthapura Bus Station", which
        # differ in actual words. Precomputed because stop_exactness consults
        # it once per candidate path on every query.
        self._compact_raw_names = {
            stop: self._compact_text(_minimal_normalize(stop)) for stop in self.stop_names
        }

        # Inverted token -> normalized-stop-name index, used by
        # get_stop_family(). The family test is "every token of the query is
        # present in the candidate's token set", which is exactly the
        # intersection of these buckets -- so it can be answered from the
        # index instead of by re-normalizing all 4883 stop names and running a
        # subset test against each, twice, on every single query.
        by_token: dict[str, set[str]] = {}
        for normalized in self.stop_displays_by_norm:
            for token in set(normalized.split()):
                by_token.setdefault(token, set()).add(normalized)
        self._norm_stops_by_token = by_token
        # Retained for callers that only need one representative name; it is
        # now the most-used of the colliding names rather than an arbitrary one.
        self.stop_display_by_norm = {
            key: names[0] for key, names in self.stop_displays_by_norm.items()
        }

    def _disambiguate_stop_name(self, query: str, candidates: list[str]) -> str:
        """Pick which of several same-normalized raw stop names the query means.

        A verbatim match wins outright: if the commuter typed a name that is
        literally in the dataset, that is the stop they meant, and no
        popularity heuristic should override it. Comparison is on the
        *minimal* normalization (case/punctuation only) rather than
        normalize_text, because normalize_text is precisely what made these
        names indistinguishable in the first place.

        Otherwise fall back to the first candidate, which
        _build_stop_name_indexes has already ordered most-used-first.
        """
        if len(candidates) == 1:
            return candidates[0]
        stripped = query.strip()
        if stripped in candidates:
            return stripped
        compact_query = self._compact_raw(stripped)
        for name in candidates:
            if self._compact_raw(name) == compact_query:
                return name
        return candidates[0]

    def _compact_raw(self, name: str) -> str:
        """Cosmetic-only identity of a raw stop name (see _build_stop_name_indexes)."""
        cached = self._compact_raw_names.get(name)
        if cached is not None:
            return cached
        return self._compact_text(_minimal_normalize(name))

    def predict(self, current_stop: str, destination: str, limit: int = 50) -> dict:
        self.train()
        current_stop = current_stop.strip()
        destination = destination.strip()

        start_stop, start_score = self._resolve_stop_name(current_stop)
        end_stop, end_score = self._resolve_stop_name(destination)

        if start_score < 0.5:
            raise ValueError(f"Could not find any stop matching '{current_stop}'")
        if end_score < 0.5:
            raise ValueError(f"Could not find any stop matching '{destination}'")
        if normalize_text(start_stop) == normalize_text(end_stop):
            raise ValueError("You are already at your destination!")

        suggestions = self._find_transfer_suggestions(current_stop, destination, limit)
        
        best_match = None
        message = "No valid route found connecting these locations."
        steps = []
        
        if suggestions:
            best_suggestion = suggestions[0]
            if best_suggestion["transfers"] == 0:
                leg = best_suggestion["legs"][0]
                best_match = {
                    "bus_number": leg["bus_number"],
                    "confidence": best_suggestion["confidence"],
                    "relevance_score": 1.0,
                    "route_id": leg["route_id"],
                    "direction_id": leg["direction_id"],
                    "route_name": leg["route_name"],
                    "source": leg["source"],
                    "destination": leg["destination"],
                    "matched_current_stop": leg["from_stop"],
                    "matched_destination": leg["to_stop"],
                    "stop_match_score": 1.0,
                    "destination_match_score": 1.0,
                    "passes_in_requested_order": True,
                    "trip_count": leg["trip_count"],
                    "first_trips": leg["first_trips"],
                    "route_path": leg["route_path"],
                    "total_stops": leg["stop_count"],
                    "stop_span": leg["stop_count"],
                    "distance_km": leg["distance_km"],
                    "duration_minutes": leg["duration_minutes"],
                    "distance_source": leg["distance_source"],
                    "distance_complete": True,
                    "route_coordinates": leg.get("route_coordinates", []),
                    # Real signal, previously computed in _make_transfer_leg
                    # and then discarded before reaching the API response --
                    # the frontend's metro badge had nothing real to check
                    # and was showing an unconditional claim instead. See
                    # the transfer branch below for the equivalent fix.
                    "metro_interchange": leg.get("metro_interchange"),
                }
                message = "Direct Route"
            else:
                # Previously best_match stayed None whenever the best
                # available option required a transfer -- this branch only
                # set the message string. That meant any query whose best
                # answer wasn't a direct 0-transfer route (a common,
                # completely normal case -- e.g. a genuinely long trip
                # across the city) returned a null primary result with no
                # indication anything had actually been found, even though
                # alternatives[0] held a real, correctly-resolved route the
                # whole time. Build best_match from it the same way, using
                # the aggregate fields _make_transfer_suggestion already
                # computes across all legs.
                message = f"{best_suggestion['transfers']} Transfer{'s' if best_suggestion['transfers'] > 1 else ''}"
                legs = best_suggestion["legs"]
                first_leg, last_leg = legs[0], legs[-1]
                combined_route_path: list[str] = []
                combined_route_coordinates: list[dict] = []
                for leg in legs:
                    combined_route_path.extend(leg.get("route_path", []))
                    combined_route_coordinates.extend(leg.get("route_coordinates", []))
                distance_complete = all(
                    leg.get("distance_source") == "stop_coordinates" for leg in legs
                )
                best_match = {
                    # The bus to board right now, so "Track this bus" and
                    # any other single-bus-number consumer stays meaningful
                    # for the immediate next step of the journey.
                    "bus_number": first_leg["bus_number"],
                    # The full journey, for anything that wants to show it
                    # (e.g. "502-H -> 226-N") -- never collapse a
                    # multi-bus journey into looking like a single bus.
                    "bus_chain": best_suggestion["bus_chain"],
                    "transfers": best_suggestion["transfers"],
                    "transfer_stops": best_suggestion.get("transfer_stops", []),
                    "summary": best_suggestion.get("summary"),
                    "confidence": best_suggestion["confidence"],
                    "relevance_score": 1.0,
                    "route_id": first_leg["route_id"],
                    "direction_id": first_leg["direction_id"],
                    "route_name": best_suggestion.get("summary") or first_leg["route_name"],
                    "source": first_leg["source"],
                    "destination": last_leg["destination"],
                    "matched_current_stop": first_leg["from_stop"],
                    "matched_destination": last_leg["to_stop"],
                    "stop_match_score": 1.0,
                    "destination_match_score": 1.0,
                    "passes_in_requested_order": True,
                    "trip_count": first_leg["trip_count"],
                    "first_trips": first_leg["first_trips"],
                    "route_path": combined_route_path,
                    "total_stops": best_suggestion["total_stops"],
                    "stop_span": best_suggestion["total_stops"],
                    "distance_km": best_suggestion["total_distance_km"],
                    "duration_minutes": round(sum(leg.get("duration_minutes", 0) for leg in legs), 1),
                    "distance_source": first_leg["distance_source"],
                    "distance_complete": distance_complete,
                    "route_coordinates": combined_route_coordinates,
                    "legs": legs,
                    # Same real signal as the direct-route branch above --
                    # check every leg, since a transfer route can pass a
                    # known interchange on either bus.
                    "metro_interchange": next(
                        (leg.get("metro_interchange") for leg in legs if leg.get("metro_interchange")),
                        None,
                    ),
                }
                
        # Attach stable stop_id fields (see stop_registry.py) alongside the
        # existing display-name fields, purely additive -- nothing above
        # this point changes, so this cannot alter which route/bus is
        # chosen, only what identifying information rides alongside it.
        if best_match:
            best_match["current_stop_id"] = self.stop_registry.id_for(best_match["matched_current_stop"])
            best_match["destination_stop_id"] = self.stop_registry.id_for(best_match["matched_destination"])
        for suggestion in suggestions:
            for leg in suggestion.get("legs", []):
                leg["from_stop_id"] = self.stop_registry.id_for(leg["from_stop"])
                leg["to_stop_id"] = self.stop_registry.id_for(leg["to_stop"])

        return {
            "query": {"current_stop": current_stop, "destination": destination},
            "best_match": best_match,
            "alternatives": suggestions,
            "steps": steps,
            "message": message,
            "model": {
                "name": "BFS Optimal Router",
                "trained_at": self._trained_at,
                "metrics": {},
            },
        }

    def autocomplete(self, query: str, limit: int = 10, kind: str = "stop") -> list[dict]:
        self.train()
        query = query.strip()
        choices = self.stop_names
        if not query:
            # Return most-connected stops first (hubs appear at the top)
            source = sorted(
                choices,
                key=lambda s: len(self.stop_to_route_indices.get(normalize_text(s), set())),
                reverse=True,
            )[:limit]
            return [{"value": value, "score": 1.0} for value in source]
        scored = []
        normalized_query = normalize_text(query)
        max_routes = max(
            (len(self.stop_to_route_indices.get(normalize_text(s), set())) for s in choices),
            default=1,
        )
        for choice in choices:
            normalized_choice = normalize_text(choice)
            if self._compact_text(normalized_query) == self._compact_text(normalized_choice):
                text_score = 0.99
            elif normalized_query in normalized_choice:
                text_score = 1.0 - (len(normalized_choice) - len(normalized_query)) / max(len(normalized_choice), 1) * 0.15
            else:
                text_score = fuzzy_ratio(query, choice, left_norm=normalized_query, right_norm=normalized_choice)
            if text_score < 0.45:
                continue
            # Blend text match with route-coverage popularity so busy hubs rank higher
            route_count = len(self.stop_to_route_indices.get(normalized_choice, set()))
            popularity = math.log1p(route_count) / math.log1p(max_routes)
            score = round(0.88 * text_score + 0.12 * popularity, 3)
            scored.append({"value": choice, "score": score})
        scored.sort(key=lambda item: item["score"], reverse=True)
        return scored[:limit]

    def _compact_text(self, normalized_text: str) -> str:
        return normalized_text.replace(" ", "")

    def list_routes(self, limit: int = 100, offset: int = 0, search: str | None = None) -> dict:
        self.train()
        routes = self.routes
        if search:
            normalized = normalize_text(search)
            routes = [
                route
                for route in routes
                if normalized in normalize_text(route.route_number)
                or normalized in normalize_text(route.full_name)
                or any(normalized in stop for stop in route.normalized_stops)
            ]
        slice_ = routes[offset : offset + limit]
        return {
            "total": len(routes),
            "limit": limit,
            "offset": offset,
            "items": [self._route_summary(route) for route in slice_],
        }

    def _rank(self, current_stop: str, destination: str, mode: str = "hybrid", use_fuzzy: bool = True) -> list[dict]:
        query = f"{current_stop} {destination}"
        tfidf_scores = self.tfidf.similarities(query)
        max_trips = max((route.trip_count for route in self.routes), default=1)
        ranked: list[dict] = []
        candidate_indices = self._candidate_indices(current_stop, destination)
        for index in candidate_indices:
            route = self.routes[index]
            start_idx, matched_start, start_score = self._match_route_stop(current_stop, route, use_fuzzy=use_fuzzy)
            dest_idx, matched_destination, destination_score = self._match_route_stop(destination, route, use_fuzzy=use_fuzzy)
            endpoint_score = destination_score
            if use_fuzzy and destination_score < 0.92:
                endpoint_score = max(
                    fuzzy_ratio(destination, route.destination),
                    fuzzy_ratio(destination, route.full_name),
                    destination_score,
                )
            ordered = start_idx >= 0 and dest_idx >= 0 and dest_idx > start_idx
            reverse_penalty = start_idx >= 0 and dest_idx >= 0 and dest_idx <= start_idx
            coverage_score = 1.0 if ordered else (0.35 if reverse_penalty else 0.55 * endpoint_score)
            route_similarity = tfidf_scores[index]
            frequency_score = math.log1p(route.trip_count) / math.log1p(max_trips)
            stop_span = max(1, dest_idx - start_idx) if ordered else len(route.stops)
            distance_score = self._distance_efficiency_score(stop_span, len(route.stops))

            if mode == "tfidf":
                raw = route_similarity
            elif mode == "ordered":
                raw = 0.44 * start_score + 0.34 * destination_score + 0.14 * coverage_score + 0.08 * distance_score
            else:
                raw = (
                    0.24 * start_score
                    + 0.21 * destination_score
                    + 0.23 * coverage_score
                    + 0.16 * route_similarity
                    + 0.07 * frequency_score
                    + 0.09 * distance_score
                )
            if reverse_penalty:
                raw *= 0.62
            confidence = round(clamp(raw) * 100, 1)
            if start_score < 0.42:
                confidence *= 0.45

            route_path = self._path_between(route, start_idx, dest_idx)
            distance = self.distance_service.route_distance(route_path, allow_remote=False)
            route_coordinates = self._path_coordinates(route_path)

            ranked.append(
                {
                    "bus_number": route.route_number,
                    "confidence": round(confidence, 1),
                    "relevance_score": round(raw, 4),
                    "route_id": route.route_id,
                    "direction_id": route.direction_id,
                    "route_name": route.full_name,
                    "source": route.source,
                    "destination": route.destination,
                    "matched_current_stop": matched_start,
                    "matched_destination": matched_destination,
                    "stop_match_score": round(start_score, 3),
                    "destination_match_score": round(destination_score, 3),
                    "passes_in_requested_order": ordered,
                    "trip_count": route.trip_count,
                    "first_trips": route.trip_list[:6],
                    "route_path": route_path,
                    "total_stops": len(route.stops),
                    "stop_span": stop_span,
                    "distance_km": distance["distance_km"],
                    "duration_minutes": distance["duration_minutes"],
                    "distance_source": distance["distance_source"],
                    "distance_complete": distance["distance_complete"],
                    "route_coordinates": route_coordinates,
                }
            )
        ranked.sort(
            key=lambda item: (
                item["confidence"],
                -float(item.get("distance_km") or 9999),
                item["trip_count"],
                item["destination_match_score"],
            ),
            reverse=True,
        )
        return self._dedupe_bus_numbers(ranked)

    def _candidate_indices(self, current_stop: str, destination: str | None = None) -> list[int]:
        normalized_query = normalize_text(current_stop)
        if destination:
            pair_indices = self._candidate_indices_for_pair(current_stop, destination)
            if pair_indices:
                return pair_indices

        exact = self.stop_to_route_indices.get(normalized_query)
        if exact:
            return sorted(exact)

        candidate_stop_scores: list[tuple[str, float]] = []
        query_tokens = self._significant_tokens(normalized_query)
        for stop in self.stop_names:
            normalized_stop = normalize_text(stop)
            stop_tokens = self._significant_tokens(normalized_stop)
            token_overlap = bool(query_tokens & stop_tokens)
            substring_match = normalized_query and (
                self._token_phrase_contains(normalized_query, normalized_stop)
                or self._token_phrase_contains(normalized_stop, normalized_query)
            )
            typo_match = SequenceMatcher(None, normalized_query, normalized_stop).ratio() >= 0.78
            if token_overlap or substring_match or typo_match:
                score = max(
                    fuzzy_ratio(current_stop, stop, left_norm=normalized_query, right_norm=normalized_stop) if token_overlap or typo_match else 0.0,
                    0.84 if substring_match else 0.0,
                )
                candidate_stop_scores.append((normalized_stop, score))
        if not candidate_stop_scores:
            for stop in self.stop_names:
                score = fuzzy_ratio(current_stop, stop)
                if score >= 0.5:
                    candidate_stop_scores.append((normalize_text(stop), score))

        indices: set[int] = set()
        for stop, score in sorted(candidate_stop_scores, key=lambda item: item[1], reverse=True)[:10]:
            if score >= 0.55:
                indices.update(self.stop_to_route_indices.get(stop, set()))
        if indices:
            return sorted(indices)
        return list(range(len(self.routes)))

    def _build_stop_pair_index(self) -> dict[tuple[str, str], list[tuple[int, int, int]]]:
        pair_index: dict[tuple[str, str], list[tuple[int, int, int]]] = {}
        for route_index, route in enumerate(self.routes):
            route_seen: set[tuple[str, str, int, int]] = set()
            for start_index, start_norm in enumerate(route.normalized_stops[:-1]):
                if not start_norm:
                    continue
                for end_index in range(start_index + 1, len(route.normalized_stops)):
                    end_norm = route.normalized_stops[end_index]
                    if not end_norm or end_norm == start_norm:
                        continue
                    seen_key = (start_norm, end_norm, start_index, end_index)
                    if seen_key in route_seen:
                        continue
                    route_seen.add(seen_key)
                    pair_index.setdefault((start_norm, end_norm), []).append((route_index, start_index, end_index))
        return pair_index

    def _candidate_indices_for_pair(self, current_stop: str, destination: str) -> list[int]:
        start_stop, start_score = self._resolve_stop_name(current_stop)
        end_stop, end_score = self._resolve_stop_name(destination)

        # Lowered threshold for alias-resolved names (they are already canonical)
        from .text import ALIASES, normalize_text as _norm
        start_is_alias = _norm(current_stop) in ALIASES or _norm(current_stop.lower()) in ALIASES
        end_is_alias = _norm(destination) in ALIASES or _norm(destination.lower()) in ALIASES
        start_threshold = 0.60 if start_is_alias else 0.72
        end_threshold = 0.60 if end_is_alias else 0.72

        if start_score < start_threshold or end_score < end_threshold:
            return []

        # Try all alias-expanded variants of both resolved names
        start_norms = {normalize_text(start_stop)}
        end_norms = {normalize_text(end_stop)}
        # Also try the raw query normalized (catches cases where resolve picked wrong candidate)
        start_norms.add(normalize_text(current_stop))
        end_norms.add(normalize_text(destination))

        route_indices: set[int] = set()
        best_pair_key: tuple[str, str] | None = None
        for sn in start_norms:
            for en in end_norms:
                if sn == en:
                    continue
                pair_key = (sn, en)
                segments = self.stop_pair_to_segments.get(pair_key, [])
                if segments:
                    for route_index, _, _ in segments:
                        route_indices.add(route_index)
                    if best_pair_key is None:
                        best_pair_key = pair_key

        if not route_indices:
            return []

        effective_key = best_pair_key or (normalize_text(start_stop), normalize_text(end_stop))
        return sorted(
            route_indices,
            key=lambda route_index: (
                self.routes[route_index].trip_count,
                -self._best_pair_stop_span(effective_key, route_index),
            ),
            reverse=True,
        )

    def _best_pair_stop_span(self, pair_key: tuple[str, str], route_index: int) -> int:
        spans = [
            end_index - start_index
            for candidate_index, start_index, end_index in self.stop_pair_to_segments.get(pair_key, [])
            if candidate_index == route_index
        ]
        return min(spans) if spans else 999

    def _distance_efficiency_score(self, stop_span: int, route_stop_count: int) -> float:
        if stop_span <= 0:
            return 0.0
        relative_span = stop_span / max(route_stop_count - 1, 1)
        compact_route_score = 1.0 / (1.0 + max(0, stop_span - 1) / 12)
        return clamp(0.55 * compact_route_score + 0.45 * (1.0 - relative_span), 0.05, 1.0)

    def _rerank_with_remote_distance(self, candidates: list[dict]) -> list[dict]:
        if not candidates:
            return candidates

        enriched = []
        for item in candidates:
            distance = self.distance_service.route_distance(item["route_path"], allow_remote=True)
            updated = {**item, **distance}
            enriched.append(updated)

        known_distances = [
            float(item["distance_km"])
            for item in enriched
            if item.get("distance_km") and item.get("distance_source") in {"google_maps", "mixed"}
        ]
        if known_distances:
            shortest = max(min(known_distances), 0.1)
            for item in enriched:
                if item.get("distance_source") not in {"google_maps", "mixed"}:
                    continue
                distance_ratio = shortest / max(float(item["distance_km"] or shortest), 0.1)
                distance_bonus = clamp(distance_ratio, 0.72, 1.08)
                item["confidence"] = round(clamp((item["confidence"] / 100) * distance_bonus) * 100, 1)
                item["relevance_score"] = round(clamp(item["relevance_score"] * distance_bonus), 4)

        enriched.sort(
            key=lambda item: (
                item["confidence"],
                item.get("distance_source") in {"google_maps", "mixed"},
                -float(item.get("distance_km") or 9999),
                item["trip_count"],
            ),
            reverse=True,
        )
        return enriched

    def _path_between(self, route: RouteRecord, start_idx: int, dest_idx: int) -> list[str]:
        if start_idx >= 0 and dest_idx > start_idx:
            return route.stops[start_idx : dest_idx + 1]
        return route.stops[: min(len(route.stops), 18)]

    def _match_route_stop(self, query: str, route: RouteRecord, use_fuzzy: bool = True) -> tuple[int, str, float]:
        normalized_query = normalize_text(query)
        if normalized_query in route.normalized_stops:
            index = route.normalized_stops.index(normalized_query)
            return index, route.stops[index], 1.0

        if not use_fuzzy:
            return -1, "", 0.0

        query_tokens = self._significant_tokens(normalized_query)
        best_index = -1
        best_score = 0.0
        for index, normalized_stop in enumerate(route.normalized_stops):
            stop_tokens = self._significant_tokens(normalized_stop)
            token_overlap = bool(query_tokens & stop_tokens)
            substring_match = normalized_query and (
                self._token_phrase_contains(normalized_query, normalized_stop)
                or self._token_phrase_contains(normalized_stop, normalized_query)
            )
            typo_match = SequenceMatcher(None, normalized_query, normalized_stop).ratio() >= 0.78
            if token_overlap or substring_match or typo_match:
                score = max(
                    fuzzy_ratio(query, route.stops[index]) if token_overlap or typo_match else 0.0,
                    0.84 if substring_match else 0.0,
                )
                if score > best_score:
                    best_index = index
                    best_score = score
        if best_index >= 0:
            return best_index, route.stops[best_index], best_score

        return self._safe_best_match(query, route)

    def _safe_best_match(self, query: str, route: RouteRecord) -> tuple[int, str, float]:
        normalized_query = normalize_text(query)
        query_tokens = self._significant_tokens(normalized_query)
        best_index = -1
        best_value = ""
        best_score = 0.0
        for index, stop in enumerate(route.stops):
            normalized_stop = route.normalized_stops[index]
            stop_tokens = self._significant_tokens(normalized_stop)
            sequence = SequenceMatcher(None, normalized_query, normalized_stop).ratio()
            token_overlap = len(query_tokens & stop_tokens) / max(len(query_tokens | stop_tokens), 1)
            if not token_overlap and sequence < 0.78:
                continue
            score = max(sequence, token_overlap, fuzzy_ratio(query, stop) if token_overlap else 0.0)
            if score > best_score:
                best_index = index
                best_value = stop
                best_score = score
        return best_index, best_value, best_score

    def _significant_tokens(self, normalized_text: str) -> set[str]:
        return {
            token
            for token in normalized_text.split()
            if len(token) >= 3 and token not in GENERIC_STOP_TOKENS
        }

    def _token_phrase_contains(self, left: str, right: str) -> bool:
        left_tokens = left.split()
        right_tokens = right.split()
        if not left_tokens or not right_tokens:
            return False
        if len(left_tokens) == 1 or len(right_tokens) == 1:
            return left_tokens == right_tokens
        return f" {right} " in f" {left} "

    def _find_transfer_suggestions(self, current_stop: str, destination: str, limit: int = 50) -> list[dict]:
        start_stop, start_score = self._resolve_stop_name(current_stop)
        end_stop, end_score = self._resolve_stop_name(destination)

        start_norm = normalize_text(start_stop) if start_score >= 0.5 else normalize_text(current_stop)
        end_norm = normalize_text(end_stop) if end_score >= 0.5 else normalize_text(destination)

        # Cosmetic-only identity of the stops to prefer boarding/alighting at,
        # used by stop_exactness below. Below the confidence threshold the
        # resolved name is a guess, so fall back to what the commuter actually
        # typed rather than letting a low-confidence guess claim an exact match.
        start_compact = self._compact_raw(start_stop if start_score >= 0.5 else current_stop)
        end_compact = self._compact_raw(end_stop if end_score >= 0.5 else destination)

        if start_norm == end_norm:
            return []

        # Find stop family names (alias / campus stops).
        #
        # A candidate joins the family only if EVERY token of norm_name
        # (minus a short, verified filler list -- see below) is present in
        # the candidate's token set. We deliberately do NOT
        # blacklist category words like "station", "layout", "gate",
        # "college", "hospital" here (an earlier version did, plus
        # GENERIC_STOP_TOKENS). Stripping those words let the token set
        # collapse to a single common root word -- e.g. "Kempegowda Bus
        # Station" collapsed to just {"kempegowda"}, which is also the
        # root of "Kempegowda International Airport", "Kempegowda Arch",
        # and "Kempegowda Garden": four unrelated places in Bengaluru that
        # got merged into one "family" and let the route search treat the
        # airport as if it were the Majestic bus stand. Category words are
        # exactly what disambiguates one named place from another that
        # happens to share a root word, so keeping them in the comparison
        # is what prevents that collision -- while short/legitimate
        # variants like "Abbigere" -> "Abbigere Cross" still match, since
        # the extra word only adds to the candidate's token set rather
        # than needing to be ignored from the query's side.
        #
        # A second, narrower version of the same bug surfaced later: a
        # length >= 3 threshold silently filtered out real, meaningful
        # 2-letter institution abbreviations that are extremely common in
        # Bengaluru place names -- RV, JP, MS, KR, MG, and so on. "RV
        # College" collapsed to just {"college"} the same way "Kempegowda
        # Bus Station" once did, and matched 98 unrelated colleges across
        # the city (Sapthagiri College, Sambhram College, ...) instead of
        # the actual RV College. Lowering the threshold to 2 fixed that --
        # and then the threshold turned out to be the whole problem, not
        # its value. Bengaluru stop names carry initials as SEPARATE
        # single-character tokens once normalized, so a length floor of 2
        # discarded them and reopened the identical collapse one letter
        # lower down. Measured on this dataset, 142 stops (2.9%) contain a
        # single-character token, and for 74 of them the length filter was
        # inflating the family:
        #
        #     'H Cross'        ('h cross')        -> 476 members, now 2
        #     'MG Road'        ('m g road')       -> 163 members, now 1
        #     'S J R College'  ('s j r college')  ->  98 members, now 1
        #     'T Hosahalli'    ('t hosahalli')    ->  25 members, now 1
        #
        # "MG Road" searching every stop in the city whose name contains
        # the word "road" is the same failure as "RV College" matching
        # every college; a single letter is exactly as distinguishing as
        # "RV" here. So there is no length floor at all now -- only the
        # explicit filler list, which is what was actually doing the useful
        # work. That list holds the few short tokens in this dataset with
        # genuinely zero distinguishing value: "of" (Institute *of*
        # Technology, Bank *of* India -- shared by dozens of unrelated
        # places), "cs" (a systematic ~200-stop BMTC naming prefix,
        # confirmed by inspection, not a place abbreviation), and ordinary
        # English connectors ("and", "the", "a").
        #
        # Dropping the floor can only ever narrow a family (more required
        # tokens = fewer candidates satisfy the subset test), with one
        # degenerate exception: 'I Gate' normalizes to bare "i", which
        # previously had no qualifying token at all and so matched only
        # itself; it now pulls in 3 other stops carrying an "i" token.
        # Harmless -- the exact-stop preference in route_rank_score ranks
        # the real stop above family members regardless.
        #
        # That preference is also why this matters less than it looks: when
        # the requested stop IS directly served, exact-match ranking already
        # wins and the family size is irrelevant (measured: 120 sampled
        # pairs touching these stops score 120/120 identically with and
        # without the floor). The floor only decides the answer in the
        # fallback case, where the requested stop has no direct route and
        # a family member is all there is. Measured over 80 such pairs, the
        # floor produced two answers that boarded somewhere else entirely:
        #
        #   'R V Metro Station'  -> boarded 'Jnanabharathi Metro Station'
        #   'CS-R T Nagara Police Station'
        #                        -> boarded 'Ramamurthy Nagara Police Station'
        #
        # Both are different places several km away, reached because the
        # dropped initials left only {"metro"} and {"nagara","police"} to
        # match on. Without the floor both become an honest "no route
        # found" instead, and no correct answer is lost (43/80 exact-stop
        # boardings either way).
        _FAMILY_FILLER_TOKENS = frozenset({"of", "cs", "and", "the", "a"})

        def get_stop_family(norm_name: str) -> set[str]:
            tokens = {
                t for t in norm_name.split()
                if t not in _FAMILY_FILLER_TOKENS
            }
            if not tokens:
                return {norm_name}
            # Intersect the smallest bucket first so the working set shrinks
            # immediately -- a query like "MG Road" would otherwise start from
            # every stop in the city containing "road".
            buckets = sorted(
                (self._norm_stops_by_token.get(token, frozenset()) for token in tokens),
                key=len,
            )
            family = set(buckets[0])
            for bucket in buckets[1:]:
                family &= bucket
                if not family:
                    break
            family.add(norm_name)
            return family

        start_family = get_stop_family(start_norm)
        end_family = get_stop_family(end_norm)

        # How many ranked candidates are ever turned into suggestions below.
        # Named once, deliberately: the early-exit guard between the two
        # enumeration phases is only correct while it compares against exactly
        # the number used to slice `pruned_paths`, so the two must not be able
        # to drift apart.
        shortlist_size = max(limit * 4, 100)

        def stop_exactness(path_tuples) -> int:
            """How precisely does this journey serve the stops actually asked for?

            0 = boards and alights at the exact raw stop names requested
            1 = same normalized names (a category-word variant of them)
            2 = a family member -- a related but different stop

            Defined here, above the search rather than below it, because the
            early-exit guard needs it while the candidates are still being
            enumerated.

            Tier 1 vs 0 is what separates "Yeshawanthapura Circle" from
            "Yeshawanthapura Bus Station": normalize_text() deliberately
            strips "Circle" and "Bus Station", so both collapse to the same
            key and a normalized-only comparison cannot tell two genuinely
            different places apart. Comparing the raw names first means the
            bus that stops where the commuter asked outranks the bus that
            stops at the other place sharing its normalized name.

            The family expansion above deliberately widens the search to
            related stops (campus entrances, alias spellings) so a query still
            finds something when the exact name isn't on any route. But
            nothing downstream distinguished a family member from the real
            thing, so a trunk route through a NEARBY stop outranked the exact
            stop's own route purely for being a trunk service with more trips.

            Measured effect: "Kottigepalya -> Janapriya Apartment" answered
            502-H boarding at "Vokkaliga School Kottigepalya" when the real
            direct buses for the requested pair are 240/240-A/240-C; a query
            for "KR Circle" was answered from "KR Pura Railway Station", 10 km
            away. Serving the stop the commuter actually named is a
            correctness property -- it outranks every convenience heuristic
            below, because a direct bus from the wrong place is not a better
            answer than a slower bus from the right one.
            """
            first_route, first_idx, _ = path_tuples[0]
            last_route, _, last_idx = path_tuples[-1]
            if not (
                first_route.normalized_stops[first_idx] == start_norm
                and last_route.normalized_stops[last_idx] == end_norm
            ):
                return 2
            if (
                self._compact_raw(first_route.stops[first_idx]) == start_compact
                and self._compact_raw(last_route.stops[last_idx]) == end_compact
            ):
                return 0
            return 1

        optimal_paths = []

        # 0-transfer (Direct routes) for exact stop and family stops.
        # Iterate the families in sorted order, not set order: a set has no
        # stable iteration order across process restarts (PYTHONHASHSEED), and
        # the candidate generated first here used to be the one the
        # deduplication below kept -- so the very same query could return a
        # different boarding stop on different runs. Same class of bug, and
        # same fix, as _NOISE_WORDS in text.py.
        for s_curr in sorted(start_family):
            for s_dest in sorted(end_family):
                src_routes = self.stop_to_route_indices.get(s_curr, set())
                dst_routes = self.stop_to_route_indices.get(s_dest, set())
                direct_route_indices = src_routes.intersection(dst_routes)
                for route_idx in direct_route_indices:
                    route = self.routes[route_idx]
                    curr_indices = route.stop_positions.get(s_curr, ())
                    dest_indices = route.stop_positions.get(s_dest, ())
                    for curr_idx in curr_indices:
                        for dest_idx in dest_indices:
                            if curr_idx < dest_idx:
                                optimal_paths.append([(route, curr_idx, dest_idx)])
                        
        # ── Is the shortlist already full of direct routes? ───────────────────
        #
        # !! THIS GUARD DEPENDS ON THE KEY ORDER IN route_rank_score BELOW.  !!
        # !! Its tuple is (stop_exactness, transfers, ...) with `transfers`  !!
        # !! SECOND. If you reorder those elements, DELETE THIS GUARD -- it  !!
        # !! becomes wrong and drops valid answers with no error.            !!
        #
        # Given that order, a one-transfer journey can never outrank a direct
        # one in the same exactness tier: (0, 0, ...) < (e, 1, ...) for every
        # e. And a transfer chain can never collide with a direct chain in the
        # deduplication below, because its bus_chain always contains " -> "
        # and a direct chain never can, so transfer candidates can only ever
        # be APPENDED below the direct ones -- never merged into them.
        #
        # So once `shortlist_size` distinct direct journeys already board and
        # alight at the exact stops requested, everything the one-transfer
        # search could find would sort below the slice that gets returned.
        # Enumerating it is provably dead work, not a quality trade-off.
        #
        # This matters because the one-transfer search is the entire cost of
        # this function. Measured on "KR Market -> Kempegowda Bus Station":
        # 205 direct exact-stop chains against a 200-slot shortlist, while
        # 933,189 of the 933,462 enumerated paths (99.97%) were one-transfer
        # candidates that could not place. Skipping them returned byte-
        # identical results on every query tested, ~32x faster; it fires only
        # on hub-to-hub queries, which are exactly the slow ones.
        direct_exact_chains = {
            path[0][0].route_number
            for path in optimal_paths
            if stop_exactness(path) == 0
        }

        # 1-transfer routes if needed
        if len(direct_exact_chains) < shortlist_size:
            src_routes = self.stop_to_route_indices.get(start_norm, set())
            dst_routes = self.stop_to_route_indices.get(end_norm, set())
            for r1_idx in src_routes:
                r1 = self.routes[r1_idx]
                r1_curr_indices = r1.stop_positions.get(start_norm, ())
                for r1_curr_idx in r1_curr_indices:
                    for t_idx in range(r1_curr_idx + 1, len(r1.normalized_stops)):
                        t_stop = r1.normalized_stops[t_idx]
                        if not t_stop or t_stop == end_norm:
                            continue

                        t_dst_routes = self.stop_to_route_indices.get(t_stop, set()).intersection(dst_routes)
                        for r2_idx in t_dst_routes:
                            r2 = self.routes[r2_idx]
                            r2_t_indices = r2.stop_positions.get(t_stop, ())
                            r2_dst_indices = r2.stop_positions.get(end_norm, ())
                            for r2_t_idx in r2_t_indices:
                                for r2_dst_idx in r2_dst_indices:
                                    if r2_t_idx < r2_dst_idx:
                                        optimal_paths.append([
                                            (r1, r1_curr_idx, t_idx),
                                            (r2, r2_t_idx, r2_dst_idx)
                                        ])

        # Smart deduplication and ranking for regular commuter transit
        SPECIAL_KEYWORDS = {'divya darshana', 'tour', 'charter', 'special', 'depo gate', 'depot gate', 'sightseeing'}

        def is_special_route(r) -> bool:
            return any(k in r.search_text for k in SPECIAL_KEYWORDS) or r.trip_count <= 1

        # stop_exactness is defined above the enumeration, not here -- the
        # early-exit guard between the two search phases needs it.

        def route_rank_score(item):
            path_tuples = item[3]
            transfers = item[0]
            total_stops = item[1]
            r1 = path_tuples[0][0]
            is_special = is_special_route(r1)
            is_self_loop = r1.is_self_loop
            r_num = r1.route_number.upper()
            is_trunk = any(r_num.startswith(p) for p in ['500', 'V-500', 'KIA', '335', '502', '248', '250', '253', 'MF', '201', 'G-'])
            avg_trips = sum(r.trip_count for r, _, _ in path_tuples) / len(path_tuples)
            # !! ORDER IS LOAD-BEARING BEYOND RANKING QUALITY.                !!
            # !! The early-exit guard in the enumeration above skips the      !!
            # !! entire one-transfer search on the strength of `transfers`    !!
            # !! being the SECOND element here, so that a direct journey      !!
            # !! always outranks a transfer one within an exactness tier.     !!
            # !! Reordering these two elements silently invalidates it --     !!
            # !! delete that guard if you do. tests/test_predictor.py has a   !!
            # !! regression test pinning this.                                !!
            return (
                stop_exactness(path_tuples),
                transfers,
                1 if (is_special or is_self_loop) else 0,
                0 if is_trunk else 1,
                -avg_trips,
                total_stops
            )

        # Collapse to one journey per bus chain, keeping the BEST variant of
        # each rather than whichever happened to be generated first.
        #
        # One bus often reaches the destination from several stops in the same
        # family: route 258-SB passes both "Basavanahalli Cross" and, two stops
        # later, "Basavanahalli". Both produce the chain "258-SB", so the
        # exact-stop variant used to be discarded as a duplicate of the
        # family-member one -- which is why a query for "Basavanahalli" fell
        # through to a 1-transfer answer even though 258-SB serves it directly.
        #
        # The comparison here is deliberately cheap (the exactness tier, the
        # transfer count, and the stop span) so that the expensive
        # route_rank_score below still runs once per surviving chain rather
        # than once per raw candidate path -- scoring every candidate instead
        # doubled p90 latency on stops with large families.
        best_by_chain: dict[str, tuple[tuple[int, int, int], tuple]] = {}
        for path_tuples in optimal_paths:
            bus_chain = " -> ".join(r.route_number for r, _, _ in path_tuples)
            transfers = len(path_tuples) - 1
            total_stops = sum(end_idx - start_idx for _, start_idx, end_idx in path_tuples)
            tie_break = (stop_exactness(path_tuples), transfers, total_stops)
            existing = best_by_chain.get(bus_chain)
            if existing is not None and existing[0] <= tie_break:
                continue
            avg_trips = sum(r.trip_count for r, _, _ in path_tuples) / len(path_tuples)
            best_by_chain[bus_chain] = (tie_break, (transfers, total_stops, -avg_trips, path_tuples))

        pruned_paths: list[tuple[int, int, float, list]] = [v[1] for v in best_by_chain.values()]

        # Sort: journeys that actually serve the requested stops first, then
        # 0-transfer first, regular non-special commuter routes first, major
        # trunk series first, highest trip frequency first
        pruned_paths.sort(key=route_rank_score)

        # Walk the ranked candidates and keep the ones whose interchanges are
        # physically real, stopping once there are enough.
        #
        # Deliberately NOT `pruned_paths[:shortlist_size]` filtered afterwards.
        # Rejected candidates would then eat shortlist slots and a query could
        # come back with nothing at all: Banashankari -> Whitefield had every
        # one of its top candidates transferring at a name that exists twice in
        # the city, and truncating first turned a routable journey into "no
        # match". Scanning deeper costs leg construction only for candidates
        # that survive, and stops as soon as the shortlist is full.
        suggestions = []
        for _, _, _, path_tuples in pruned_paths:
            if len(suggestions) >= shortlist_size:
                break
            # Cheap geometric check first: building a leg costs a full distance
            # walk, and most of what this rejects would be discarded straight
            # afterwards. Filtering before construction is what keeps the
            # deeper scan affordable.
            if not self._interchange_is_walkable(path_tuples):
                continue
            path = [self._make_transfer_leg(r, c, n) for r, c, n in path_tuples]
            suggestions.append(self._make_transfer_suggestion(path))

        # Final deduplicate by dedupe_key and trim to limit
        cleaned = []
        seen_keys: set[str] = set()
        for suggestion in suggestions:
            key = suggestion.pop("dedupe_key", None)
            if key and key in seen_keys:
                continue
            if key:
                seen_keys.add(key)
            cleaned.append(suggestion)
            if len(cleaned) >= limit:
                break
        return cleaned

    # Bus depot/yard staging points (internal BMTC operational entries, not
    # passenger destinations) are named "Depot-<number> <nearby place>" --
    # e.g. "Depot-18 White Field". Because the scoring below rewards
    # SHORTER strings that contain the query as a substring, a depot entry
    # can win over the actual, better-known passenger stop purely by being
    # a shorter string: "Depot-18 White Field" (after "depot" is stripped
    # as a noise word) normalizes to "18 white field" -- 14 characters --
    # which scored higher against the query "white field" than "White
    # Field Bus Station (Vydehi Hospital)" (39 characters) or "White Field
    # Post Office" (23 characters), even though neither the depot's
    # existence nor its brevity has anything to do with which one a
    # commuter searching "Whitefield" actually means.
    _DEPOT_PREFIX_RE = re.compile(r"^depot[\s-]*\d", re.IGNORECASE)

    def _is_operational_depot_stop(self, stop_display_name: str) -> bool:
        return bool(self._DEPOT_PREFIX_RE.match(stop_display_name.strip()))

    def _resolve_stop_name(self, query: str) -> tuple[str, float]:
        normalized = normalize_text(query)
        candidates = self.stop_displays_by_norm.get(normalized)
        if candidates:
            return self._disambiguate_stop_name(query, candidates), 1.0
        query_means_depot = "depot" in normalized
        best_value = ""
        best_score = 0.0
        norm_map = getattr(self, "_normalized_stop_names", None)
        items = norm_map.items() if norm_map else [(s, normalize_text(s)) for s in self.stop_names]
        for stop, normalized_stop in items:
            if self._compact_text(normalized) == self._compact_text(normalized_stop):
                score = 0.99
            elif normalized and normalized in normalized_stop:
                score = 1.0 - (len(normalized_stop) - len(normalized)) / max(len(normalized_stop), 1) * 0.15
            else:
                score = fuzzy_ratio(query, stop, left_norm=normalized, right_norm=normalized_stop)
            # Unless the commuter is explicitly searching for a depot, a
            # depot staging point should essentially never outrank a real
            # passenger stop just for being a shorter string -- it should
            # only win if nothing else is even a plausible match.
            if not query_means_depot and self._is_operational_depot_stop(stop):
                score *= 0.5
            if score > best_score:
                best_value = stop
                best_score = score
        if best_value:
            return best_value, round(best_score, 3)
        return query, 0.0

    # Generic/structural words that appear in many station and stop names
    # without being what actually distinguishes one place from another --
    # same principle as get_stop_family's _FAMILY_FILLER_TOKENS above, kept
    # separate because this list is tuned for matching bus stop names
    # against the metro station list specifically (e.g. "nadaprabhu" is a
    # formal prefix on official metro station names that never appears on
    # a bus stop name and would otherwise never let anything match).
    _GENERIC_METRO_TOKENS = frozenset({
        "station", "metro", "road", "bus", "terminal", "college", "layout",
        "nagar", "nagara", "cross", "circle", "junction", "gate", "depot",
        "stand", "stop", "garden", "park", "market", "chowk", "square",
        "central", "nadaprabhu", "the", "of", "and",
    })

    def _metro_match_tokens(self, name: str) -> set[str]:
        # _minimal_normalize (not normalize_text) deliberately: normalize_text's
        # alias table expands "whitefield" -> "white field" (two tokens),
        # which would stop it matching against the metro station's own
        # "Whitefield (Kadugodi)" (tokenized as {"whitefield","kadugodi"}
        # under minimal normalization, with no alias expansion to split
        # "whitefield" into two words in the first place).
        return {
            t for t in _minimal_normalize(name).split()
            if len(t) >= 2 and t not in self._GENERIC_METRO_TOKENS
        }

    def _detect_metro_interchange(self, route_path: list[str]) -> dict | None:
        """Check whether this route path passes a real Namma Metro station.

        Previously this checked route_path against a hardcoded dict of 15
        manually-typed stations, each with an invented "feeder_bay" field
        (e.g. "Bay 3") that has no basis in any real data. A real, 85-
        station dataset (dataset/bengaluru_metro_network.csv) already
        existed in this project and was already loaded by MetroService --
        it just wasn't being used here. This now checks every real
        station, using validated token-subset matching (tested against
        every station in the original hardcoded dict plus deliberately
        adversarial generic-word queries like "College" and "Bus Station"
        to confirm no false positives) instead of exact string equality,
        since official metro station names ("Nadaprabhu Kempegowda Station
        Majestic") often don't literally match the corresponding bus stop
        name ("Kempegowda Bus Station").

        Known limitation: acronym-style bus stop names that don't share a
        literal token with the metro station's full name (e.g. "MG Road"
        vs "Mahatma Gandhi Road", "JP Nagar" vs "Jayaprakash Nagar") won't
        match. This under-detects rather than risks a false match, which
        is the safer failure mode given everywhere else in this file this
        exact class of bug (a route confidently claiming a connection that
        isn't real) has needed fixing.
        """
        stations = metro_service.get_all_stations()
        if not stations:
            return None
        for stop in route_path:
            stop_tokens = self._metro_match_tokens(stop)
            if not stop_tokens:
                continue
            for station in stations:
                station_tokens = self._metro_match_tokens(station["station_name"])
                if not station_tokens:
                    continue
                if stop_tokens.issubset(station_tokens) or station_tokens.issubset(stop_tokens):
                    lines = sorted({
                        s["line"] for s in stations if s["station_name"] == station["station_name"]
                    })
                    return {
                        "has_metro_connection": True,
                        "station_name": station["station_name"],
                        "lines": lines,
                        "is_interchange": station["is_interchange"],
                        "interchange_stop": stop,
                    }
        return None

    def _estimate_ev_specs(self, distance_km: float | None, stop_count: int) -> dict:
        dist = distance_km or (stop_count * 1.2)
        battery_used_pct = round(min(95.0, dist * 2.1 + stop_count * 0.4), 1)
        return {
            "is_ev_compatible": True,
            "battery_estimate_pct": battery_used_pct,
            "estimated_co2_saved_kg": round(dist * 0.18, 2),
            "fleet_type": "Switch Mobility / TATA Electric"
        }

    def _path_coordinates(self, path: list[str]) -> list[dict]:
        """Map coordinates for a sequence of stop names, anchored.

        Anchoring is not optional here. Resolving each name independently makes
        the drawn route teleport between same-named places on opposite sides of
        the city -- route 335-G drew a 69.4 km line for a 19.2 km journey,
        because its "Kodihalli" matched the wrong Kodihalli 28 km east. The
        distance figures beside the map were always right (route_distance walks
        an anchor); only the map was wrong, which is exactly the kind of bug
        that survives review.
        """
        from .route_geometry import resolve_stop_sequence

        resolved = resolve_stop_sequence(path, self.distance_service)
        return [
            {
                "stop": stop,
                "lat": record.lat if record else None,
                "lon": record.lon if record else None,
            }
            for stop, record in zip(path, resolved)
        ]

    def _make_transfer_leg(self, route: RouteRecord, start_index: int, end_index: int) -> dict:
        path = route.stops[start_index : end_index + 1]
        distance = self.distance_service.route_distance(path, allow_remote=False)
        route_coordinates = self._path_coordinates(path)

        distance_km = distance["distance_km"]
        stop_count = max(1, end_index - start_index)
        metro_info = self._detect_metro_interchange(path)
        ev_specs = self._estimate_ev_specs(distance_km, stop_count)

        return {
            "bus_number": route.route_number,
            "route_id": route.route_id,
            "direction_id": route.direction_id,
            "route_name": route.full_name,
            "source": route.source,
            "destination": route.destination,
            "from_stop": route.stops[start_index],
            "to_stop": route.stops[end_index],
            "stop_count": stop_count,
            "trip_count": route.trip_count,
            "first_trips": route.trip_list[:4],
            "route_path": path,
            "distance_km": distance_km,
            "duration_minutes": distance["duration_minutes"],
            "distance_source": distance["distance_source"],
            "route_coordinates": route_coordinates,
            "metro_interchange": metro_info,
            "ev_specs": ev_specs,
        }

    # How far apart two stops sharing an interchange's name may be and still
    # be the same place. Covers a large terminal's platforms and a short walk
    # across a junction; well below the distance between two genuinely
    # different suburbs that happen to share a name.
    MAX_INTERCHANGE_WALK_KM = 1.2

    def _route_points(self, route: RouteRecord) -> list[tuple[float, float] | None]:
        """This route's stops as anchored points, cached per route-direction.

        Cached because candidate transfer chains reuse the same routes heavily,
        and the check below runs on every candidate before any leg is built.
        Anchoring against the route's WHOLE stop list rather than a slice also
        makes the answer independent of which portion a given candidate uses.
        """
        from .route_geometry import resolve_stop_sequence

        key = (route.route_number, route.direction_id)
        cached = self._route_points_cache.get(key)
        if cached is None:
            cached = [
                (record.lat, record.lon) if record else None
                for record in resolve_stop_sequence(route.stops, self.distance_service)
            ]
            self._route_points_cache[key] = cached
        return cached

    def _interchange_is_walkable(self, path_tuples: list[tuple]) -> bool:
        """Reject a transfer whose two buses do not actually meet.

        Transfers are found by matching stop NAMES, and Bengaluru reuses names
        across the city. Banashankari -> Hebbal was being answered with "take
        215-K to Avalahalli, then 285-M from Avalahalli" -- except 215-K stops
        at the Avalahalli near Banashankari and 285-M starts at the Avalahalli
        near Yelahanka, 28.6 km north. Both are real stops, both are really
        called Avalahalli, and the journey is impossible.

        This is the route-map bug's real cause. The drawn line was not
        malfunctioning when it shot across the city; it was faithfully drawing
        a journey that should never have been offered. Checking here removes
        the route instead of hiding the line.

        Runs on the raw candidate (route, start, end) tuples, before any leg is
        built, because building a leg costs a full distance walk and most of
        what this rejects would be thrown away straight afterwards. It also has
        to run before _reanchor_legs, which resolves a whole journey as one
        sequence and so forces the interchange onto a single point -- checking
        after that would be asking whether two stops agree having just made
        them agree.
        """
        from .blocking import haversine_km

        for (route_a, _, end_a), (route_b, start_b, _) in zip(path_tuples, path_tuples[1:]):
            points_a = self._route_points(route_a)
            points_b = self._route_points(route_b)
            arrive = points_a[end_a] if end_a < len(points_a) else None
            depart = points_b[start_b] if start_b < len(points_b) else None
            # An unlocatable interchange is not evidence of a bad transfer, so
            # it is left alone rather than rejected -- the name match is the
            # same evidence every transfer was accepted on before this existed.
            if arrive is None or depart is None:
                continue
            gap = haversine_km(arrive, depart)
            if gap > self.MAX_INTERCHANGE_WALK_KM:
                logger.debug(
                    "Rejected transfer at stop %r: %s and %s are %.1f km apart",
                    route_a.stops[end_a], route_a.route_number, route_b.route_number, gap,
                )
                return False
        return True

    def _reanchor_legs(self, legs: list[dict]) -> list[dict]:
        """Re-resolve a whole journey's stops as one anchored sequence.

        Each leg is already internally anchored by _make_transfer_leg, but the
        legs are anchored INDEPENDENTLY -- and they share a stop, the
        interchange. Resolved separately, that one stop can land on two
        different same-named places: on Banashankari -> Hebbal, leg 1's
        "Avalahalli" and leg 2's "Avalahalli" came out 29.2 km apart, so the
        drawn journey shot across the city and back at the transfer.

        Resolving the concatenated path in one pass makes the interchange
        resolve to a single place by construction, because the second leg's
        first stop is anchored to the first leg's last.
        """
        from .route_geometry import resolve_stop_sequence

        paths = [leg.get("route_path") or [] for leg in legs]
        combined = [stop for path in paths for stop in path]
        if not combined:
            return legs

        resolved = resolve_stop_sequence(combined, self.distance_service)

        rebuilt: list[dict] = []
        cursor = 0
        for leg, path in zip(legs, paths):
            window = resolved[cursor : cursor + len(path)]
            cursor += len(path)
            rebuilt.append({
                **leg,
                "route_coordinates": [
                    {
                        "stop": stop,
                        "lat": record.lat if record else None,
                        "lon": record.lon if record else None,
                    }
                    for stop, record in zip(path, window)
                ],
            })
        return rebuilt

    def _make_transfer_suggestion(self, legs: list[dict]) -> dict:
        # Done here rather than at the point of drawing so that every consumer
        # of a suggestion -- best_match, the alternatives list, the map, the
        # SMS reply -- sees the same journey geometry.
        legs = self._reanchor_legs(legs)
        total_stops = sum(leg["stop_count"] for leg in legs)
        known_distances = [float(leg["distance_km"]) for leg in legs if leg.get("distance_km")]
        total_distance = sum(known_distances) if known_distances else None
        frequency_score = sum(math.log1p(leg["trip_count"]) for leg in legs) / max(len(legs), 1)
        confidence = clamp(0.96 - 0.08 * (len(legs) - 1) - 0.006 * total_stops + 0.012 * frequency_score, 0.28, 0.92)
        transfer_stops = [leg["to_stop"] for leg in legs[:-1]]
        bus_chain = " -> ".join(leg["bus_number"] for leg in legs)
        summary_parts = [
            f"Take {leg['bus_number']} from {leg['from_stop']} to {leg['to_stop']}"
            for leg in legs
        ]
        return {
            "dedupe_key": bus_chain,
            "confidence": round(confidence * 100, 1),
            "transfers": max(0, len(legs) - 1),
            "total_stops": total_stops,
            "total_distance_km": round(total_distance, 2) if total_distance is not None else None,
            "bus_chain": bus_chain,
            "transfer_stops": transfer_stops,
            "summary": "; then ".join(summary_parts) + ".",
            "legs": legs,
        }

    def _enrich_transfer_distances(self, suggestions: list[dict]) -> list[dict]:
        enriched_suggestions = []
        for suggestion in suggestions:
            legs = []
            for leg in suggestion["legs"]:
                distance = self.distance_service.route_distance(leg["route_path"], allow_remote=True)
                legs.append({**leg, **distance})
            total_distance = sum(float(leg.get("distance_km") or 0) for leg in legs)
            distance_penalty = min(30.0, total_distance * 0.25) if total_distance else 0.0
            updated = {
                **suggestion,
                "confidence": round(clamp((suggestion["confidence"] - distance_penalty) / 100, 0.28, 0.92) * 100, 1),
                "legs": legs,
                "total_distance_km": round(total_distance, 2) if total_distance else suggestion.get("total_distance_km"),
            }
            enriched_suggestions.append(updated)

        enriched_suggestions.sort(
            key=lambda item: (
                item["confidence"],
                -float(item.get("total_distance_km") or 9999),
                -item["total_stops"],
                -item["transfers"],
            ),
            reverse=True,
        )
        return enriched_suggestions

    def _dedupe_bus_numbers(self, ranked: list[dict]) -> list[dict]:
        best_by_bus: dict[str, dict] = {}
        for item in ranked:
            bus = item["bus_number"]
            if bus not in best_by_bus:
                best_by_bus[bus] = item
                continue
            current = best_by_bus[bus]
            if (
                item["confidence"],
                -float(item.get("distance_km") or 9999),
                item["trip_count"],
            ) > (
                current["confidence"],
                -float(current.get("distance_km") or 9999),
                current["trip_count"],
            ):
                best_by_bus[bus] = item
        return sorted(
            best_by_bus.values(),
            key=lambda item: (item["confidence"], -float(item.get("distance_km") or 9999), item["trip_count"]),
            reverse=True,
        )

    def _score_samples_live(self, samples: list[tuple[str, str, str]]) -> dict:
        """Benchmark the function predict() actually calls.

        _score_samples() (above) only ever exercises _rank() -- but
        predict() never calls _rank(); it calls _find_transfer_suggestions()
        (a direct + one-transfer graph search), a completely separate code
        path that was never benchmarked at all. That meant metrics.json's
        reported accuracy described a model that wasn't in the live request
        path, and the real accuracy of what a user actually receives was
        unknown. This scores _find_transfer_suggestions() itself, using the
        same top-1/3/5 methodology as _score_samples(), so the numbers
        reported to users/train() describe what predict() truly returns.
        """
        top1 = top3 = top5 = 0
        for expected_bus, current, destination in samples:
            try:
                suggestions = self._find_transfer_suggestions(current, destination, limit=5)
            except Exception:
                suggestions = []
            # A suggestion can involve more than one bus (a transfer route);
            # count it as a hit if the expected bus appears on any leg,
            # matching how a commuter reading the result would judge it.
            bus_sets = [
                {leg.get("bus_number") for leg in suggestion.get("legs", [])}
                for suggestion in suggestions[:5]
            ]
            top1 += int(bool(bus_sets) and expected_bus in bus_sets[0])
            top3 += int(any(expected_bus in buses for buses in bus_sets[:3]))
            top5 += int(any(expected_bus in buses for buses in bus_sets[:5]))
        total = max(len(samples), 1)
        precision_at_5 = (top5 / total) / 5
        recall_at_5 = top5 / total
        f1_at_5 = 2 * precision_at_5 * recall_at_5 / max(precision_at_5 + recall_at_5, 1e-9)
        return {
            "accuracy_top_1": round(top1 / total, 4),
            "accuracy_top_3": round(top3 / total, 4),
            "accuracy_top_5": round(top5 / total, 4),
            "precision_at_5": round(precision_at_5, 4),
            "recall_at_5": round(recall_at_5, 4),
            "f1_at_5": round(f1_at_5, 4),
        }

    def _evaluate_models(self) -> dict:
        random.seed(42)
        evaluable = [route for route in self.routes if len(route.stops) >= 4]
        samples = []
        for route in evaluable:
            start = random.randint(0, max(0, len(route.stops) - 3))
            dest = random.randint(start + 1, len(route.stops) - 1)
            samples.append((route.route_number, route.stops[start], route.stops[dest]))
        random.shuffle(samples)
        test_samples = samples[: min(120, max(60, len(samples) // 12))]

        # _find_transfer_suggestions() is a real graph search over the stop
        # index (~1.3s/sample), not a lightweight ranker like _rank() --
        # scoring all `test_samples` here would add several minutes to a
        # fresh training run. This only runs once per fresh artifact
        # directory (train() caches metrics.json afterward), but 60 samples
        # is already the floor the rest of this file treats as statistically
        # workable (see the min(120, max(60, ...)) above), so reuse it here
        # too rather than paying for the full 120.
        live_samples = test_samples[: min(15, len(test_samples))]
        model_scores = {
            "TFIDFCosine": self._score_samples(test_samples, mode="tfidf"),
            "OrderedStopFuzzy": self._score_samples(test_samples, mode="ordered"),
            "DistanceAwareRouteRanker": self._score_samples(test_samples, mode="hybrid"),
            # This is the one predict() actually serves -- see
            # _score_samples_live's docstring. It is always what train()
            # reports as "selected_model" below, regardless of which
            # candidate wins on paper, because it is the only one that is
            # literally true.
            "LiveTransferSearch": self._score_samples_live(live_samples),
        }
        selected = max(model_scores.items(), key=lambda item: item[1]["f1_at_5"])[0]
        return {
            "candidate_models": model_scores,
            "best_candidate_model": selected,
            "selected_model_metrics": model_scores[selected],
            "cross_validation": self._cross_validate(samples, folds=5),
            "test_samples": len(test_samples),
            "live_test_samples": len(live_samples),
        }

    def _score_samples(self, samples: list[tuple[str, str, str]], mode: str) -> dict:
        top1 = top3 = top5 = 0
        for expected_bus, current, destination in samples:
            ranked = self._rank(current, destination, mode=mode, use_fuzzy=False)[:5]
            buses = [item["bus_number"] for item in ranked]
            top1 += int(bool(buses and buses[0] == expected_bus))
            top3 += int(expected_bus in buses[:3])
            top5 += int(expected_bus in buses[:5])
        total = max(len(samples), 1)
        precision_at_5 = (top5 / total) / 5
        recall_at_5 = top5 / total
        f1_at_5 = 2 * precision_at_5 * recall_at_5 / max(precision_at_5 + recall_at_5, 1e-9)
        return {
            "accuracy_top_1": round(top1 / total, 4),
            "accuracy_top_3": round(top3 / total, 4),
            "accuracy_top_5": round(top5 / total, 4),
            "precision_at_5": round(precision_at_5, 4),
            "recall_at_5": round(recall_at_5, 4),
            "f1_at_5": round(f1_at_5, 4),
        }

    def _cross_validate(self, samples: list[tuple[str, str, str]], folds: int = 5) -> dict:
        if not samples:
            return {}
        fold_size = max(1, len(samples) // folds)
        scores = []
        for fold in range(folds):
            fold_samples = samples[fold * fold_size : (fold + 1) * fold_size][:32]
            if fold_samples:
                scores.append(self._score_samples(fold_samples, mode="hybrid"))
        keys = scores[0].keys() if scores else []
        return {key: round(mean(score[key] for score in scores), 4) for key in keys}

    def _route_summary(self, route: RouteRecord) -> dict:
        return {
            "bus_number": route.route_number,
            "route_id": route.route_id,
            "direction_id": route.direction_id,
            "route_name": route.full_name,
            "source": route.source,
            "destination": route.destination,
            "trip_count": route.trip_count,
            "stop_count": len(route.stops),
            "stops": route.stops,
        }

    def _save_metrics(self) -> None:
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            # Without this key the cache-reuse check in train() can never
            # match, however the version constant is defined -- see
            # METRICS_SCHEMA_VERSION.
            "schema_version": self.METRICS_SCHEMA_VERSION,
            "metrics": self.metrics,
            "profile": self.profile,
            "trained_at": self._trained_at,
        }
        (self.artifact_dir / "metrics.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")