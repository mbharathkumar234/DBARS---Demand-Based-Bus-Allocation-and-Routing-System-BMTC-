from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional, Type
from pydantic import BaseModel, Field

from app.ai.tools.base import BaseDBARSTool
from app.ai.tools.routing_tools import get_shared_predictor

logger = logging.getLogger("bmtc-ai-tools-ops")


# ── Fleet Planning Tool ──────────────────────────────────────────────

class FleetPlanInput(BaseModel):
    depot_name: Optional[str] = Field(default=None, description="Optional depot name to filter blocking plan")


class GetFleetPlanTool(BaseDBARSTool):
    """Retrieves depot blocking plan and minimum fleet requirements."""

    name: str = "get_fleet_plan"
    description: str = "Returns minimum fleet requirements, scheduled buses, interlined buses, and depot statistics."
    args_schema: Type[BaseModel] = FleetPlanInput

    def _run_tool(self, depot_name: Optional[str] = None) -> Dict[str, Any]:
        from app.services.blocking_service import blocking_plan_service

        plan = getattr(blocking_plan_service, "_plan", None)
        if plan is None:
            try:
                from app.services.blocking_service import compute_plan
                plan = compute_plan()
                blocking_plan_service._plan = plan
            except Exception as e:
                logger.warning("Could not compute blocking plan synchronously: %s", e)

        if not plan:
            return {
                "status": "calculating",
                "message": "Blocking plan is currently calculating in the background.",
            }

        network = plan.get("network", {})
        depots = plan.get("depots", [])

        if depot_name:
            clean = depot_name.lower().strip()
            match = next((d for d in depots if clean in d.get("key", "").lower() or clean in d.get("label", "").lower()), None)
            if match:
                return {
                    "depot": match.get("label"),
                    "zone": match.get("zone"),
                    "buses_scheduled": match.get("buses_scheduled"),
                    "buses_released": match.get("buses_released"),
                    "routes_served": match.get("routes", []),
                }

        return {
            "total_buses_scheduled": network.get("buses_scheduled"),
            "total_buses_interlined": network.get("buses_interlined"),
            "total_depots": len(depots),
            "deadhead_kilometers": network.get("dead_km"),
        }


# ── Crew Planning Tool ───────────────────────────────────────────────

class CrewPlanInput(BaseModel):
    depot_name: Optional[str] = Field(default=None, description="Optional depot filter for crew duties")


class GetCrewPlanTool(BaseDBARSTool):
    """Retrieves crew scheduling and daily duty requirements."""

    name: str = "get_crew_plan"
    description: str = "Returns total daily crew duties, crew-to-bus ratio, and shift parameters."
    args_schema: Type[BaseModel] = CrewPlanInput

    def _run_tool(self, depot_name: Optional[str] = None) -> Dict[str, Any]:
        from app.services.crew_service import crew_plan_service

        plan = getattr(crew_plan_service, "_plan", None)
        if plan is None:
            # Normally warmed at startup (see lifespan in app/main.py), so this
            # is the cold path only.
            try:
                from app.services.crew_service import compute_crew_plan, CrewParameters
                from app.services.blocking_service import blocking_plan_service, _build_context

                # Reuse the blocking context if it is already built. Calling
                # _build_context() unconditionally rebuilt it every time --
                # ~5.6s that the cache next door had already paid for.
                context = getattr(blocking_plan_service, "_context", None)
                if context is None:
                    context = _build_context()
                    blocking_plan_service._context = context
                plan = compute_crew_plan(context, CrewParameters())
                crew_plan_service._plan = plan
            except Exception as e:
                logger.warning("Could not compute crew plan synchronously: %s", e)

        if not plan:
            return {
                "status": "ready",
                "assumed_crew_to_bus_ratio": 2.4,
                "notes": "Crew duty generator schedules 2 shifts per vehicle block adhering to statutory spreadover limits.",
            }

        network = plan.get("network", {})
        # Keys must match what app/ml/crew.py summarize() actually returns.
        # "duties_required", "two_shift_duties" and "single_shift_duties" do
        # not exist there, so the assistant reported the total duties as
        # "None" while the figure -- 15,636 -- sat in "duties".
        return {
            "total_duties_required": network.get("duties"),
            "crew_to_bus_ratio": network.get("crew_to_bus_ratio"),
            "blocks_staffed": network.get("blocks"),
            "split_duties": network.get("split_duties"),
            "split_duty_pct": network.get("split_duty_pct"),
            "paid_hours": network.get("paid_hours"),
            "median_spreadover_hours": network.get("median_spreadover_hours"),
            "unstaffable_blocks": network.get("unstaffable_blocks"),
        }


# ── Crowding Information Tool ────────────────────────────────────────

class CrowdingInput(BaseModel):
    route_number: str = Field(..., description="Bus route number, e.g. '500-D' or '335-A'")


class GetCrowdingInfoTool(BaseDBARSTool):
    """Retrieves crowd reports and crowding level for a route."""

    name: str = "get_crowding_information"
    description: str = "Returns recent commuter crowd reports and crowding level for a route."
    args_schema: Type[BaseModel] = CrowdingInput

    def _run_tool(self, route_number: str) -> Dict[str, Any]:
        from app.services.crowding_service import get_route_crowding

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Run with run_until_complete in new loop or report status
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    report = executor.submit(asyncio.run, get_route_crowding(route_number)).result()
            else:
                report = loop.run_until_complete(get_route_crowding(route_number))
            return report
        except Exception as e:
            return {
                "route_number": route_number,
                "status": "insufficient_data",
                "note": f"Live crowd reporting requires MongoDB connection ({str(e)}).",
            }


# ── Service Alerts Tool ──────────────────────────────────────────────

class AlertsInput(BaseModel):
    route_number: Optional[str] = Field(default=None, description="Optional route number filter")
    stop_name: Optional[str] = Field(default=None, description="Optional stop name filter")


class GetServiceAlertsTool(BaseDBARSTool):
    """Retrieves active BMTC service alerts and disruptions."""

    name: str = "get_service_alerts"
    description: str = "Returns active service disruption alerts, road closures, and passenger notices."
    args_schema: Type[BaseModel] = AlertsInput

    def _run_tool(self, route_number: Optional[str] = None, stop_name: Optional[str] = None) -> Dict[str, Any]:
        try:
            from app.services.alerts_service import get_active_alerts
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor:
                alerts = executor.submit(asyncio.run, get_active_alerts(route_number, stop_name)).result()
            return {
                "active_alerts_count": len(alerts),
                "alerts": alerts,
            }
        except Exception as e:
            return {
                "active_alerts_count": 0,
                "alerts": [],
                "note": "No active service disruptions reported.",
            }


# ── Metro Information Tool ───────────────────────────────────────────

class MetroInput(BaseModel):
    stop_name: str = Field(..., description="Bus stop name to find nearby Metro connectivity")


class GetMetroInfoTool(BaseDBARSTool):
    """Retrieves nearby Namma Metro station connectivity for a bus stop."""

    name: str = "get_metro_information"
    description: str = "Returns nearby Bengaluru Namma Metro stations, line colors, and interchange options."
    args_schema: Type[BaseModel] = MetroInput

    def _run_tool(self, stop_name: str) -> Dict[str, Any]:
        from app.services.metro_service import metro_service
        from app.ai.tools.routing_tools import get_shared_predictor

        predictor = get_shared_predictor()
        nearby = metro_service.find_nearest_stations(
            stop_name=stop_name,
            limit=3,
            distance_service=getattr(predictor, "distance_service", None),
        )
        if not nearby:
            return {
                "stop_name": stop_name,
                "has_metro_connection": False,
                "message": f"No Namma Metro station found near '{stop_name}'.",
            }

        return {
            "stop_name": stop_name,
            "has_metro_connection": True,
            "nearby_stations": [
                {
                    "station_name": s.get("station_name"),
                    "line": s.get("line") or (s.get("lines")[0] if s.get("lines") else "Purple Line"),
                    "lines": s.get("lines", [s.get("line")]),
                    "distance_km": round(s["distance_km"], 2) if s.get("distance_km") is not None else None,
                    "walking_minutes": s.get("walking_minutes"),
                    "is_interchange": s.get("is_interchange", False),
                }
                for s in nearby[:3]
            ],
        }


# ── Vehicle ETA & Tracking Tool ──────────────────────────────────────

class BusETAInput(BaseModel):
    route_number: str = Field(..., description="Bus route number to track, e.g. '335-A'")


class GetBusETATool(BaseDBARSTool):
    """Retrieves current simulated or live vehicle positions for a route."""

    name: str = "get_bus_eta"
    description: str = "Returns active vehicle positions and schedule status for a given route."
    args_schema: Type[BaseModel] = BusETAInput

    def _run_tool(self, route_number: str) -> Dict[str, Any]:
        from app.services.vehicle_service import describe_vehicles
        predictor = get_shared_predictor()

        payload = describe_vehicles(route_number.strip(), predictor=predictor)
        vehicles = payload.get("vehicles", [])

        return {
            "route_number": route_number,
            "is_live": payload.get("is_live", False),
            "feed_type": payload.get("feed", "simulated"),
            "active_vehicles_count": len(vehicles),
            "vehicles": [
                {
                    "vehicle_id": v.get("vehicle_id"),
                    "next_stop": v.get("next_stop"),
                    "speed_kmh": v.get("speed_kmh"),
                    "adherence_minutes": v.get("adherence_min"),
                }
                for v in vehicles[:4]
            ],
        }
