"""GTFS static feed built from dataset/routes_cleaned.csv + stops_cleaned.csv.

WHAT IS EXACT VS WHAT IS MODELLED
---------------------------------
Exact, straight out of BMTC's published data:
    route numbers, route names, stop sequences, stop coordinates, published
    stop ids, and every trip's DEPARTURE TIME from its first stop (the
    dataset's `trip_list` column is the real timetable).

Modelled here, and therefore configurable via GtfsParameters:
    the times at every stop AFTER the first. The dataset gives departures,
    not stop-by-stop timings, so intermediate times are interpolated from
    stop-to-stop geometry, an assumed running speed, and an assumed dwell.
    Every stop_time is written with timepoint=0, which is GTFS's own way of
    saying "interpolated, not observed" -- consumers that care can tell.

    The service calendar. The dataset carries no day-of-week information, so
    the feed declares one DAILY service. This overstates Sunday service and
    is the single most valuable correction BMTC could supply; supply a real
    calendar and this becomes exact too.

Publishing a feed whose times were modelled without saying so is worse than
publishing nothing, so the provenance is stated in three places that travel
with the file: feed_info.txt, a README.txt inside the zip, and the
`feed_prefix` namespacing of every id (a DBARS id can never be mistaken for,
or collide with, an official BMTC one).
"""

from __future__ import annotations

import csv
import hashlib
import io
import logging
import os
import tempfile
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator

from app.ml.blocking import _DEPOT_RUN_RE, parse_clock
from app.ml.data_loader import RouteRecord
from app.ml.distance import GoogleMapsDistanceService, StopRecord
from app.ml.route_geometry import resolve_route_geometry

logger = logging.getLogger("bmtc.gtfs.builder")

GTFS_ROUTE_TYPE_BUS = 3


@dataclass(frozen=True)
class GtfsParameters:
    """Everything this exporter assumes, in one place.

    The first three mirror BlockingParameters in app/ml/blocking.py on
    purpose: they are the same physical assumptions about the same buses, and
    letting them drift apart would mean the fleet plan and the published
    timetable disagreed about how long a route takes.
    """

    agency_id: str = "BMTC"
    agency_name: str = "Bangalore Metropolitan Transport Corporation"
    agency_url: str = "https://mybmtc.karnataka.gov.in/"
    agency_timezone: str = "Asia/Kolkata"
    agency_lang: str = "en"

    feed_prefix: str = "dbars"
    """Namespaces every id in the feed. A consumer that sees `dbars-500D` can
    never mistake it for an official BMTC identifier, and two feeds can be
    loaded side by side without colliding."""

    feed_publisher_name: str = "DBARS (unofficial, derived from published BMTC data)"
    feed_publisher_url: str = "https://github.com/"
    feed_contact_email: str = ""

    service_id: str = "DAILY"
    calendar_days: int = 365

    average_speed_kmph: float = 16.0
    dwell_minutes_per_stop: float = 0.3
    circuity_factor: float = 1.2
    """See BlockingParameters for the reasoning behind each of these three."""

    include_shapes: bool = True
    """shapes.txt is drawn stop-to-stop, not along the road centreline -- we
    have stop coordinates, not road geometry. Consecutive BMTC stops are close
    together so the result tracks the real path well, but it is an
    approximation and is described as one in the in-zip README."""

    min_stops_per_trip: int = 2

    exclude_depot_runs: bool = True
    """Schedules whose name begins with a depot code (D44-ANP10, D14G-AFG) are
    the depot's own pull-out/pull-in positioning runs -- typically two stops,
    "Depot-NN Gate" to a terminal, carrying no passengers. blocking.py already
    identifies them (_DEPOT_RUN_RE) and books them as dead running.

    They must not appear in a public feed. A journey planner cannot tell that a
    trip is non-revenue, so leaving them in means Google Maps will cheerfully
    route a rider to a depot gate to board a bus that will not carry them."""

    max_route_km: float = 100.0
    """Routes longer than this are dropped as not-city-service.

    The dataset contains a handful of genuine outstation coach services
    (KALABURAGI at 672 km, YADGIRI at 619 km, VIJAYAPURA at 602 km). Timing
    those at the city running speed above produces trips lasting 30-40 hours,
    which is not merely imprecise -- it is broken data that would corrupt any
    journey planner that ingested it.

    Note this is deliberately more permissive than the 60 km ceiling
    blocking.py uses for fleet totals. That band exists to keep untrustworthy
    geometry out of a bus count; this one exists to keep absurd trips out of a
    timetable, and 66 real Bengaluru routes fall in the 60-70 km range and
    belong in the feed. Set to 0 to disable the check entirely."""

    @property
    def assumptions(self) -> dict[str, object]:
        """Echoed into the build report and feed_info so no consumer has to
        read this file to find out what was assumed."""
        return {
            "average_speed_kmph": self.average_speed_kmph,
            "dwell_minutes_per_stop": self.dwell_minutes_per_stop,
            "circuity_factor": self.circuity_factor,
            "service_calendar": (
                f"single '{self.service_id}' service running all seven days -- the "
                "source dataset carries no day-of-week information"
            ),
            "stop_times": (
                "only the first stop's departure is published data; every later "
                "stop time is interpolated and flagged timepoint=0"
            ),
            "shapes": (
                "stop-to-stop polyline, not road centreline" if self.include_shapes
                else "not included"
            ),
            "exclusions": (
                f"depot pull-out/pull-in schedules{'' if self.exclude_depot_runs else ' (DISABLED)'}; "
                f"services longer than {self.max_route_km} km"
            ),
        }


@dataclass
class GtfsBuildReport:
    """What the build actually produced, including everything it dropped.

    A feed that silently omits routes is indistinguishable from a feed that
    never had them, so the counts below are part of the deliverable rather
    than a log line.
    """

    built_at: str = ""
    duration_seconds: float = 0.0
    dataset_fingerprint: str = ""
    feed_version: str = ""
    output_path: str = ""
    output_bytes: int = 0

    routes: int = 0
    trips: int = 0
    stop_times: int = 0
    stops: int = 0
    shapes: int = 0

    route_directions_in: int = 0
    route_directions_kept: int = 0
    dropped_too_few_resolvable_stops: int = 0
    dropped_no_departures: int = 0
    dropped_unresolved_geometry: int = 0
    dropped_depot_runs: int = 0
    dropped_too_long: int = 0
    skipped_unresolvable_stops: int = 0
    unresolvable_stop_names: list[str] = field(default_factory=list)
    excluded_long_routes: list[str] = field(default_factory=list)
    geometry_suspect_routes: list[str] = field(default_factory=list)

    assumptions: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        payload = self.__dict__.copy()
        # A handful of examples is diagnostic; thousands is a data dump.
        payload["unresolvable_stop_names"] = sorted(self.unresolvable_stop_names)[:50]
        payload["excluded_long_routes"] = sorted(self.excluded_long_routes)[:50]
        payload["geometry_suspect_routes"] = sorted(self.geometry_suspect_routes)[:50]
        return payload


# The band blocking.py trusts its geometry within. Routes outside it are still
# published -- a rider looking for that bus should find it, and 66 real
# Bengaluru routes run 60-70 km -- but they are named in the build report so a
# reviewer can check them. Genuinely absurd geometry is excluded separately by
# GtfsParameters.max_route_km, which is a different judgement: not "is this
# measurement shaky" but "is this trip impossible".
MIN_PLAUSIBLE_ROUTE_KM = 1.0
MAX_PLAUSIBLE_ROUTE_KM = 60.0


@dataclass(slots=True)
class _ResolvedRoute:
    """One route-direction, resolved to published stops with cumulative distance."""

    route: RouteRecord
    records: list[StopRecord]
    cumulative_km: list[float]
    departures: list[int]

    @property
    def total_km(self) -> float:
        return self.cumulative_km[-1]

    @property
    def shape_id(self) -> str:
        return f"{self.route.route_number}-{self.route.direction_id}"


def _slug(value: str) -> str:
    """Ids must survive a CSV round-trip and a URL. Whitespace is the only
    thing in BMTC route names that reliably breaks consumers, so that is all
    this collapses -- the name stays recognisable, which matters when someone
    is eyeballing a feed against a timetable."""
    return "_".join(str(value).split())


def format_gtfs_time(total_seconds: int) -> str:
    """Seconds after midnight -> "HH:MM:SS", hours past 24 preserved.

    GTFS requires that a trip departing 23:50 and arriving 00:20 the next day
    is written 24:20:00, not 00:20:00 -- wrapping it would make the trip appear
    to run backwards in time and most consumers reject or mis-sort it. The
    dataset already uses the same convention for post-midnight departures (see
    parse_clock in blocking.py), so this passes straight through.
    """
    hours, remainder = divmod(max(total_seconds, 0), 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


PROVENANCE_README = """\
DBARS GTFS export -- UNOFFICIAL, DERIVED DATA
=============================================

This feed was generated by DBARS (Demand Based Bus Allocation & Routing
System) from BMTC's published route catalogue. It is NOT an official BMTC
publication and is not endorsed by BMTC.

Every id in this feed is namespaced with the prefix "{prefix}" so that it
cannot be confused with, or collide with, an official BMTC identifier.

WHAT IS EXACT
-------------
  * Route numbers, route names and stop sequences.
  * Stop names, coordinates and stop ids (from BMTC's published stop list).
  * Each trip's DEPARTURE TIME from its first stop.

WHAT IS MODELLED
----------------
  * Every stop time after the first. The source data publishes departures,
    not stop-by-stop timings. Intermediate times are interpolated from
    stop-to-stop geometry using:
        average running speed   {speed} km/h
        dwell per intermediate stop  {dwell} min
        circuity factor         {circuity}
    All such times carry timepoint=0, GTFS's marker for interpolated values.

  * The service calendar. The source data carries no day-of-week
    information, so this feed declares a single service running all seven
    days. THIS OVERSTATES SUNDAY AND HOLIDAY SERVICE. Supplying a real
    calendar is the single highest-value correction to this feed.

  * shapes.txt (when present) is a stop-to-stop polyline, not road
    centreline geometry.

STOPS
-----
BMTC's published stop list contains separate rows for direction-specific
platforms of the same physical stop, typically a few metres apart. DBARS
resolves those to one physical stop, so stops.txt contains one entry per
physical stop actually served, each keeping a real published stop id.

WHAT IS DELIBERATELY NOT IN THIS FEED
-------------------------------------
  * Depot pull-out and pull-in schedules (names beginning with a depot code
    such as D44-ANP10). These are non-revenue positioning runs that carry no
    passengers, and a journey planner has no way to know that.

  * Services longer than {max_km} km. The source data includes a few genuine
    outstation coach services (Kalaburagi, Yadgiri, Vijayapura) whose length
    makes the city running speed above meaningless.

Both exclusions are counted, and the excluded services named, in the build
report available from the DBARS API at GET /gtfs/feed-info.

Built:   {built_at}
Version: {version}
"""


class GtfsFeedBuilder:
    """Builds a GTFS static feed, streaming, from the in-memory route catalogue.

    Streaming matters: this dataset produces roughly 1.5 million stop_times
    rows. Materialising them in a list before writing costs well over a
    gigabyte and is the difference between a build that runs beside the API
    process and one that gets the container OOM-killed.
    """

    def __init__(
        self,
        routes: list[RouteRecord],
        distance_service: GoogleMapsDistanceService,
        parameters: GtfsParameters | None = None,
    ) -> None:
        self.routes = routes
        self.distance_service = distance_service
        self.parameters = parameters or GtfsParameters()

    # ── resolution ──────────────────────────────────────────────────────────

    def _resolve_route(self, route: RouteRecord, report: GtfsBuildReport) -> _ResolvedRoute | None:
        if self.parameters.exclude_depot_runs and _DEPOT_RUN_RE.match(route.route_number):
            report.dropped_depot_runs += 1
            return None

        departures = sorted(
            minute for minute in (parse_clock(clock) for clock in route.trip_list) if minute is not None
        )
        if not departures:
            report.dropped_no_departures += 1
            return None

        geometry = resolve_route_geometry(
            route, self.distance_service, circuity_factor=self.parameters.circuity_factor
        )
        if geometry.unresolved:
            report.skipped_unresolvable_stops += len(geometry.unresolved)
            report.unresolvable_stop_names.extend(geometry.unresolved[:5])
        records = geometry.records
        if len(records) < self.parameters.min_stops_per_trip:
            report.dropped_too_few_resolvable_stops += 1
            return None

        cumulative = geometry.cumulative_km
        total_km = geometry.total_km
        if total_km <= 0:
            # Every stop resolved to the same place: no geometry to time with.
            report.dropped_unresolved_geometry += 1
            return None
        if self.parameters.max_route_km and total_km > self.parameters.max_route_km:
            report.dropped_too_long += 1
            report.excluded_long_routes.append(
                f"{route.route_number}:{route.direction_id} ({total_km:.0f} km)"
            )
            return None
        if not (MIN_PLAUSIBLE_ROUTE_KM <= total_km <= MAX_PLAUSIBLE_ROUTE_KM):
            report.geometry_suspect_routes.append(f"{route.route_number}:{route.direction_id}")

        return _ResolvedRoute(
            route=route, records=records, cumulative_km=cumulative, departures=departures
        )

    # ── timing model ────────────────────────────────────────────────────────

    def stop_time_seconds(self, resolved: _ResolvedRoute, depart_minute: int) -> list[tuple[int, int]]:
        """(arrival, departure) in seconds after midnight, for every stop.

        Driving time is distributed across segments in proportion to their
        share of the route's distance; dwell is added on arrival at each
        intermediate stop, which makes the total exactly
        driving + dwell x (stops - 2) -- the same figure
        BlockingEngine.running_time_minutes produces, so the published
        timetable and the fleet plan cannot disagree about trip length.
        """
        total_km = resolved.total_km
        driving_seconds = (total_km / self.parameters.average_speed_kmph) * 3600.0
        dwell_seconds = self.parameters.dwell_minutes_per_stop * 60.0
        last_index = len(resolved.records) - 1

        times: list[tuple[int, int]] = []
        clock = float(depart_minute * 60)
        previous_departure = clock
        floor = 0  # enforces monotonicity after rounding
        for index in range(len(resolved.records)):
            if index == 0:
                arrival = clock
            else:
                share = (resolved.cumulative_km[index] - resolved.cumulative_km[index - 1]) / total_km
                arrival = previous_departure + share * driving_seconds
            departure = arrival + (dwell_seconds if 0 < index < last_index else 0.0)

            # Rounding to whole seconds can otherwise emit a stop that arrives
            # before the previous one departed, which validators reject.
            arrival_int = max(int(round(arrival)), floor)
            departure_int = max(int(round(departure)), arrival_int)
            times.append((arrival_int, departure_int))
            floor = departure_int
            previous_departure = departure
        return times

    # ── file writers ────────────────────────────────────────────────────────

    def _trip_id(self, resolved: _ResolvedRoute, depart_minute: int) -> str:
        prefix = self.parameters.feed_prefix
        return (
            f"{prefix}-{_slug(resolved.route.route_number)}"
            f"-{resolved.route.direction_id}-{depart_minute:04d}"
        )

    def _route_id(self, route_number: str) -> str:
        return f"{self.parameters.feed_prefix}-{_slug(route_number)}"

    def _stop_id(self, record: StopRecord) -> str:
        return f"{self.parameters.feed_prefix}-{_slug(record.stop_id)}"

    def _write_csv(self, archive: zipfile.ZipFile, name: str, header: list[str], rows: Iterator[list]) -> int:
        """Stream rows straight into the archive member; never buffer them."""
        written = 0
        with archive.open(name, "w") as raw:
            with io.TextIOWrapper(raw, encoding="utf-8", newline="") as text:
                writer = csv.writer(text)
                writer.writerow(header)
                for row in rows:
                    writer.writerow(row)
                    written += 1
        return written

    # ── build ───────────────────────────────────────────────────────────────

    def build(self, destination: str | Path) -> GtfsBuildReport:
        started = datetime.now(timezone.utc)
        report = GtfsBuildReport(
            built_at=started.isoformat(),
            route_directions_in=len(self.routes),
            assumptions=self.parameters.assumptions,
        )

        resolved_routes: list[_ResolvedRoute] = []
        used_stops: dict[str, StopRecord] = {}
        for route in self.routes:
            resolved = self._resolve_route(route, report)
            if resolved is None:
                continue
            resolved_routes.append(resolved)
            for record in resolved.records:
                used_stops.setdefault(self._stop_id(record), record)

        report.route_directions_kept = len(resolved_routes)
        if not resolved_routes:
            raise ValueError("No route-direction resolved to usable geometry; refusing to build an empty feed.")

        report.dataset_fingerprint = self._fingerprint(resolved_routes)
        report.feed_version = f"{started.strftime('%Y%m%d-%H%M%S')}-{report.dataset_fingerprint[:8]}"

        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        # Build to a temp file in the destination directory and rename at the
        # end: a reader hitting GET /gtfs/static.zip mid-build must never see a
        # half-written archive, and rename within one directory is atomic.
        handle, temp_name = tempfile.mkstemp(dir=destination.parent, suffix=".zip.part")
        os.close(handle)
        temp_path = Path(temp_name)

        try:
            with zipfile.ZipFile(temp_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
                self._write_agency(archive)
                report.stops = self._write_stops(archive, used_stops)
                report.routes = self._write_routes(archive, resolved_routes)
                self._write_calendar(archive, started.date())
                report.trips = self._write_trips(archive, resolved_routes)
                report.stop_times = self._write_stop_times(archive, resolved_routes)
                if self.parameters.include_shapes:
                    report.shapes = self._write_shapes(archive, resolved_routes)
                self._write_feed_info(archive, started.date(), report.feed_version)
                archive.writestr(
                    "README.txt",
                    PROVENANCE_README.format(
                        prefix=self.parameters.feed_prefix,
                        speed=self.parameters.average_speed_kmph,
                        dwell=self.parameters.dwell_minutes_per_stop,
                        circuity=self.parameters.circuity_factor,
                        max_km=self.parameters.max_route_km,
                        built_at=report.built_at,
                        version=report.feed_version,
                    ),
                )
            temp_path.replace(destination)
        except BaseException:
            temp_path.unlink(missing_ok=True)
            raise

        report.output_path = str(destination)
        report.output_bytes = destination.stat().st_size
        report.duration_seconds = round((datetime.now(timezone.utc) - started).total_seconds(), 2)
        logger.info(
            "GTFS feed built: %s routes, %s trips, %s stop_times, %s stops -> %s (%.1f MB) in %.1fs",
            report.routes, report.trips, report.stop_times, report.stops,
            destination, report.output_bytes / 1_048_576, report.duration_seconds,
        )
        return report

    def _fingerprint(self, resolved_routes: list[_ResolvedRoute]) -> str:
        """Identifies the source data a feed was built from, so two feeds can
        be compared without diffing 1.5M rows."""
        digest = hashlib.sha256()
        for resolved in resolved_routes:
            digest.update(resolved.route.key.encode("utf-8"))
            digest.update(str(len(resolved.records)).encode("utf-8"))
            digest.update(str(resolved.departures).encode("utf-8"))
        return digest.hexdigest()

    def _write_agency(self, archive: zipfile.ZipFile) -> None:
        parameters = self.parameters
        self._write_csv(
            archive,
            "agency.txt",
            ["agency_id", "agency_name", "agency_url", "agency_timezone", "agency_lang"],
            iter([[
                parameters.agency_id,
                parameters.agency_name,
                parameters.agency_url,
                parameters.agency_timezone,
                parameters.agency_lang,
            ]]),
        )

    def _write_stops(self, archive: zipfile.ZipFile, used_stops: dict[str, StopRecord]) -> int:
        # Only stops that some trip actually calls at. Emitting the full
        # published stop list would add thousands of stops no trip references,
        # which every validator flags and which tells a consumer nothing.
        # zone_id is deliberately omitted: in the source data it duplicates
        # stop_id, so publishing it would imply a fare-zone structure that does
        # not exist.
        def rows() -> Iterator[list]:
            for stop_id, record in sorted(used_stops.items()):
                yield [stop_id, record.stop_name, f"{record.lat:.6f}", f"{record.lon:.6f}", 0]

        return self._write_csv(
            archive, "stops.txt", ["stop_id", "stop_name", "stop_lat", "stop_lon", "location_type"], rows()
        )

    def _write_routes(self, archive: zipfile.ZipFile, resolved_routes: list[_ResolvedRoute]) -> int:
        # One GTFS route per bus number; the dataset's two direction rows are
        # two sets of trips on it, which is exactly how GTFS models direction.
        seen: dict[str, str] = {}
        for resolved in resolved_routes:
            route_id = self._route_id(resolved.route.route_number)
            seen.setdefault(route_id, resolved.route.full_name or resolved.route.route_number)

        def rows() -> Iterator[list]:
            for route_id, long_name in sorted(seen.items()):
                short_name = route_id[len(self.parameters.feed_prefix) + 1:]
                yield [route_id, self.parameters.agency_id, short_name, long_name, GTFS_ROUTE_TYPE_BUS]

        return self._write_csv(
            archive,
            "routes.txt",
            ["route_id", "agency_id", "route_short_name", "route_long_name", "route_type"],
            rows(),
        )

    def _write_calendar(self, archive: zipfile.ZipFile, start: date) -> None:
        end = start + timedelta(days=self.parameters.calendar_days)
        self._write_csv(
            archive,
            "calendar.txt",
            ["service_id", "monday", "tuesday", "wednesday", "thursday", "friday",
             "saturday", "sunday", "start_date", "end_date"],
            iter([[
                self.parameters.service_id, 1, 1, 1, 1, 1, 1, 1,
                start.strftime("%Y%m%d"), end.strftime("%Y%m%d"),
            ]]),
        )

    def _write_trips(self, archive: zipfile.ZipFile, resolved_routes: list[_ResolvedRoute]) -> int:
        def rows() -> Iterator[list]:
            for resolved in resolved_routes:
                route = resolved.route
                route_id = self._route_id(route.route_number)
                headsign = route.destination or (route.stops[-1] if route.stops else "")
                shape_id = (
                    f"{self.parameters.feed_prefix}-{_slug(resolved.shape_id)}"
                    if self.parameters.include_shapes else ""
                )
                for depart_minute in resolved.departures:
                    yield [
                        route_id,
                        self.parameters.service_id,
                        self._trip_id(resolved, depart_minute),
                        headsign,
                        route.direction_id,
                        shape_id,
                    ]

        return self._write_csv(
            archive,
            "trips.txt",
            ["route_id", "service_id", "trip_id", "trip_headsign", "direction_id", "shape_id"],
            rows(),
        )

    def _write_stop_times(self, archive: zipfile.ZipFile, resolved_routes: list[_ResolvedRoute]) -> int:
        def rows() -> Iterator[list]:
            for resolved in resolved_routes:
                stop_ids = [self._stop_id(record) for record in resolved.records]
                for depart_minute in resolved.departures:
                    trip_id = self._trip_id(resolved, depart_minute)
                    times = self.stop_time_seconds(resolved, depart_minute)
                    for sequence, (stop_id, (arrival, departure)) in enumerate(zip(stop_ids, times)):
                        yield [
                            trip_id,
                            format_gtfs_time(arrival),
                            format_gtfs_time(departure),
                            stop_id,
                            sequence,
                            # timepoint=0: every time here except the first
                            # stop's departure is interpolated. Saying so is
                            # the whole difference between an honest derived
                            # feed and a fabricated one.
                            0,
                            f"{resolved.cumulative_km[sequence]:.3f}",
                        ]

        return self._write_csv(
            archive,
            "stop_times.txt",
            ["trip_id", "arrival_time", "departure_time", "stop_id", "stop_sequence",
             "timepoint", "shape_dist_traveled"],
            rows(),
        )

    def _write_shapes(self, archive: zipfile.ZipFile, resolved_routes: list[_ResolvedRoute]) -> int:
        emitted: set[str] = set()

        def rows() -> Iterator[list]:
            for resolved in resolved_routes:
                shape_id = f"{self.parameters.feed_prefix}-{_slug(resolved.shape_id)}"
                if shape_id in emitted:
                    continue
                emitted.add(shape_id)
                for sequence, record in enumerate(resolved.records):
                    yield [
                        shape_id,
                        f"{record.lat:.6f}",
                        f"{record.lon:.6f}",
                        sequence,
                        f"{resolved.cumulative_km[sequence]:.3f}",
                    ]

        return self._write_csv(
            archive,
            "shapes.txt",
            ["shape_id", "shape_pt_lat", "shape_pt_lon", "shape_pt_sequence", "shape_dist_traveled"],
            rows(),
        )

    def _write_feed_info(self, archive: zipfile.ZipFile, start: date, version: str) -> None:
        end = start + timedelta(days=self.parameters.calendar_days)
        self._write_csv(
            archive,
            "feed_info.txt",
            ["feed_publisher_name", "feed_publisher_url", "feed_lang",
             "feed_start_date", "feed_end_date", "feed_version", "feed_contact_email"],
            iter([[
                self.parameters.feed_publisher_name,
                self.parameters.feed_publisher_url,
                self.parameters.agency_lang,
                start.strftime("%Y%m%d"),
                end.strftime("%Y%m%d"),
                version,
                self.parameters.feed_contact_email,
            ]]),
        )
