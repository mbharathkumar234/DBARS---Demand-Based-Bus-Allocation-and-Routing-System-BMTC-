"""Builds and serves the GTFS static feed.

Deliberately independent of MongoDB, exactly like blocking_service.py beside
it: the feed is a pure function of two CSVs that ship with the repo, so
publishing it keeps working when the database is unreachable.

The build takes ~11s and produces ~15MB, which is far too much to do inside a
request. It is built once, cached on disk, and the build report is persisted
next to it so that a restarted process can serve a feed the previous process
built without rebuilding it.
"""

from __future__ import annotations

import asyncio
import csv
import io
import json
import logging
import zipfile
from dataclasses import asdict
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.gtfs.builder import GtfsBuildReport, GtfsFeedBuilder, GtfsParameters
from app.ml.data_loader import load_routes
from app.ml.distance import GoogleMapsDistanceService

logger = logging.getLogger("bmtc.services.gtfs")

FEED_FILENAME = "static.zip"
REPORT_FILENAME = "build_report.json"


def default_parameters() -> GtfsParameters:
    return GtfsParameters(
        feed_prefix=settings.gtfs_feed_prefix,
        feed_publisher_name=settings.gtfs_publisher_name,
        feed_publisher_url=settings.gtfs_publisher_url,
        feed_contact_email=settings.gtfs_contact_email,
    )


def _build_sync(parameters: GtfsParameters, destination: Path) -> GtfsBuildReport:
    """Runs off the event loop -- see GtfsFeedService.ensure_built."""
    distance_service = GoogleMapsDistanceService(
        settings.artifact_dir / "google_distance_cache.json",
        api_key="",              # offline: stop coordinates only, no remote calls
        stop_coordinates_path=settings.stop_coordinates_path,
        max_remote_lookups=0,
    )
    builder = GtfsFeedBuilder(load_routes(settings.dataset_path), distance_service, parameters)
    return builder.build(destination)


class GtfsFeedService:
    def __init__(self) -> None:
        # Serialises builds. Without it, several concurrent first requests
        # would each start an 11-second build over the same output path.
        self._lock = asyncio.Lock()
        self._report: GtfsBuildReport | None = None
        self._published_ids: tuple[frozenset[str], frozenset[str]] | None = None

    @property
    def output_dir(self) -> Path:
        return settings.artifact_dir / "gtfs"

    @property
    def feed_path(self) -> Path:
        return self.output_dir / FEED_FILENAME

    @property
    def report_path(self) -> Path:
        return self.output_dir / REPORT_FILENAME

    def _load_persisted_report(self) -> GtfsBuildReport | None:
        """Adopt a feed a previous process built, if it is still on disk.

        Both files must be present: a report without its zip would advertise a
        feed that 404s, and a zip without its report would be served with no
        provenance, which is the one thing this exporter must never do.
        """
        if not (self.feed_path.exists() and self.report_path.exists()):
            return None
        try:
            payload = json.loads(self.report_path.read_text(encoding="utf-8"))
            report = GtfsBuildReport(**payload)
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            logger.warning("Ignoring unreadable GTFS build report at %s (%s)", self.report_path, exc)
            return None
        report.output_path = str(self.feed_path)
        report.output_bytes = self.feed_path.stat().st_size
        return report

    async def ensure_built(self, *, force: bool = False) -> GtfsBuildReport:
        if not force and self._report is not None:
            return self._report

        async with self._lock:
            # Re-check inside the lock: callers that queued behind a build in
            # progress should take its result, not start another one.
            if not force and self._report is not None:
                return self._report
            if not force:
                persisted = self._load_persisted_report()
                if persisted is not None:
                    logger.info("Adopted existing GTFS feed %s", persisted.feed_version)
                    self._report = persisted
                    return persisted

            parameters = default_parameters()
            report = await asyncio.to_thread(_build_sync, parameters, self.feed_path)
            self._published_ids = None       # the zip changed; re-read on demand
            try:
                self.report_path.write_text(
                    json.dumps(asdict(report), indent=2, default=str), encoding="utf-8"
                )
            except OSError:
                # A feed that was built but whose report could not be written
                # is still a usable feed; the in-memory report serves this
                # process. Do not fail the build over it.
                logger.exception("Could not persist GTFS build report to %s", self.report_path)
            self._report = report
            return report

    def published_ids(self) -> tuple[frozenset[str], frozenset[str]]:
        """(stop_ids, route_ids) actually present in the published feed.

        The realtime alert feed needs these. A GTFS-RT alert that names a
        stop_id or route_id the static feed does not contain is a dangling
        reference, and consumers silently drop the whole alert -- so a
        disruption a depot manager published would just never reach riders.
        Read straight from the built zip so the two feeds cannot disagree.
        """
        if self._published_ids is not None:
            return self._published_ids
        if not self.feed_path.exists():
            return frozenset(), frozenset()

        def column(archive: zipfile.ZipFile, member: str, name: str) -> frozenset[str]:
            with archive.open(member) as handle:
                reader = csv.DictReader(io.TextIOWrapper(handle, encoding="utf-8", newline=""))
                return frozenset(row[name] for row in reader)

        try:
            with zipfile.ZipFile(self.feed_path) as archive:
                self._published_ids = (
                    column(archive, "stops.txt", "stop_id"),
                    column(archive, "routes.txt", "route_id"),
                )
        except (OSError, KeyError, zipfile.BadZipFile):
            logger.exception("Could not read published ids from %s", self.feed_path)
            return frozenset(), frozenset()
        return self._published_ids

    def current_report(self) -> GtfsBuildReport | None:
        """The report without triggering a build -- for endpoints that must
        answer immediately and can honestly say 'not built yet'."""
        if self._report is None:
            self._report = self._load_persisted_report()
        return self._report

    def feed_info(self) -> dict[str, Any]:
        report = self.current_report()
        if report is None:
            return {
                "status": "not_built",
                "note": (
                    "The GTFS feed has not been built yet. It builds automatically at "
                    "startup, or on the first request to GET /gtfs/static.zip; an admin "
                    "can force a rebuild with POST /gtfs/rebuild."
                ),
            }
        available = self.feed_path.exists()
        return {
            "status": "ok" if available else "missing",
            "note": None if available else "Build report found but the feed file is gone; rebuild required.",
            "download_url": "/gtfs/static.zip",
            "report": report.as_dict(),
        }


gtfs_feed_service = GtfsFeedService()
