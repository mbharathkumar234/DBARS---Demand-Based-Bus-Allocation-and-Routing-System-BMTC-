"""The ingest loop: polls the active feed and keeps the store current."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.core.config import settings
from app.tracking.adapters import build_feed
from app.tracking.base import VehicleFeed
from app.tracking.store import vehicle_store

logger = logging.getLogger("bmtc.tracking.ingest")

# Consecutive failures multiply the wait, up to this ceiling. A dead upstream
# should not be hammered every ten seconds for the life of the process, and a
# feed that recovers should be picked up again without a restart.
MAX_BACKOFF_SECONDS = 300.0


class VehicleIngestService:
    def __init__(self) -> None:
        self.feed: VehicleFeed | None = None
        self._task: asyncio.Task | None = None
        self._stopping = asyncio.Event()
        self.consecutive_failures = 0

    @property
    def active(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self, predictor: Any = None) -> None:
        if self.active:
            return
        try:
            self.feed = build_feed(
                settings.tracking_feed,
                url=settings.tracking_feed_url,
                field_map=settings.tracking_feed_field_map,
                predictor=predictor,
            )
        except ValueError:
            # A misconfigured feed must not take the app down with it: route
            # prediction, the GTFS export and the depot plans have no
            # dependency on vehicle positions at all.
            logger.exception("Vehicle feed not configured; tracking will report itself unavailable")
            self.feed = None
            return

        vehicle_store.stale_after_seconds = settings.avl_stale_seconds
        await self.feed.start()
        self._stopping.clear()
        self._task = asyncio.create_task(self._run())
        logger.info(
            "Vehicle ingest started: feed=%s live=%s poll=%ss",
            self.feed.name, self.feed.is_live, settings.tracking_poll_seconds,
        )

    async def stop(self) -> None:
        self._stopping.set()
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        if self.feed:
            await self.feed.stop()

    async def poll_once(self) -> int:
        """Poll immediately, outside the loop's schedule.

        Covers the gap between process start and the loop's first tick, so the
        first request to /tracking/buses is not answered with an empty fleet.
        Failures are swallowed into the store's error record: a request for
        vehicle positions should return no vehicles, not a 500, when the feed
        upstream is down.
        """
        if self.feed is None:
            return 0
        try:
            observations = await self.feed.poll()
        except Exception as exc:
            vehicle_store.record_error(f"{type(exc).__name__}: {exc}")
            logger.warning("On-demand vehicle poll failed: %s", exc)
            return 0
        if not isinstance(self.feed, _PUSH_TYPES):
            vehicle_store.replace_all(observations)
        return len(observations)

    async def _run(self) -> None:
        assert self.feed is not None
        while not self._stopping.is_set():
            delay = settings.tracking_poll_seconds
            try:
                observations = await self.feed.poll()
                if isinstance(self.feed, _PUSH_TYPES):
                    # Nothing to merge: observations arrive through the ingest
                    # endpoint. Touch nothing, or an empty poll would wipe the
                    # fleet every ten seconds.
                    pass
                else:
                    vehicle_store.replace_all(observations)
                self.consecutive_failures = 0
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.consecutive_failures += 1
                vehicle_store.record_error(f"{type(exc).__name__}: {exc}")
                delay = min(delay * (2 ** self.consecutive_failures), MAX_BACKOFF_SECONDS)
                logger.warning(
                    "Vehicle feed %s poll failed (%s consecutive); retrying in %.0fs: %s",
                    self.feed.name, self.consecutive_failures, delay, exc,
                )
            try:
                await asyncio.wait_for(self._stopping.wait(), timeout=delay)
            except asyncio.TimeoutError:
                continue

    def source_report(self) -> dict[str, Any]:
        """What is actually powering the vehicle map right now.

        This is what GET /tracking/source returns. It used to describe a
        constant; now it is derived from the running feed, so it cannot drift
        from reality and cannot be edited into claiming something it is not.
        """
        if self.feed is None:
            return {
                "feed": None,
                "is_live": False,
                "status": "unconfigured",
                "description": (
                    "No vehicle feed is configured, so there are no vehicle positions. "
                    "Set TRACKING_FEED to simulated, gtfs_rt, http_json or push."
                ),
                **vehicle_store.health(),
            }
        return {
            "feed": self.feed.name,
            "is_live": self.feed.is_live,
            "status": "running" if self.active else "stopped",
            "description": (
                f"Vehicle positions come from the '{self.feed.name}' adapter."
                if self.feed.is_live
                else (
                    "Vehicle positions are produced by a physics simulation, not a BMTC "
                    "vehicle feed. They are not published as GTFS-realtime and must not be "
                    "presented as live tracking."
                )
            ),
            "poll_interval_seconds": settings.tracking_poll_seconds,
            "consecutive_failures": self.consecutive_failures,
            **vehicle_store.health(),
        }


def _push_types() -> tuple[type, ...]:
    from app.tracking.adapters import PushIngestFeed

    return (PushIngestFeed,)


_PUSH_TYPES = _push_types()

vehicle_ingest = VehicleIngestService()
