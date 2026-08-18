"""Serves the crew duty plan to the depot and admin dashboards.

Sits directly on top of blocking_service.py and reuses its cached context --
the engine, the route-to-depot index, the depot list -- rather than rebuilding
any of it. The vehicle plan and the crew plan must be answers about the same
schedule; deriving them from two independently built engines would let them
drift apart, which is precisely the failure this module exists to prevent.

Deliberately independent of MongoDB, for the same reason blocking_service.py
is: everything here comes from the timetable CSV and the depot workbook, both
of which ship with the repo. The panel meant to be shown to BMTC keeps working
when the database does not.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from app.ml.blocking import BlockingEngine
from app.ml.crew import CrewParameters, schedule_crew, summarize
from app.services.blocking_service import UNASSIGNED, blocking_plan_service

logger = logging.getLogger("bmtc.services.crew")


def _depot_crew(
    engine: BlockingEngine, depot_routes: list, parameters: CrewParameters
) -> dict[str, Any]:
    blocks = engine.block_interlined(depot_routes)
    return summarize(schedule_crew(blocks, parameters), parameters)


def compute_crew_plan(context: dict[str, Any], parameters: CrewParameters) -> dict[str, Any]:
    """Duties required to staff the blocked timetable, network-wide and per depot."""
    started = time.perf_counter()
    engine: BlockingEngine = context["engine"]

    revenue_routes = engine.revenue_service()
    network_blocks = engine.block_interlined(revenue_routes)
    network_schedule = schedule_crew(network_blocks, parameters)
    network = summarize(network_schedule, parameters)

    depots: list[dict[str, Any]] = []
    for key, depot_routes in context["routes_by_depot"].items():
        depot = context["depot_by_key"].get(key)
        entry = _depot_crew(engine, depot_routes, parameters)
        entry.pop("assumptions", None)          # stated once, at the top level
        entry["key"] = key
        entry["label"] = key
        entry["zone"] = depot.zone if depot else ""
        entry["number"] = depot.number if depot else ""
        entry["routes"] = len(depot_routes)
        depots.append(entry)

    depots.sort(key=lambda entry: -entry["duties"])
    elapsed = time.perf_counter() - started
    logger.info(
        "Crew plan computed in %.1fs: %s duties for %s blocks across %s depots",
        elapsed, network["duties"], network["blocks"], len(depots),
    )

    return {
        "status": "ok",
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "computed_in_seconds": round(elapsed, 1),
        "source": (
            "Crew duties derived from the vehicle blocks in /depot/blocking-plan, "
            "which come from BMTC's published timetable (routes_cleaned.csv)."
        ),
        "network": network,
        "depots": depots,
        "caveats": [
            "Every crew rule here is an assumption, not a BMTC figure. Duty limits, "
            "spreadover, break rules and relief points come from crew agreements that "
            "are not in any published dataset. Replace them before quoting a headcount "
            "or a wage cost.",
            "Relief points default to every terminal, which is permissive and therefore "
            "UNDERSTATES the duty count. A real relief point list is short and would "
            "raise it.",
            "These are daily duties, not employees. Weekly offs, leave and standby cover "
            "multiply this figure -- a real operator staffs roughly 1.4-1.5 people per "
            "daily duty.",
            "Duties are counted, not rostered. Assigning them to named crew needs real "
            "crew records and is a separate exercise.",
        ],
    }


class CrewPlanService:
    def __init__(self) -> None:
        self._plan: dict[str, Any] | None = None
        self._lock = asyncio.Lock()

    async def get_plan(self) -> dict[str, Any]:
        if self._plan is not None:
            return self._plan
        async with self._lock:
            # Re-check inside the lock so queued callers take the first
            # result rather than each starting their own computation.
            if self._plan is None:
                context = await blocking_plan_service._get_context()
                self._plan = await asyncio.to_thread(
                    compute_crew_plan, context, CrewParameters()
                )
        return self._plan

    async def run_scenario(self, parameters: CrewParameters, depot: str = "") -> dict[str, Any]:
        """Re-schedule crew under different agreement rules.

        Scoped to one depot when given, because a full network re-schedule is
        ~7s including the re-block and that is not a console anyone will use
        interactively. Scoping is also the honest unit: crew belong to a depot,
        and a rule change is negotiated per agreement, not per network.
        """
        context = await blocking_plan_service._get_context()
        if not depot:
            return await asyncio.to_thread(compute_crew_plan, context, parameters)

        depot_routes = context["routes_by_depot"].get(depot)
        if depot_routes is None:
            raise LookupError(depot)

        engine: BlockingEngine = context["engine"]
        baseline, proposed = await asyncio.to_thread(
            lambda: (
                _depot_crew(engine, depot_routes, CrewParameters()),
                _depot_crew(engine, depot_routes, parameters),
            )
        )
        delta = {
            key: round(proposed[key] - baseline[key], 2)
            for key in ("duties", "split_duties", "paid_hours", "unstaffable_blocks")
        }
        return {
            "status": "ok",
            "depot": {"key": depot, "label": depot},
            "before": baseline,
            "after": proposed,
            "delta": delta,
            "notes": _scenario_notes(baseline, proposed, delta),
        }

    async def known_depots(self) -> list[str]:
        context = await blocking_plan_service._get_context()
        return sorted(context["routes_by_depot"].keys())

    def clear(self) -> None:
        self._plan = None


def _scenario_notes(baseline: dict[str, Any], proposed: dict[str, Any], delta: dict[str, Any]) -> list[str]:
    notes: list[str] = []
    if delta["duties"] > 0:
        notes.append(
            f"Needs {delta['duties']} more daily duties at this depot "
            f"({baseline['duties']} -> {proposed['duties']})."
        )
    elif delta["duties"] < 0:
        notes.append(
            f"Releases {abs(delta['duties'])} daily duties at this depot "
            f"({baseline['duties']} -> {proposed['duties']})."
        )
    else:
        notes.append("No change in the number of duties required.")

    notes.append(
        f"Crew per bus moves from {baseline['crew_to_bus_ratio']} to {proposed['crew_to_bus_ratio']}."
    )
    if delta["unstaffable_blocks"] > 0:
        notes.append(
            f"{delta['unstaffable_blocks']} more block(s) become unstaffable under these rules -- "
            "no legal way to split them into duties. Those trips would need a timetable change, "
            "not a rostering change."
        )
    if proposed["split_duty_pct"] > baseline["split_duty_pct"] + 5:
        notes.append(
            f"Split duties rise from {baseline['split_duty_pct']}% to {proposed['split_duty_pct']}% "
            "of all duties. Split shifts are the usual flashpoint in a crew agreement, so a plan "
            "that leans on them is a plan that has to be negotiated."
        )
    return notes


crew_plan_service = CrewPlanService()
