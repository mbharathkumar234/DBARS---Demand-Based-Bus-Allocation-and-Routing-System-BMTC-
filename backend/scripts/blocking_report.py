"""Minimum fleet and dead kilometres, computed from the BMTC timetable.

Reports three things, kept strictly separate by how well the data supports them:

  1. FLEET REQUIREMENT   -- provable from the timetable alone.
  2. INTERLINING SAVING  -- provable from the timetable alone. The headline.
  3. DEAD KILOMETRES     -- only for routes whose operating depot the dataset
                            states outright. The citywide figure is NOT
                            computable until BMTC supplies its route->depot
                            mapping, and is reported as such rather than
                            guessed.

Usage:
    python scripts/blocking_report.py
    python scripts/blocking_report.py --json out.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings
from app.ml.blocking import (
    MAX_PLAUSIBLE_ROUTE_KM,
    MIN_PLAUSIBLE_ROUTE_KM,
    BlockingEngine,
    BlockingParameters,
    load_depots,
)
from app.ml.data_loader import load_routes
from app.ml.distance import GoogleMapsDistanceService


def build_engine(parameters: BlockingParameters) -> BlockingEngine:
    routes = load_routes(settings.dataset_path)
    depots = load_depots(settings.depot_dataset_path)
    distance_service = GoogleMapsDistanceService(
        settings.artifact_dir / "google_distance_cache.json",
        api_key="",                 # offline: coordinates only, no remote calls
        stop_coordinates_path=settings.stop_coordinates_path,
        max_remote_lookups=0,
    )
    return BlockingEngine(routes, depots, distance_service, parameters)


def rule(title: str) -> None:
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--speed", type=float, default=16.0, help="average km/h")
    parser.add_argument("--layover", type=int, default=10, help="terminal layover, minutes")
    parser.add_argument("--max-idle", type=int, default=None,
                        help="max terminal wait in minutes; omit for no cap (true minimum fleet)")
    parser.add_argument("--deadhead", type=float, default=5.0,
                        help="max empty repositioning between trips, km")
    parser.add_argument("--top", type=int, default=12, help="rows per table")
    parser.add_argument("--json", type=str, default="", help="write full results here")
    args = parser.parse_args()

    parameters = BlockingParameters(
        average_speed_kmph=args.speed,
        layover_minutes=args.layover,
        max_terminal_idle_minutes=args.max_idle,
        max_deadhead_km=args.deadhead,
    )

    started = time.time()
    engine = build_engine(parameters)
    geocoded = sum(1 for d in engine.depots if d.point)
    per_route = engine.block_by_route()

    revenue_routes = engine.revenue_service()
    revenue_names = {r.route_number for r in revenue_routes}
    revenue_rows = [r for r in per_route if r.route_number in revenue_names]

    depot_runs = [r for r in per_route if r.is_depot_run]
    suspect = [r for r in per_route if r.geometry_suspect and not r.is_depot_run]

    rule("DATA QUALITY  (what was excluded, and why)")
    print(f"  depots in workbook                : {len(engine.depots):>7}  ({geocoded} geocoded)")
    print(f"  route names in dataset            : {len(per_route):>7}")
    print(f"  - depot pull-out/pull-in schedules: {len(depot_runs):>7}"
          f"  ({sum(r.trip_count for r in depot_runs):,} trips) -> dead running, not service")
    print(f"  - implausible geometry            : {len(suspect):>7}"
          f"  (outside {MIN_PLAUSIBLE_ROUTE_KM:.0f}-{MAX_PLAUSIBLE_ROUTE_KM:.0f} km/direction)")
    print(f"  = passenger routes analysed       : {len(revenue_rows):>7}"
          f"  ({sum(r.trip_count for r in revenue_rows):,} trips)")

    # ── 1. fleet requirement ────────────────────────────────────────────────
    baseline_buses = sum(r.buses_required for r in revenue_rows)
    lower_bound = sum(r.concurrency_lower_bound for r in revenue_rows)
    optimal = sum(1 for r in revenue_rows if r.is_provably_minimal)
    revenue_km = sum(r.revenue_km for r in revenue_rows)

    rule("1. FLEET REQUIREMENT  (from the timetable alone)")
    print(f"  scheduled passenger trips/day     : {sum(r.trip_count for r in revenue_rows):>7,}")
    print(f"  revenue km/day                    : {revenue_km:>7,.0f}")
    print()
    print(f"  buses, no interlining (baseline)  : {baseline_buses:>7,}")
    print(f"  hard lower bound (max overlap)    : {lower_bound:>7,}")
    print(f"  routes already provably minimal   : {optimal:>7,} / {len(revenue_rows)}")

    # ── 2. interlining ──────────────────────────────────────────────────────
    interlined = engine.block_interlined(revenue_routes)
    interlined_buses = len(interlined)
    saved = baseline_buses - interlined_buses
    network_bound = engine.concurrency_lower_bound(engine.all_trips(revenue_routes))
    trips_total = sum(r.trip_count for r in revenue_rows)

    rule("2. INTERLINING SAVING  (the DBARS lever, same timetable)")
    print(f"  buses, each route name separate   : {baseline_buses:>7,}")
    print(f"  buses, chaining across route names: {interlined_buses:>7,}")
    if baseline_buses:
        print(f"  buses released                    : {saved:>7,}"
              f"   ({saved / baseline_buses * 100:.1f}%)")
    print(f"  network-wide hard lower bound      : {network_bound:>7,}"
          f"   (max trips ever in progress at once)")
    print()
    print("  Same trips, same headways, same passengers served.")
    print("  The only thing that changed is which bus runs which trip.")

    if interlined:
        served = sum(len(b.trips) for b in interlined)
        idle = sum(b.idle_minutes for b in interlined)
        km_per_bus = revenue_km / max(interlined_buses, 1)
        print()
        print(f"  trips per bus/day  baseline {trips_total / max(baseline_buses, 1):>5.1f}"
              f"  ->  interlined {served / max(interlined_buses, 1):>5.1f}")
        print(f"  revenue km per bus/day, interlined : {km_per_bus:>7,.0f} km")
        print(f"  terminal idle time, interlined     : {idle / 60:>7,.0f} bus-hours/day")
        print()
        print("  SANITY CHECK -- a real BMTC bus covers roughly 180-200 km and")
        print("  8-12 trips a day. If the two figures above are far from that,")
        print("  the chaining model is wrong, not BMTC.")

    # ── 3. dead km ──────────────────────────────────────────────────────────
    explicit = [r for r in revenue_rows if r.depot_source == "route_code" and r.depot and r.depot.point]
    inferred = [r for r in revenue_rows if r.depot_source == "nearest_terminal"]

    rule("3. DEAD KILOMETRES  (only where the depot is stated, not guessed)")
    print(f"  routes with depot stated in name  : {len(explicit):>7,}")
    print(f"  routes needing BMTC depot mapping : {len(inferred):>7,}   <- BLOCKED")
    if explicit:
        e_dead = sum(r.dead_km for r in explicit)
        e_rev = sum(r.revenue_km for r in explicit)
        e_total = e_dead + e_rev
        print()
        print(f"  on those {len(explicit)} routes:")
        print(f"    revenue km/day                  : {e_rev:>7,.0f}")
        print(f"    dead km/day (pull-out + pull-in): {e_dead:>7,.0f}")
        print(f"    dead km share                   : {e_dead / e_total * 100:>6.1f}%")
        print()
        print(f"  {'route':<20} {'buses':>5} {'trips':>6} {'rev km':>8} {'dead km':>8} {'dead%':>6}")
        for r in sorted(explicit, key=lambda r: -r.dead_km)[: args.top]:
            print(f"  {r.route_number:<20} {r.buses_required:>5} {r.trip_count:>6} "
                  f"{r.revenue_km:>8,.0f} {r.dead_km:>8,.0f} {r.dead_km_pct:>5.1f}%")

    print()
    print("  A citywide dead-km figure is NOT reported here. It depends entirely")
    print("  on which depot operates each route, and that is the single field")
    print("  missing from the published data. Inferring it by proximity puts")
    print(f"  {len(inferred):,} routes on whichever depot happens to sit nearest a")
    print("  central terminal, which would produce a confident-looking number")
    print("  with no basis. Ask BMTC for the mapping; everything else is ready.")

    # ── measured dead running that IS in the data ───────────────────────────
    if depot_runs:
        rule("MEASURED DEAD RUNNING  (depot schedules already in the dataset)")
        dr_trips = sum(r.trip_count for r in depot_runs)
        print(f"  depot pull-out/pull-in schedules   : {len(depot_runs):>6,}")
        print(f"  trips/day on them                  : {dr_trips:>6,}")
        print(f"  share of all scheduled trips       : "
              f"{dr_trips / sum(r.trip_count for r in per_route) * 100:>5.1f}%")
        print()
        print("  BMTC publishes these as named schedules, so this portion of dead")
        print("  running is measured rather than modelled.")
        print()
        print(f"  {'schedule':<20} {'trips':>6}  terminals")
        for r in sorted(depot_runs, key=lambda r: -r.trip_count)[: args.top]:
            block = r.blocks[0] if r.blocks else None
            terminals = (
                f"{block.trips[0].origin} -> {block.trips[-1].destination}" if block else "-"
            )
            print(f"  {r.route_number:<20} {r.trip_count:>6}  {terminals}")

    rule("ASSUMPTIONS  (replace these with BMTC's observed figures)")
    print(f"  average running speed  : {parameters.average_speed_kmph} km/h")
    print(f"  dwell per stop         : {parameters.dwell_minutes_per_stop} min")
    print(f"  terminal layover       : {parameters.layover_minutes} min")
    print(f"  max terminal idle      : {parameters.max_terminal_idle_minutes or 'no cap'}")
    print(f"  max deadhead reposition: {parameters.max_deadhead_km} km")
    print(f"  road circuity factor   : {parameters.circuity_factor}")
    print(f"\n  computed in {time.time() - started:.1f}s")

    if args.json:
        payload = {
            "parameters": {
                "average_speed_kmph": parameters.average_speed_kmph,
                "layover_minutes": parameters.layover_minutes,
                "max_terminal_idle_minutes": parameters.max_terminal_idle_minutes,
                "circuity_factor": parameters.circuity_factor,
            },
            "fleet": {
                "passenger_routes": len(revenue_rows),
                "trips": sum(r.trip_count for r in revenue_rows),
                "revenue_km": round(revenue_km, 1),
                "buses_baseline": baseline_buses,
                "buses_interlined": interlined_buses,
                "buses_released": saved,
                "hard_lower_bound": lower_bound,
            },
            "dead_km_explicit_depot": {
                "routes": len(explicit),
                "dead_km": round(sum(r.dead_km for r in explicit), 1),
                "revenue_km": round(sum(r.revenue_km for r in explicit), 1),
            },
            "blocked_on": {
                "routes_needing_depot_mapping": len(inferred),
            },
            "routes": [
                {
                    "route": r.route_number,
                    "depot": r.depot.label if r.depot else None,
                    "depot_source": r.depot_source,
                    "buses": r.buses_required,
                    "lower_bound": r.concurrency_lower_bound,
                    "trips": r.trip_count,
                    "revenue_km": round(r.revenue_km, 1),
                    "dead_km": round(r.dead_km, 1) if r.depot_source == "route_code" else None,
                }
                for r in revenue_rows
            ],
        }
        Path(args.json).write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"\n  wrote {args.json}")


if __name__ == "__main__":
    main()
