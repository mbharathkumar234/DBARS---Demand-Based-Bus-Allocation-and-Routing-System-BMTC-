"""Public GTFS endpoints.

The static feed is deliberately public and unauthenticated. Its whole purpose
is to be consumed by parties who will never hold a DBARS account -- journey
planners, researchers, BMTC's own vendors -- and an API key requirement would
defeat that. Rebuilding it, which costs real CPU, is admin-only.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, Response
from google.protobuf.json_format import MessageToDict

from app.auth.auth import UserRole, require_role
from app.core.config import settings
from app.db.database import db_available
from app.gtfs.realtime import build_service_alerts_feed, build_vehicle_positions_feed
from app.services.alerts_service import get_active_alerts
from app.services.gtfs_service import gtfs_feed_service
from app.tracking.ingest import vehicle_ingest
from app.tracking.store import vehicle_store

logger = logging.getLogger("bmtc.api.gtfs")

router = APIRouter(prefix="/gtfs", tags=["gtfs"])
realtime_router = APIRouter(prefix="/gtfs-rt", tags=["gtfs-realtime"])


@router.get("/feed-info")
async def feed_info() -> dict:
    """What the currently published feed contains, what it assumed, and what
    it dropped.

    Answers without building, so a monitoring check on this endpoint stays
    cheap and a not-yet-built feed reports itself honestly rather than
    blocking the caller for eleven seconds.
    """
    return gtfs_feed_service.feed_info()


@router.get("/static.zip")
async def static_feed() -> FileResponse:
    """The GTFS static feed. Built on first request if it is not on disk yet.

    Concurrent first requests queue on one build rather than starting several
    (see GtfsFeedService.ensure_built), so the worst case is that a handful of
    callers wait for the same eleven seconds, not that the machine runs four
    builds over one output path.
    """
    try:
        report = await gtfs_feed_service.ensure_built()
    except Exception as exc:
        logger.exception("GTFS feed build failed")
        raise HTTPException(
            status_code=503,
            detail=f"The GTFS feed could not be built: {exc}",
        ) from exc

    path = gtfs_feed_service.feed_path
    if not path.exists():
        raise HTTPException(status_code=503, detail="The GTFS feed is not available.")

    return FileResponse(
        path,
        media_type="application/zip",
        filename=f"bmtc-dbars-gtfs-{report.feed_version}.zip",
        headers={
            # Lets a consumer detect that the underlying dataset changed
            # without downloading and diffing 1.5 million rows.
            "X-Feed-Version": report.feed_version,
            "X-Feed-Provenance": "unofficial; derived from published BMTC data; timings modelled",
            "Cache-Control": "public, max-age=3600",
        },
    )


@router.post("/rebuild")
async def rebuild_feed(user: dict = Depends(require_role(UserRole.ADMIN))) -> dict:
    """Force a full rebuild. Admin only -- this is ~11s of CPU and ~15MB of IO.

    Worth calling after the underlying dataset changes; the feed is otherwise
    a pure function of files on disk and has nothing to invalidate.
    """
    try:
        report = await gtfs_feed_service.ensure_built(force=True)
    except Exception as exc:
        logger.exception("GTFS rebuild requested by %s failed", user.get("sub"))
        raise HTTPException(status_code=500, detail=f"Rebuild failed: {exc}") from exc
    return {"status": "ok", "report": report.as_dict()}


# ── realtime ────────────────────────────────────────────────────────────────

async def _service_alerts_feed(request: Request):
    """Shared by the protobuf and JSON views below.

    Requires MongoDB, and says so rather than returning an empty feed. An
    empty GTFS-RT alerts feed is a positive assertion -- "there are no
    disruptions" -- and publishing that while the alert store is unreachable
    would be stating something we do not know, in the one feed whose entire
    purpose is warning riders that something is wrong.
    """
    if not db_available():
        raise HTTPException(
            status_code=503,
            detail=(
                "Service alerts are stored in MongoDB, which is currently unreachable. "
                "Returning an empty alert feed would assert that there are no "
                "disruptions, which is not known to be true."
            ),
        )

    alerts = await get_active_alerts()
    stop_ids, route_ids = gtfs_feed_service.published_ids()
    if not stop_ids and not route_ids:
        # Alerts reference entities in the static feed; without it there is
        # nothing for a consumer to attach them to.
        await gtfs_feed_service.ensure_built()
        stop_ids, route_ids = gtfs_feed_service.published_ids()

    return build_service_alerts_feed(
        alerts,
        distance_service=request.app.state.predictor.distance_service,
        feed_prefix=settings.gtfs_feed_prefix,
        published_stop_ids=stop_ids,
        published_route_ids=route_ids,
    )


@realtime_router.get("/service-alerts.pb")
async def service_alerts_protobuf(request: Request) -> Response:
    """Active service disruptions as a GTFS-realtime protobuf.

    This is real data, not a simulation: every alert here was created by a
    depot manager or admin through POST /alerts. That is why this feed exists
    and the vehicle-position feed does not.
    """
    feed, stats = await _service_alerts_feed(request)
    return Response(
        content=feed.SerializeToString(),
        media_type="application/x-protobuf",
        headers={
            "X-Alert-Count": str(stats["alerts"]),
            # Surfaced rather than logged: a rising dropped count means alerts
            # are naming routes or stops the static feed does not publish, and
            # those parts of the alert are not reaching riders.
            "X-Informed-Entities-Dropped": str(stats["routes_dropped"] + stats["stops_dropped"]),
            "Cache-Control": "no-cache",
        },
    )


def _vehicle_positions_response(*, allow_simulated: bool) -> Response:
    report = vehicle_ingest.source_report()
    observations = vehicle_store.fresh()

    if not report["is_live"] and not allow_simulated:
        raise HTTPException(
            status_code=503,
            detail=(
                "Vehicle positions are currently produced by a simulation, not a BMTC "
                "vehicle feed, and are therefore not published as GTFS-realtime. "
                "GTFS-realtime has no way to mark data as simulated, so a consumer "
                "ingesting this feed could not tell. Configure TRACKING_FEED with a real "
                "adapter, or see GET /tracking/source for what is running now."
            ),
        )

    feed = build_vehicle_positions_feed(observations, feed_prefix=settings.gtfs_feed_prefix)
    return Response(
        content=feed.SerializeToString(),
        media_type="application/x-protobuf",
        headers={
            "X-Vehicle-Count": str(len(observations)),
            "X-Feed-Source": str(report["feed"]),
            "X-Feed-Is-Live": "true" if report["is_live"] else "false",
            "Cache-Control": "no-cache",
        },
    )


@realtime_router.get("/vehicle-positions.pb")
async def vehicle_positions_protobuf() -> Response:
    """Live vehicle positions as GTFS-realtime.

    Refuses with 503 while positions come from the simulator. That gate is the
    reason this endpoint took a whole adapter layer to build rather than being
    a five-line wrapper over the existing simulator: the difference between
    this project and one that fakes a government data feed is exactly this
    check.
    """
    return _vehicle_positions_response(allow_simulated=False)


@realtime_router.get("/vehicle-positions.sim.pb")
async def vehicle_positions_simulated() -> Response:
    """The same feed built from simulated positions, for local development.

    On a deliberately different path, and behind GTFS_RT_ALLOW_SIMULATED, so
    that no consumer can be pointed at simulated data by accident -- a wrong
    environment variable alone is not enough to make it happen; someone has to
    have configured this URL on purpose.
    """
    if not settings.gtfs_rt_allow_simulated:
        raise HTTPException(
            status_code=404,
            detail=(
                "Simulated GTFS-realtime output is disabled. Set GTFS_RT_ALLOW_SIMULATED=true "
                "to enable it for local development."
            ),
        )
    return _vehicle_positions_response(allow_simulated=True)


@realtime_router.get("/service-alerts.json")
async def service_alerts_json(request: Request) -> dict:
    """The same feed as JSON.

    Protobuf is opaque to anyone without a decoder, which makes a broken
    realtime feed unusually annoying to diagnose. This is the same message
    built by the same code path, so it cannot drift from the binary version.
    """
    feed, stats = await _service_alerts_feed(request)
    return {
        "status": "ok",
        "stats": stats,
        "feed": MessageToDict(feed, preserving_proto_field_name=True),
    }
