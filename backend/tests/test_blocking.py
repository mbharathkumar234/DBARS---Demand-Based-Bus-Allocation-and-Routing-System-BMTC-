"""Guards for the vehicle-blocking engine.

Two kinds of test here. The unit tests pin the chaining logic on hand-built
timetables where the correct answer is countable by hand. The dataset tests
pin the outputs against real-world plausibility, because every wrong version
of this engine so far was wrong in a way that still ran cleanly and produced
confident-looking numbers -- 30,570 buses for a 6,000-bus operator, 36% dead
kilometres, routes with 23 revenue km and 9,885 dead km. Only a sanity range
catches that class of failure.
"""

from __future__ import annotations

import pytest

from app.core.config import settings
from app.ml.blocking import (
    BlockingEngine,
    BlockingParameters,
    Trip,
    load_depots,
    parse_clock,
)
from app.ml.data_loader import load_routes
from app.ml.distance import GoogleMapsDistanceService


# ── unit: clock parsing ─────────────────────────────────────────────────────
def test_parse_clock_handles_post_midnight_hours():
    assert parse_clock("00:30:00") == 30
    assert parse_clock("17:45:00") == 1065
    # GTFS-style "next morning" times must stay monotonic, not wrap to 30,
    # or a block spanning midnight silently splits into two buses.
    assert parse_clock("24:30:00") == 1470
    assert parse_clock("") is None
    assert parse_clock("garbage") is None


# ── unit: chaining ──────────────────────────────────────────────────────────
def _engine(**overrides) -> BlockingEngine:
    parameters = BlockingParameters(**overrides)
    service = GoogleMapsDistanceService(
        settings.artifact_dir / "google_distance_cache.json",
        api_key="",
        stop_coordinates_path=settings.stop_coordinates_path,
        max_remote_lookups=0,
    )
    return BlockingEngine([], [], service, parameters)


def _trip(depart: int, duration: int, origin: str, destination: str) -> Trip:
    return Trip(
        route_number="T",
        direction_id=0,
        depart_minute=depart,
        arrive_minute=depart + duration,
        origin=origin,
        destination=destination,
        revenue_km=10.0,
    )


def test_out_and_back_trips_reuse_one_bus():
    engine = _engine(max_deadhead_km=0.0, layover_minutes=10)
    trips = [
        _trip(0, 60, "a", "b"),     # 00:00 a->b, arrives 01:00
        _trip(70, 60, "b", "a"),    # 01:10 b->a, 10 min layover: same bus
    ]
    blocks = engine.chain_blocks(trips)
    assert len(blocks) == 1
    assert len(blocks[0].trips) == 2


def test_layover_shortfall_forces_a_second_bus():
    engine = _engine(max_deadhead_km=0.0, layover_minutes=10)
    trips = [
        _trip(0, 60, "a", "b"),
        _trip(65, 60, "b", "a"),    # only 5 min after arrival, below layover
    ]
    assert len(engine.chain_blocks(trips)) == 2


def test_overlapping_trips_cannot_share_a_bus():
    engine = _engine(max_deadhead_km=0.0)
    trips = [_trip(0, 60, "a", "b"), _trip(10, 60, "a", "b"), _trip(20, 60, "a", "b")]
    blocks = engine.chain_blocks(trips)
    assert len(blocks) == 3
    assert engine.concurrency_lower_bound(trips) == 3


def test_concurrency_bound_never_exceeds_block_count():
    """The bound is a hard floor; a chaining that beat it would be a bug."""
    engine = _engine(max_deadhead_km=0.0)
    trips = [
        _trip(0, 30, "a", "b"), _trip(15, 30, "a", "b"), _trip(45, 30, "b", "a"),
        _trip(60, 30, "a", "b"), _trip(200, 30, "a", "b"),
    ]
    assert engine.concurrency_lower_bound(trips) <= len(engine.chain_blocks(trips))


def test_idle_cap_retires_a_bus_instead_of_stranding_it():
    """A bus idle past the cap must leave the pool.

    Leaving it in was a real bug: it could never satisfy the cap again, so it
    was never reused and its block ended after one trip, which roughly doubled
    the computed fleet.
    """
    engine = _engine(max_deadhead_km=0.0, layover_minutes=10, max_terminal_idle_minutes=30)
    trips = [
        _trip(0, 60, "a", "b"),        # arrives at b at 01:00
        _trip(200, 60, "b", "a"),      # 140 min later: past the cap, new bus
        _trip(280, 60, "a", "b"),      # must reuse the bus freed at 260, not a third
    ]
    blocks = engine.chain_blocks(trips)
    assert len(blocks) == 2


def test_deadhead_allows_reuse_across_nearby_terminals(monkeypatch):
    engine = _engine(max_deadhead_km=5.0, layover_minutes=10)
    # Two terminals 2 km apart; a bus finishing at "b" can reposition to "c".
    monkeypatch.setattr(
        engine, "_stop_point",
        lambda name, near=None: {"a": (12.90, 77.50), "b": (12.95, 77.55),
                                 "c": (12.96, 77.56)}.get(name),
    )
    trips = [_trip(0, 60, "a", "b"), _trip(90, 60, "c", "a")]
    blocks = engine.chain_blocks(trips)
    assert len(blocks) == 1
    assert blocks[0].deadhead_km > 0
    assert blocks[0].dead_km == pytest.approx(blocks[0].deadhead_km)


def test_deadhead_disabled_keeps_terminals_separate(monkeypatch):
    engine = _engine(max_deadhead_km=0.0, layover_minutes=10)
    monkeypatch.setattr(
        engine, "_stop_point",
        lambda name, near=None: {"a": (12.90, 77.50), "b": (12.95, 77.55),
                                 "c": (12.96, 77.56)}.get(name),
    )
    trips = [_trip(0, 60, "a", "b"), _trip(90, 60, "c", "a")]
    assert len(engine.chain_blocks(trips)) == 2


# ── dataset: real-world plausibility ────────────────────────────────────────
@pytest.fixture(scope="module")
def dataset_engine() -> BlockingEngine:
    if not settings.dataset_path.exists() or not settings.depot_dataset_path.exists():
        pytest.skip("dataset not available")
    service = GoogleMapsDistanceService(
        settings.artifact_dir / "google_distance_cache.json",
        api_key="",
        stop_coordinates_path=settings.stop_coordinates_path,
        max_remote_lookups=0,
    )
    return BlockingEngine(
        load_routes(settings.dataset_path),
        load_depots(settings.depot_dataset_path),
        service,
        BlockingParameters(),
    )


def test_depot_workbook_matches_route_depot_codes(dataset_engine):
    """The D<n> codes embedded in route names must resolve against the depot
    workbook. If they stop doing so, one of the two files has changed shape and
    every depot-based figure downstream is quietly wrong."""
    numbers = {d.number for d in dataset_engine.depots if d.number}
    assert "45" in numbers and "29" in numbers
    assert sum(1 for d in dataset_engine.depots if d.point) >= 35


def test_interlined_fleet_is_operationally_plausible(dataset_engine):
    revenue = dataset_engine.revenue_service()
    blocks = dataset_engine.block_interlined(revenue)
    bound = dataset_engine.concurrency_lower_bound(dataset_engine.all_trips(revenue))

    # A chaining that beats the hard bound is arithmetically impossible.
    assert len(blocks) >= bound

    # BMTC runs on the order of 6,000-6,500 buses. Anything far outside this
    # band means the model is broken, not that BMTC is.
    assert 4_000 <= len(blocks) <= 9_000, f"implausible fleet: {len(blocks)}"

    revenue_km = sum(b.revenue_km for b in blocks)
    km_per_bus = revenue_km / len(blocks)
    assert 120 <= km_per_bus <= 260, f"implausible km/bus/day: {km_per_bus:.0f}"

    trips_per_bus = sum(len(b.trips) for b in blocks) / len(blocks)
    assert 4 <= trips_per_bus <= 14, f"implausible trips/bus/day: {trips_per_bus:.1f}"


def test_interlining_beats_per_route_blocking(dataset_engine):
    """The whole DBARS claim is that chaining across route names releases buses.
    If this ever inverts, the claim is dead and the pitch must change."""
    revenue = dataset_engine.revenue_service()
    names = {r.route_number for r in revenue}
    per_route = [r for r in dataset_engine.block_by_route() if r.route_number in names]
    baseline = sum(r.buses_required for r in per_route)
    interlined = len(dataset_engine.block_interlined(revenue))
    assert interlined < baseline


def test_revenue_service_excludes_depot_runs_and_bad_geometry(dataset_engine):
    revenue = dataset_engine.revenue_service()
    assert not any(r.route_number.upper().startswith(("D1-", "D7-", "D44-")) for r in revenue)
    for route in revenue:
        km = dataset_engine.route_length_km(route)
        assert km is not None and 1.0 <= km <= 60.0
