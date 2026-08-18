"""Guards for the GTFS static export.

Two kinds of test, following test_blocking.py's split. The unit tests pin the
timing model and the exclusion rules on hand-built routes where the right
answer is countable by hand. The dataset tests build the real feed once and
assert the properties a consumer actually depends on -- referential integrity,
monotonic times, provenance present -- because the failure mode that matters
here is a feed that loads cleanly into a journey planner and is quietly wrong.
"""

from __future__ import annotations

import csv
import io
import zipfile

import pytest

from app.core.config import settings
from app.gtfs.builder import (
    GtfsBuildReport,
    GtfsFeedBuilder,
    GtfsParameters,
    format_gtfs_time,
)
from app.ml.data_loader import RouteRecord, load_routes
from app.ml.distance import GoogleMapsDistanceService
from app.ml.text import normalize_text


def _distance_service() -> GoogleMapsDistanceService:
    return GoogleMapsDistanceService(
        settings.artifact_dir / "google_distance_cache.json",
        api_key="",
        stop_coordinates_path=settings.stop_coordinates_path,
        max_remote_lookups=0,
    )


def _route(number: str, stops: list[str], trips: list[str], direction: int = 0) -> RouteRecord:
    return RouteRecord(
        route_number=number,
        full_name=f"{stops[0]} -> {stops[-1]}",
        trip_count=len(trips),
        trip_list=trips,
        stop_count=len(stops),
        stops=stops,
        route_id=number,
        direction_id=direction,
        source=stops[0],
        destination=stops[-1],
        normalized_stops=[normalize_text(stop) for stop in stops],
    )


# ── unit: time formatting ───────────────────────────────────────────────────
def test_format_gtfs_time_preserves_hours_past_midnight():
    assert format_gtfs_time(0) == "00:00:00"
    assert format_gtfs_time(3661) == "01:01:01"
    # A trip that departs 23:50 and arrives after midnight must read 24:xx, not
    # 00:xx. Wrapping it makes the trip appear to run backwards in time and
    # most consumers reject or mis-sort it.
    assert format_gtfs_time(24 * 3600 + 1200) == "24:20:00"
    assert format_gtfs_time(26 * 3600) == "26:00:00"


# ── unit: stop id resolution carries the published id ───────────────────────
def test_resolver_returns_published_stop_id():
    service = _distance_service()
    record = service.resolve_stop_record("Marathahalli")
    assert record is not None
    assert record.stop_id
    # resolve_coordinate must keep behaving exactly as before the record
    # refactor -- every distance and blocking calculation depends on it.
    assert service.resolve_coordinate("Marathahalli") == record.point


# ── unit: timing model ──────────────────────────────────────────────────────
def test_stop_times_are_monotonic_and_match_the_running_time_model():
    """Total trip time must equal driving + dwell x (stops - 2).

    That is the same figure BlockingEngine.running_time_minutes produces. If
    these two drift apart, the published timetable and the fleet plan disagree
    about how long a bus takes to run a route, and one of them is wrong.
    """
    builder = GtfsFeedBuilder([], _distance_service(), GtfsParameters())
    route = _route("TEST-1", ["Majestic", "Silk Board", "Marathahalli"], ["10:00:00"])
    resolved = builder._resolve_route(route, GtfsBuildReport())
    assert resolved is not None

    times = builder.stop_time_seconds(resolved, 600)
    assert times[0][0] == 600 * 60                      # first departure is published data
    for (arrival, departure) in times:
        assert departure >= arrival
    for previous, current in zip(times, times[1:]):
        assert current[0] >= previous[1]                # no arrival before the prior departure

    parameters = builder.parameters
    expected_driving = (resolved.total_km / parameters.average_speed_kmph) * 3600
    expected_dwell = parameters.dwell_minutes_per_stop * 60 * (len(resolved.records) - 2)
    actual = times[-1][1] - times[0][0]
    assert actual == pytest.approx(expected_driving + expected_dwell, abs=2)


# ── unit: exclusions ────────────────────────────────────────────────────────
def test_depot_pull_out_schedules_are_excluded():
    """A journey planner cannot tell that a trip carries no passengers, so a
    depot positioning run left in the feed becomes a bus riders are told to
    board."""
    builder = GtfsFeedBuilder([], _distance_service(), GtfsParameters())
    report = GtfsBuildReport()
    depot_run = _route("D44-ANP10", ["Majestic", "Marathahalli"], ["06:00:00"])
    assert builder._resolve_route(depot_run, report) is None
    assert report.dropped_depot_runs == 1

    # ...and the same route keeps its trips when the exclusion is turned off,
    # so the test is pinning the rule rather than an unrelated failure.
    permissive = GtfsFeedBuilder([], _distance_service(), GtfsParameters(exclude_depot_runs=False))
    assert permissive._resolve_route(depot_run, GtfsBuildReport()) is not None


def test_routes_without_departures_are_excluded():
    builder = GtfsFeedBuilder([], _distance_service(), GtfsParameters())
    report = GtfsBuildReport()
    assert builder._resolve_route(_route("X", ["Majestic", "Marathahalli"], []), report) is None
    assert report.dropped_no_departures == 1


# ── dataset: the real feed ──────────────────────────────────────────────────
@pytest.fixture(scope="module")
def built_feed(tmp_path_factory) -> zipfile.ZipFile:
    destination = tmp_path_factory.mktemp("gtfs") / "static.zip"
    builder = GtfsFeedBuilder(
        load_routes(settings.dataset_path), _distance_service(), GtfsParameters()
    )
    report = builder.build(destination)
    archive = zipfile.ZipFile(destination)
    archive.build_report = report          # type: ignore[attr-defined]
    return archive


def _rows(archive: zipfile.ZipFile, name: str):
    with archive.open(name) as handle:
        yield from csv.DictReader(io.TextIOWrapper(handle, encoding="utf-8", newline=""))


def test_feed_contains_every_required_file(built_feed):
    required = {
        "agency.txt", "stops.txt", "routes.txt", "calendar.txt",
        "trips.txt", "stop_times.txt", "feed_info.txt",
    }
    assert required <= set(built_feed.namelist())


def test_feed_is_referentially_intact(built_feed):
    """Every id a consumer follows must land somewhere. A dangling stop_id is
    the single most common way a derived feed fails to import."""
    stop_ids = {row["stop_id"] for row in _rows(built_feed, "stops.txt")}
    route_ids = {row["route_id"] for row in _rows(built_feed, "routes.txt")}
    shape_ids = {row["shape_id"] for row in _rows(built_feed, "shapes.txt")}
    service_ids = {row["service_id"] for row in _rows(built_feed, "calendar.txt")}

    trip_ids = set()
    for row in _rows(built_feed, "trips.txt"):
        assert row["route_id"] in route_ids
        assert row["service_id"] in service_ids
        assert row["direction_id"] in ("0", "1")
        if row["shape_id"]:
            assert row["shape_id"] in shape_ids
        trip_ids.add(row["trip_id"])

    seen_per_trip: dict[str, int] = {}
    for row in _rows(built_feed, "stop_times.txt"):
        assert row["stop_id"] in stop_ids
        assert row["trip_id"] in trip_ids
        seen_per_trip[row["trip_id"]] = seen_per_trip.get(row["trip_id"], 0) + 1

    # Both directions matter: an orphan trip has no times, and a trip with one
    # stop is a journey a planner can never use.
    assert set(seen_per_trip) == trip_ids
    assert min(seen_per_trip.values()) >= 2


def test_stop_times_never_go_backwards(built_feed):
    def seconds(value: str) -> int:
        hours, minutes, secs = value.split(":")
        return int(hours) * 3600 + int(minutes) * 60 + int(secs)

    current_trip = None
    previous_departure = -1
    for row in _rows(built_feed, "stop_times.txt"):
        if row["trip_id"] != current_trip:
            current_trip = row["trip_id"]
            previous_departure = -1
        arrival = seconds(row["arrival_time"])
        departure = seconds(row["departure_time"])
        assert arrival >= previous_departure
        assert departure >= arrival
        previous_departure = departure


def test_no_trip_lasts_an_implausible_length_of_time(built_feed):
    """The outstation coach services (Kalaburagi at 672 km) timed at the city
    running speed produced 30-40 hour trips. They are excluded, and this is
    the guard that says so -- a feed containing a 37-hour bus ride is not
    imprecise, it is broken."""
    def seconds(value: str) -> int:
        hours, minutes, secs = value.split(":")
        return int(hours) * 3600 + int(minutes) * 60 + int(secs)

    start: dict[str, int] = {}
    longest = 0
    for row in _rows(built_feed, "stop_times.txt"):
        trip_id = row["trip_id"]
        if trip_id not in start:
            start[trip_id] = seconds(row["arrival_time"])
        longest = max(longest, seconds(row["departure_time"]) - start[trip_id])
    assert longest <= 8 * 3600


def test_every_id_is_namespaced(built_feed):
    """A DBARS id must never be mistakable for an official BMTC one."""
    prefix = GtfsParameters().feed_prefix + "-"
    for row in _rows(built_feed, "routes.txt"):
        assert row["route_id"].startswith(prefix)
    for row in _rows(built_feed, "stops.txt"):
        assert row["stop_id"].startswith(prefix)


def test_provenance_travels_with_the_feed(built_feed):
    """Three independent places, because a consumer who strips one still has
    two. Publishing modelled timings without saying so is the one failure this
    exporter must not have."""
    readme = built_feed.read("README.txt").decode("utf-8")
    assert "UNOFFICIAL" in readme
    assert "OVERSTATES SUNDAY" in readme
    assert "interpolated" in readme

    info = next(_rows(built_feed, "feed_info.txt"))
    assert "unofficial" in info["feed_publisher_name"].lower()
    assert info["feed_version"]

    # timepoint=0 is GTFS's own marker for an interpolated time, and it is the
    # only part of the provenance a machine reads.
    for _, row in zip(range(200), _rows(built_feed, "stop_times.txt")):
        assert row["timepoint"] == "0"


def test_build_report_accounts_for_everything_dropped(built_feed):
    report: GtfsBuildReport = built_feed.build_report      # type: ignore[attr-defined]
    accounted = (
        report.route_directions_kept
        + report.dropped_depot_runs
        + report.dropped_too_long
        + report.dropped_too_few_resolvable_stops
        + report.dropped_no_departures
        + report.dropped_unresolved_geometry
    )
    assert accounted == report.route_directions_in
    # The stop-name join is exact (routes and the stop list share all 4,883
    # names), so any unresolved stop means that assumption has broken.
    assert report.skipped_unresolvable_stops == 0
