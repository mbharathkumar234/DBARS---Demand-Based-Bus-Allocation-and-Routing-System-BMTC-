from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Type
from pydantic import BaseModel, Field

from app.ai.tools.base import BaseDBARSTool
from app.core.config import settings
from app.ml.predictor import BMTCBusPredictor

logger = logging.getLogger("bmtc-ai-tools-routing")

# Shared in-memory predictor reference
_shared_predictor: Optional[BMTCBusPredictor] = None


def set_shared_predictor(predictor: BMTCBusPredictor) -> None:
    global _shared_predictor
    _shared_predictor = predictor


def get_shared_predictor() -> BMTCBusPredictor:
    global _shared_predictor
    if _shared_predictor is None:
        dataset_path = Path(settings.dataset_path)
        if not dataset_path.exists():
            from app.ai.config import BACKEND_DIR, WORKSPACE_DIR
            candidates = [
                WORKSPACE_DIR / "dataset" / "routes_cleaned.csv",
                BACKEND_DIR / dataset_path,
                WORKSPACE_DIR / dataset_path,
                BACKEND_DIR.parent / "dataset" / "routes_cleaned.csv",
            ]
            for cand in candidates:
                if cand.exists():
                    dataset_path = cand
                    break

        artifact_dir = Path(settings.artifact_dir)
        if not artifact_dir.exists() and not artifact_dir.is_absolute():
            from app.ai.config import BACKEND_DIR
            if (BACKEND_DIR / artifact_dir).exists():
                artifact_dir = BACKEND_DIR / artifact_dir

        logger.info("Initializing fallback shared predictor from %s", dataset_path)
        _shared_predictor = BMTCBusPredictor(dataset_path, artifact_dir)
        if not _shared_predictor.ready:
            _shared_predictor.train()
    return _shared_predictor


class SearchBusRouteInput(BaseModel):
    current_stop: str = Field(..., description="Origin stop name, e.g. 'Silk Board' or 'Majestic'")
    destination: str = Field(..., description="Destination stop name, e.g. 'Marathahalli' or 'Whitefield'")
    limit: int = Field(default=3, description="Maximum number of candidate predictions to return")
    max_transfers: Optional[int] = Field(default=None, description="Optional maximum allowed transfers (0 for direct only, 1 for up to one transfer)")


class SearchBusRouteTool(BaseDBARSTool):
    """Searches for deterministic BMTC bus routes between two bus stops using DBARS routing engine."""

    name: str = "search_bus_route"
    description: str = (
        "Finds real BMTC bus routes between an origin stop and destination stop. "
        "Calls the existing deterministic BMTCBusPredictor engine to return genuine route options."
    )
    args_schema: Type[BaseModel] = SearchBusRouteInput

    def _run_tool(
        self,
        current_stop: str,
        destination: str,
        limit: int = 3,
        max_transfers: Optional[int] = None,
    ) -> Dict[str, Any]:
        predictor = get_shared_predictor()
        try:
            raw_result = predictor.predict(current_stop, destination, limit=limit)
        except ValueError as e:
            return {
                "origin": current_stop,
                "destination": destination,
                "found": False,
                "error": str(e),
                "message": str(e),
                "best_match": {},
                "top_candidates": [],
                "alternatives": [],
            }
        except Exception as e:
            logger.error("Unexpected error in search_bus_route: %s", e)
            return {
                "origin": current_stop,
                "destination": destination,
                "found": False,
                "error": f"Prediction failed: {e}",
                "message": f"Unable to route between '{current_stop}' and '{destination}'.",
                "best_match": {},
                "top_candidates": [],
                "alternatives": [],
            }

        best = raw_result.get("best_match") or {}
        raw_alternatives = raw_result.get("alternatives", []) or raw_result.get("top_predictions", [])

        # Filter by max_transfers if requested
        if max_transfers is not None:
            raw_alternatives = [
                alt for alt in raw_alternatives
                if alt.get("transfers", 0) <= max_transfers
            ]

        is_direct = (best.get("transfers") == 0) if best.get("transfers") is not None else best.get("is_direct", True)
        
        parsed_alternatives = []
        for alt in raw_alternatives[:limit]:
            parsed_alternatives.append({
                "bus_number": alt.get("bus_number") or (alt.get("legs", [{}])[0].get("bus_number") if alt.get("legs") else None),
                "bus_chain": alt.get("bus_chain") or alt.get("bus_number"),
                "transfers": alt.get("transfers", 0),
                "transfer_stops": alt.get("transfer_stops", []),
                "summary": alt.get("summary") or alt.get("route_name"),
                "total_distance_km": alt.get("total_distance_km") or alt.get("distance_km"),
                "total_duration_minutes": alt.get("total_duration_minutes") or alt.get("duration_minutes"),
                "is_direct": alt.get("transfers", 0) == 0,
                "legs": [
                    {
                        "bus_number": leg.get("bus_number"),
                        "route_name": leg.get("route_name"),
                        "from_stop": leg.get("from_stop"),
                        "to_stop": leg.get("to_stop"),
                        "stop_count": leg.get("stop_count"),
                        "distance_km": leg.get("distance_km"),
                    }
                    for leg in alt.get("legs", [])
                ],
            })

        # The same two readings the commuter search page shows, so the copilot
        # and the main engine cannot disagree about the same pair of stops.
        def _view(items):
            return [
                {
                    "bus_chain": v.get("bus_chain"),
                    "transfers": v.get("transfers", 0),
                    "transfer_stops": v.get("transfer_stops", []),
                    "total_stops": v.get("total_stops"),
                    "total_distance_km": v.get("total_distance_km"),
                    "duration_minutes": v.get("duration_minutes"),
                    "summary": v.get("summary"),
                }
                for v in (items or [])[:limit]
            ]

        raw_views = raw_result.get("views") or {}

        return {
            "origin": current_stop,
            "destination": destination,
            "found": bool(best),
            "views": {
                "fewest_transfers": _view(raw_views.get("fewest_transfers")),
                "least_distance": _view(raw_views.get("least_distance")),
            },
            "matched_origin": best.get("matched_current_stop"),
            "matched_destination": best.get("matched_destination"),
            "best_match": {
                "bus_number": best.get("bus_number"),
                "bus_chain": best.get("bus_chain") or best.get("bus_number"),
                "route_name": best.get("route_name"),
                "is_direct": is_direct,
                "transfers": best.get("transfers", 0) if best.get("transfers") is not None else 0,
                "transfer_stops": best.get("transfer_stops", []),
                "distance_km": best.get("distance_km"),
                "duration_minutes": best.get("duration_minutes"),
                "fare_inr": best.get("fare_inr"),
                "passes_in_order": best.get("passes_in_requested_order", True),
                "summary": best.get("summary"),
                "message": best.get("message") or raw_result.get("message"),
                "trip_count": best.get("trip_count"),
            },
            "total_candidates_found": len(raw_alternatives),
            "top_candidates": [
                {
                    "bus_number": p.get("bus_number"),
                    "bus_chain": p.get("bus_chain") or p.get("bus_number"),
                    "route_name": p.get("route_name") or p.get("summary"),
                    "score": p.get("score"),
                    "is_direct": p.get("is_direct", True),
                    "transfers": p.get("transfers", 0),
                }
                for p in parsed_alternatives
            ],
            "alternatives": parsed_alternatives,
        }


class GetRouteDetailsInput(BaseModel):
    bus_number: str = Field(..., description="Bus number or route identifier, e.g. 'KIA-8E' or '335-A'")


class GetRouteDetailsTool(BaseDBARSTool):
    """Retrieves authoritative timetable and stop sequence for a specific BMTC bus number."""

    name: str = "get_route_details"
    description: str = "Retrieves stop list, terminal points, and trip frequencies for a known BMTC bus number."
    args_schema: Type[BaseModel] = GetRouteDetailsInput

    def _run_tool(self, bus_number: str = "", route_number: Optional[str] = None) -> Dict[str, Any]:
        predictor = get_shared_predictor()
        clean_bus = (bus_number or route_number or "").strip().upper()

        matching_routes = [
            r for r in getattr(predictor, "routes", [])
            if r.route_number.strip().upper() == clean_bus
        ]

        if not matching_routes:
            return {
                "bus_number": bus_number,
                "found": False,
                "message": f"No BMTC route found matching '{bus_number}' in catalogue.",
            }

        primary = matching_routes[0]
        return {
            "bus_number": primary.route_number,
            "found": True,
            "full_name": primary.full_name,
            "trip_count": primary.trip_count,
            "stop_count": len(primary.stops),
            "origin_stop": primary.stops[0] if primary.stops else None,
            "destination_stop": primary.stops[-1] if primary.stops else None,
            "stop_sequence": primary.stops,
            "direction_id": getattr(primary, "direction_id", 0),
        }
