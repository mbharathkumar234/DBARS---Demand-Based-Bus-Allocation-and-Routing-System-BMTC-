"""Serves the vehicle-blocking plan to the depot and admin dashboards.

Deliberately independent of MongoDB. Everything here is derived from the
timetable CSV and the depot workbook, both of which ship with the repo, so the
depot dashboard's blocking panel keeps working when the database is
unreachable -- unlike the vote-driven panels beside it, which honestly report
themselves unavailable. A demo that dies on a connectivity problem is a demo
you do not recover from.

The full computation takes ~15s, far too long for a request, so it is computed
once on first use and cached. It is pure a function of files on disk, so there
is nothing to invalidate.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from app.core.config import settings
from app.ml.blocking import (
    BlockingEngine,
    BlockingParameters,
    RouteBlocking,
    ScenarioChange,
    apply_scenario,
    format_clock,
    load_depots,
)
from app.ml.data_loader import load_routes
from app.ml.distance import GoogleMapsDistanceService

logger = logging.getLogger(__name__)

UNASSIGNED = "unassigned"


def _build_engine(parameters: BlockingParameters) -> BlockingEngine:
    distance_service = GoogleMapsDistanceService(
        settings.artifact_dir / "google_distance_cache.json",
        api_key="",              # offline: stop coordinates only, no remote calls
        stop_coordinates_path=settings.stop_coordinates_path,
        max_remote_lookups=0,
    )
    return BlockingEngine(
        load_routes(settings.dataset_path),
        load_depots(settings.depot_dataset_path),
        distance_service,
        parameters,
    )


def _route_payload(row: RouteBlocking) -> dict[str, Any]:
    saved = max(row.buses_required - row.concurrency_lower_bound, 0)
    return {
        "route": row.route_number,
        "trips": row.trip_count,
        "buses_scheduled": row.buses_required,
        "buses_floor": row.concurrency_lower_bound,
        "buses_released": saved,
        "revenue_km": round(row.revenue_km, 1),
        # Dead km is only meaningful where the operating depot is stated in the
        # data. Where it was inferred by proximity, return null rather than a
        # number that looks authoritative and is not.
        "dead_km": round(row.dead_km, 1) if row.depot_source == "route_code" else None,
        "depot_source": row.depot_source,
        "provably_minimal": row.is_provably_minimal,
    }


def compute_plan(parameters: BlockingParameters | None = None) -> dict[str, Any]:
    """The whole plan: network totals, per-depot rollup, per-route proposals."""
    parameters = parameters or BlockingParameters()
    started = time.perf_counter()
    engine = _build_engine(parameters)

    per_route = engine.block_by_route()
    revenue_routes = engine.revenue_service()
    revenue_names = {route.route_number for route in revenue_routes}
    rows = [row for row in per_route if row.route_number in revenue_names]
    by_name = {row.route_number: row for row in rows}

    network_blocks = engine.block_interlined(revenue_routes)
    network_bound = engine.concurrency_lower_bound(engine.all_trips(revenue_routes))
    baseline_buses = sum(row.buses_required for row in rows)
    interlined_buses = len(network_blocks)
    revenue_km = sum(row.revenue_km for row in rows)
    trips = sum(row.trip_count for row in rows)

    # Group the actual RouteRecords by depot so each depot can be interlined on
    # its own. Buses interline WITHIN a depot in practice -- they go home at
    # night -- so a per-depot figure is the operationally honest one, and the
    # network figure above is the theoretical ceiling.
    routes_by_depot: dict[str, list] = {}
    labels: dict[str, RouteBlocking] = {}
    for route in revenue_routes:
        row = by_name.get(route.route_number)
        if not row:
            continue
        key = row.depot.label if row.depot else UNASSIGNED
        routes_by_depot.setdefault(key, []).append(route)
        labels.setdefault(key, row)

    depots: list[dict[str, Any]] = []
    for key, depot_routes in routes_by_depot.items():
        names = {r.route_number for r in depot_routes}
        depot_rows = [by_name[n] for n in names if n in by_name]
        depot_blocks = engine.block_interlined(depot_routes)
        scheduled = sum(row.buses_required for row in depot_rows)
        stated = [row for row in depot_rows if row.depot_source == "route_code"]
        sample = labels.get(key)
        depots.append({
            "key": key,
            "label": key,
            "zone": sample.depot.zone if sample and sample.depot else "",
            "number": sample.depot.number if sample and sample.depot else "",
            "routes": len(depot_rows),
            "trips": sum(row.trip_count for row in depot_rows),
            "revenue_km": round(sum(row.revenue_km for row in depot_rows), 1),
            "buses_scheduled": scheduled,
            "buses_interlined": len(depot_blocks),
            "buses_released": max(scheduled - len(depot_blocks), 0),
            "buses_floor": engine.concurrency_lower_bound(engine.all_trips(depot_routes)),
            # Only routes whose depot the data states outright contribute here.
            "dead_km_stated": round(sum(row.dead_km for row in stated), 1),
            "routes_depot_stated": len(stated),
            "routes_depot_inferred": len(depot_rows) - len(stated),
            "proposals": sorted(
                (_route_payload(row) for row in depot_rows if row.buses_required > row.concurrency_lower_bound),
                key=lambda item: -item["buses_released"],
            )[:40],
        })

    depots.sort(key=lambda item: -item["buses_released"])
    elapsed = time.perf_counter() - started
    logger.info("Blocking plan computed in %.1fs (%s depots)", elapsed, len(depots))

    return {
        "status": "ok",
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "computed_in_seconds": round(elapsed, 1),
        "source": "BMTC published timetable (routes_cleaned.csv) + depot workbook",
        "network": {
            "passenger_routes": len(rows),
            "trips": trips,
            "revenue_km": round(revenue_km, 1),
            "buses_scheduled": baseline_buses,
            "buses_interlined": interlined_buses,
            "buses_released": max(baseline_buses - interlined_buses, 0),
            "buses_floor": network_bound,
            "km_per_bus": round(revenue_km / interlined_buses, 1) if interlined_buses else 0,
            "trips_per_bus": round(trips / interlined_buses, 1) if interlined_buses else 0,
        },
        "depots": depots,
        "assumptions": {
            "average_speed_kmph": parameters.average_speed_kmph,
            "dwell_minutes_per_stop": parameters.dwell_minutes_per_stop,
            "layover_minutes": parameters.layover_minutes,
            "max_terminal_idle_minutes": parameters.max_terminal_idle_minutes,
            "max_deadhead_km": parameters.max_deadhead_km,
            "circuity_factor": parameters.circuity_factor,
        },
        "caveats": [
            "Running speed, dwell, layover and circuity are assumptions, not BMTC "
            "observations. Replace them with scheduled running times before quoting "
            "any fuel or cost figure.",
            "Dead kilometres are reported only for routes whose operating depot is "
            "stated in the route name. A citywide dead-km total needs BMTC's "
            "route-to-depot mapping.",
        ],
    }


def _depot_metrics(
    engine: BlockingEngine, routes: list, parameters: BlockingParameters, depot
) -> dict[str, Any]:
    """Block one depot's routes and report what an operations manager asks for."""
    blocks = engine.block_interlined(routes)
    engine.apply_dead_km(blocks, depot)
    trips = sum(len(block.trips) for block in blocks)
    spans = sorted((b.end_minute - b.start_minute) for b in blocks if b.trips)
    return {
        "trips": trips,
        "buses": len(blocks),
        "buses_floor": engine.concurrency_lower_bound(engine.all_trips(routes)),
        "revenue_km": round(sum(block.revenue_km for block in blocks), 1),
        "dead_km": round(sum(block.dead_km for block in blocks), 1),
        "idle_bus_hours": round(sum(block.idle_minutes for block in blocks) / 60, 1),
        "trips_per_bus": round(trips / len(blocks), 1) if blocks else 0.0,
        "over_duty_blocks": engine.blocks_exceeding_duty(blocks, parameters.duty_limit_minutes),
        # Reported alongside the count because on this dataset the count is
        # saturated -- see the crew note in run_scenario below.
        "total_blocks": len(blocks),
        "median_block_span_hours": round(spans[len(spans) // 2] / 60, 1) if spans else 0.0,
    }


def run_scenario(
    engine: BlockingEngine,
    depot_routes: list,
    depot,
    change: ScenarioChange,
    parameters: BlockingParameters,
    dead_km_is_stated: bool = False,
) -> dict[str, Any]:
    """Re-block one depot with and without a timetable change.

    Scoped to the affected depot rather than the whole network on purpose: a
    frequency change on one route cannot move a bus that belongs to a different
    depot, and re-blocking all 44 depots would take ~17s per question, which is
    not a console anyone will use interactively.
    """
    before = _depot_metrics(engine, depot_routes, parameters, depot)
    changed_routes, summary = apply_scenario(depot_routes, change)
    if not summary["route_directions_changed"]:
        raise LookupError(change.route_number)
    after = _depot_metrics(engine, changed_routes, parameters, depot)

    # Dead km is measured from the depot's coordinates, so it is only as real
    # as the route-to-depot assignment underneath it. Where that assignment was
    # inferred by proximity, blank it here exactly as the blocking panel does --
    # a console that quotes 17,000 dead km/day for a depot whose routes were
    # guessed would contradict the panel directly above it, and the honest-null
    # rule is worth more than the extra row.
    if not dead_km_is_stated:
        for metrics in (before, after):
            metrics["dead_km"] = None

    delta = {
        key: round(after[key] - before[key], 1)
        for key in before
        if key != "trips_per_bus" and before[key] is not None and after[key] is not None
    }
    delta.setdefault("dead_km", None)

    notes: list[str] = []
    if delta["buses"] > 0:
        notes.append(
            f"Needs {delta['buses']} more bus{'es' if delta['buses'] != 1 else ''} at "
            f"{getattr(depot, 'label', 'this depot')}."
        )
    elif delta["buses"] < 0:
        notes.append(f"Releases {abs(delta['buses'])} buses at {getattr(depot, 'label', 'this depot')}.")
    else:
        notes.append("Absorbed by the existing fleet — no additional buses required.")

    hours = parameters.duty_limit_minutes // 60
    share = after["over_duty_blocks"] / after["total_blocks"] if after["total_blocks"] else 0
    if share > 0.5:
        # Not a property of the scenario -- a property of how the baseline is
        # built. Minimum-fleet blocking imposes no cap on terminal idle time,
        # so a bus is chained all day and almost every block spans more than
        # one duty. Saying "N more blocks exceed 8h" here would imply the
        # change caused it. It did not, and an operations person would spot
        # that immediately.
        notes.append(
            f"Crew: {after['over_duty_blocks']} of {after['total_blocks']} blocks exceed a "
            f"{hours}h duty (median span {after['median_block_span_hours']}h) — both before and "
            "after. Minimum-fleet blocking chains a bus all day by design, so this schedule "
            "would need crew changes mid-block regardless of this scenario."
        )
    elif delta["over_duty_blocks"] > 0:
        notes.append(
            f"{delta['over_duty_blocks']} additional block(s) exceed the {hours}-hour duty span "
            "and would need splitting across two crews."
        )
    if not dead_km_is_stated:
        notes.append(
            "Dead km not shown: this depot's route-to-depot assignment is inferred by "
            "proximity, not stated in the published data, so any pull-out distance computed "
            "from it would be guesswork. BMTC's mapping would fill this in."
        )

    return {
        "scenario": {
            "route_number": change.route_number,
            "action": change.action,
            "window": f"{format_clock(change.start_minute)}-{format_clock(change.end_minute)}",
            "headway_minutes": change.headway_minutes,
            "trips": change.trips,
            "direction_id": change.direction_id,
            "description": change.describe(),
        },
        "depot": {"key": getattr(depot, "label", ""), "label": getattr(depot, "label", "")},
        "timetable": summary,
        "before": before,
        "after": after,
        "delta": delta,
        "notes": notes,
        "assumptions": {
            "average_speed_kmph": parameters.average_speed_kmph,
            "layover_minutes": parameters.layover_minutes,
            "max_deadhead_km": parameters.max_deadhead_km,
            "duty_limit_minutes": parameters.duty_limit_minutes,
        },
    }


class BlockingPlanService:
    def __init__(self) -> None:
        self._plan: dict[str, Any] | None = None
        self._context: dict[str, Any] | None = None
        self._lock = asyncio.Lock()

    async def get_plan(self) -> dict[str, Any]:
        if self._plan is not None:
            return self._plan
        async with self._lock:
            if self._plan is None:
                # ~15s of CPU-bound work: off the event loop, or every other
                # request on the server stalls behind it.
                self._plan = await asyncio.to_thread(compute_plan)
        return self._plan

    async def _get_context(self) -> dict[str, Any]:
        """Engine + route-to-depot index, kept alive so scenarios do not pay the
        full dataset load on every question."""
        if self._context is not None:
            return self._context
        async with self._lock:
            if self._context is None:
                self._context = await asyncio.to_thread(_build_context)
        return self._context

    async def run_scenario(self, change: ScenarioChange) -> dict[str, Any]:
        context = await self._get_context()
        key = context["depot_by_route"].get(change.route_number.strip().casefold())
        if key is None:
            raise LookupError(change.route_number)
        return await asyncio.to_thread(
            run_scenario,
            context["engine"],
            context["routes_by_depot"][key],
            context["depot_by_key"].get(key),
            change,
            context["parameters"],
            key in context["depots_with_stated_routes"],
        )

    async def known_routes(self, prefix: str = "", limit: int = 20) -> list[str]:
        context = await self._get_context()
        needle = prefix.strip().casefold()
        names = context["route_names"]
        matches = [n for n in names if n.casefold().startswith(needle)] if needle else names
        return matches[:limit]

    def clear(self) -> None:
        self._plan = None
        self._context = None


def _build_context(parameters: BlockingParameters | None = None) -> dict[str, Any]:
    parameters = parameters or BlockingParameters()
    engine = _build_engine(parameters)
    rows = {row.route_number: row for row in engine.block_by_route()}

    routes_by_depot: dict[str, list] = {}
    depot_by_key: dict[str, Any] = {}
    depot_by_route: dict[str, str] = {}
    # Depots where EVERY route's operating depot is stated in the route name.
    # Only these may quote a dead-km figure -- see run_scenario.
    #
    # "At least one stated route" was the first rule here and it was far too
    # loose: D20 Banashankari has 1 stated route out of 293, and that single
    # route was enough to publish a 17,214 km/day dead-km total computed almost
    # entirely from inferred assignments. Requiring the whole depot leaves 5
    # depots of 44 able to quote the figure, which is the true state of the
    # published data rather than a flattering reading of it.
    routes_seen: dict[str, int] = {}
    routes_stated: dict[str, int] = {}
    for route in engine.revenue_service():
        row = rows.get(route.route_number)
        if not row:
            continue
        key = row.depot.label if row.depot else UNASSIGNED
        routes_by_depot.setdefault(key, []).append(route)
        if row.depot:
            depot_by_key.setdefault(key, row.depot)
        routes_seen[key] = routes_seen.get(key, 0) + 1
        if row.depot_source == "route_code":
            routes_stated[key] = routes_stated.get(key, 0) + 1
        depot_by_route[route.route_number.casefold()] = key

    depots_with_stated_routes = {
        key for key, seen in routes_seen.items() if routes_stated.get(key, 0) == seen
    }

    return {
        "engine": engine,
        "parameters": parameters,
        "routes_by_depot": routes_by_depot,
        "depot_by_key": depot_by_key,
        "depot_by_route": depot_by_route,
        "depots_with_stated_routes": depots_with_stated_routes,
        "route_names": sorted({r.route_number for r in engine.revenue_service()}),
    }


blocking_plan_service = BlockingPlanService()
