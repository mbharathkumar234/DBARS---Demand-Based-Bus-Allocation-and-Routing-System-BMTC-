"""GTFS-realtime feeds.

Only one feed lives here today, and that is the point: service alerts are the
one realtime signal this project already has as genuine data. A depot manager
creating an alert through POST /alerts is a real human reporting a real
disruption (see services/alerts_service.py), so republishing it as GTFS-RT
adds reach without inventing anything.

Vehicle positions are deliberately absent. GTFS-realtime has no field meaning
"this data is simulated" and a consumer ingesting a VehiclePosition cannot
tell, so publishing the bus simulator's output as GTFS-RT would be
indistinguishable from claiming BMTC's fleet is being tracked. That feed
arrives when a real AVL adapter does.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from google.transit import gtfs_realtime_pb2 as gtfs_rt

from app.ml.distance import GoogleMapsDistanceService

logger = logging.getLogger("bmtc.gtfs.realtime")

GTFS_REALTIME_VERSION = "2.0"

# services/alerts_service.py's AlertSeverity -> GTFS-RT SeverityLevel.
_SEVERITY_MAP = {
    "info": gtfs_rt.Alert.SeverityLevel.INFO,
    "moderate": gtfs_rt.Alert.SeverityLevel.WARNING,
    "severe": gtfs_rt.Alert.SeverityLevel.SEVERE,
}


def _translated(text: str, language: str = "en") -> gtfs_rt.TranslatedString:
    message = gtfs_rt.TranslatedString()
    translation = message.translation.add()
    translation.text = text
    translation.language = language
    return message


def _route_id(route_number: str, prefix: str) -> str:
    return f"{prefix}-{'_'.join(str(route_number).split())}"


def build_service_alerts_feed(
    alerts: list[dict[str, Any]],
    *,
    distance_service: GoogleMapsDistanceService,
    feed_prefix: str,
    published_stop_ids: frozenset[str],
    published_route_ids: frozenset[str],
) -> tuple[gtfs_rt.FeedMessage, dict[str, int]]:
    """Turn active DBARS service alerts into a GTFS-realtime FeedMessage.

    Every informed_entity is checked against the ids the static feed actually
    publishes. An alert naming a stop_id or route_id the static feed does not
    contain is a dangling reference, and consumers routinely drop the entire
    alert rather than part of it -- so an unchecked reference means a real
    disruption a depot manager published silently never reaches riders. The
    counts returned say how many references were dropped, so the failure is
    visible rather than silent.

    An alert whose references are ALL unresolvable is still published, with no
    informed_entity: GTFS-RT treats that as affecting the whole agency, which
    is a fair reading of "we know something is wrong but not precisely where"
    and is better than discarding a human's disruption report.
    """
    feed = gtfs_rt.FeedMessage()
    feed.header.gtfs_realtime_version = GTFS_REALTIME_VERSION
    feed.header.incrementality = gtfs_rt.FeedHeader.Incrementality.FULL_DATASET
    feed.header.timestamp = int(datetime.now(timezone.utc).timestamp())

    stats = {"alerts": 0, "routes_matched": 0, "routes_dropped": 0,
             "stops_matched": 0, "stops_dropped": 0}

    for alert in alerts:
        entity = feed.entity.add()
        entity.id = str(alert.get("id") or alert.get("_id") or f"alert-{stats['alerts']}")
        rt_alert = entity.alert

        for route_number in alert.get("affected_routes") or []:
            route_id = _route_id(route_number, feed_prefix)
            if route_id not in published_route_ids:
                stats["routes_dropped"] += 1
                continue
            rt_alert.informed_entity.add().route_id = route_id
            stats["routes_matched"] += 1

        for stop_name in alert.get("affected_stops") or []:
            record = distance_service.resolve_stop_record(stop_name)
            stop_id = f"{feed_prefix}-{'_'.join(record.stop_id.split())}" if record else None
            if not stop_id or stop_id not in published_stop_ids:
                stats["stops_dropped"] += 1
                continue
            rt_alert.informed_entity.add().stop_id = stop_id
            stats["stops_matched"] += 1

        created_at = alert.get("created_at")
        if created_at:
            period = rt_alert.active_period.add()
            period.start = _epoch(created_at)
            # No `end`: an active alert has no known end time. Inventing one
            # would make consumers expire a live disruption early.

        # cause and effect are left UNKNOWN on purpose -- DBARS collects a
        # title, a description and a severity from the reporter, and nothing
        # that maps to GTFS-RT's cause/effect enumerations. Guessing them
        # would be fabricating structure the reporter never supplied.
        rt_alert.cause = gtfs_rt.Alert.Cause.UNKNOWN_CAUSE
        rt_alert.effect = gtfs_rt.Alert.Effect.UNKNOWN_EFFECT
        rt_alert.severity_level = _SEVERITY_MAP.get(
            str(alert.get("severity", "")).lower(), gtfs_rt.Alert.SeverityLevel.UNKNOWN_SEVERITY
        )
        rt_alert.header_text.CopyFrom(_translated(str(alert.get("title") or "Service disruption")))
        rt_alert.description_text.CopyFrom(_translated(str(alert.get("description") or "")))
        stats["alerts"] += 1

    return feed, stats


def build_vehicle_positions_feed(
    observations: list[Any], *, feed_prefix: str
) -> gtfs_rt.FeedMessage:
    """Vehicle positions as GTFS-realtime.

    Callers MUST check that the active feed is live before publishing this.
    GTFS-realtime has no field meaning "this data is simulated" and a consumer
    ingesting a VehiclePosition cannot tell, so serving the simulator's output
    here would be indistinguishable from claiming BMTC's fleet is tracked.
    See api/gtfs.py, where that check is a hard 503.
    """
    feed = gtfs_rt.FeedMessage()
    feed.header.gtfs_realtime_version = GTFS_REALTIME_VERSION
    feed.header.incrementality = gtfs_rt.FeedHeader.Incrementality.FULL_DATASET
    feed.header.timestamp = int(datetime.now(timezone.utc).timestamp())

    for observation in observations:
        entity = feed.entity.add()
        entity.id = observation.vehicle_id
        vehicle = entity.vehicle
        vehicle.vehicle.id = observation.vehicle_id
        vehicle.position.latitude = observation.lat
        vehicle.position.longitude = observation.lon
        if observation.bearing is not None:
            vehicle.position.bearing = float(observation.bearing)
        if observation.speed_kmph is not None:
            vehicle.position.speed = float(observation.speed_kmph) / 3.6      # GTFS-RT is m/s
        if observation.route_number:
            vehicle.trip.route_id = _route_id(observation.route_number, feed_prefix)
        if observation.direction_id is not None:
            vehicle.trip.direction_id = int(observation.direction_id)
        if observation.trip_id:
            vehicle.trip.trip_id = observation.trip_id
        # The source's observation time, never receipt time -- a consumer uses
        # this to decide whether a position is worth showing, and stamping it
        # on republication would make stale data look permanently fresh.
        vehicle.timestamp = _epoch(observation.recorded_at)

    return feed


def _epoch(value: Any) -> int:
    """Alert timestamps arrive as ISO strings from _serialize_alert, or as
    datetimes straight from Mongo depending on the caller."""
    if isinstance(value, datetime):
        moment = value
    else:
        try:
            moment = datetime.fromisoformat(str(value))
        except ValueError:
            return int(datetime.now(timezone.utc).timestamp())
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return int(moment.timestamp())
