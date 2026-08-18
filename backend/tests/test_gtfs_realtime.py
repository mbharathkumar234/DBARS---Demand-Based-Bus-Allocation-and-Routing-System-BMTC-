"""Guards for the GTFS-realtime service-alert feed.

The failure this file exists to catch is silent: an alert whose informed_entity
names an id the static feed does not publish is a dangling reference, and
consumers drop the whole alert rather than the bad reference. A depot manager's
disruption report would then simply never reach riders, with nothing anywhere
reporting that it had not.
"""

from __future__ import annotations

from datetime import datetime, timezone

from google.transit import gtfs_realtime_pb2 as gtfs_rt

from app.core.config import settings
from app.gtfs.realtime import build_service_alerts_feed
from app.ml.distance import GoogleMapsDistanceService


def _distance_service() -> GoogleMapsDistanceService:
    return GoogleMapsDistanceService(
        settings.artifact_dir / "google_distance_cache.json",
        api_key="",
        stop_coordinates_path=settings.stop_coordinates_path,
        max_remote_lookups=0,
    )


def _alert(**overrides) -> dict:
    base = {
        "id": "alert-1",
        "title": "Flooding at Silk Board",
        "description": "Southbound services delayed by waterlogging.",
        "severity": "severe",
        "affected_routes": ["500-D"],
        "affected_stops": ["Central Silk Board"],
        "created_at": datetime(2026, 8, 10, 6, 30, tzinfo=timezone.utc),
    }
    base.update(overrides)
    return base


def _build(alerts, *, stop_ids=frozenset(), route_ids=frozenset()):
    return build_service_alerts_feed(
        alerts,
        distance_service=_distance_service(),
        feed_prefix="dbars",
        published_stop_ids=stop_ids,
        published_route_ids=route_ids,
    )


def test_alert_maps_to_a_valid_realtime_entity():
    service = _distance_service()
    record = service.resolve_stop_record("Central Silk Board")
    assert record is not None
    stop_id = f"dbars-{record.stop_id}"

    feed, stats = _build(
        [_alert()], stop_ids=frozenset({stop_id}), route_ids=frozenset({"dbars-500-D"})
    )

    assert feed.header.gtfs_realtime_version == "2.0"
    assert feed.header.incrementality == gtfs_rt.FeedHeader.Incrementality.FULL_DATASET
    assert len(feed.entity) == 1

    alert = feed.entity[0].alert
    assert alert.severity_level == gtfs_rt.Alert.SeverityLevel.SEVERE
    assert alert.header_text.translation[0].text == "Flooding at Silk Board"
    assert {entity.route_id for entity in alert.informed_entity if entity.route_id} == {"dbars-500-D"}
    assert {entity.stop_id for entity in alert.informed_entity if entity.stop_id} == {stop_id}
    assert stats == {"alerts": 1, "routes_matched": 1, "routes_dropped": 0,
                     "stops_matched": 1, "stops_dropped": 0}

    # An active alert must not carry an end time -- inventing one makes
    # consumers expire a live disruption early.
    assert len(alert.active_period) == 1
    assert alert.active_period[0].start == int(_alert()["created_at"].timestamp())
    assert not alert.active_period[0].HasField("end")


def test_unpublished_references_are_dropped_and_counted():
    feed, stats = _build([_alert(affected_routes=["NOT-A-ROUTE"], affected_stops=["Nowhere At All"])])
    assert stats["routes_dropped"] == 1
    assert stats["stops_dropped"] == 1
    assert stats["routes_matched"] == 0
    assert stats["stops_matched"] == 0

    # The alert itself survives with no informed_entity, which GTFS-RT reads as
    # agency-wide. A human reported a real disruption; losing it entirely
    # because we could not resolve a stop name is the worse outcome.
    assert len(feed.entity) == 1
    assert len(feed.entity[0].alert.informed_entity) == 0
    assert feed.entity[0].alert.header_text.translation[0].text


def test_severity_and_unknown_fields_are_honest():
    feed, _ = _build([_alert(severity="info"), _alert(id="a2", severity="moderate"),
                      _alert(id="a3", severity="nonsense")])
    levels = [entity.alert.severity_level for entity in feed.entity]
    assert levels == [
        gtfs_rt.Alert.SeverityLevel.INFO,
        gtfs_rt.Alert.SeverityLevel.WARNING,
        gtfs_rt.Alert.SeverityLevel.UNKNOWN_SEVERITY,
    ]
    # DBARS never collects a cause or an effect from the reporter, so both must
    # stay UNKNOWN rather than being guessed into a plausible-looking value.
    for entity in feed.entity:
        assert entity.alert.cause == gtfs_rt.Alert.Cause.UNKNOWN_CAUSE
        assert entity.alert.effect == gtfs_rt.Alert.Effect.UNKNOWN_EFFECT


def test_feed_round_trips_through_protobuf():
    feed, _ = _build([_alert()], route_ids=frozenset({"dbars-500-D"}))
    payload = feed.SerializeToString()

    decoded = gtfs_rt.FeedMessage()
    decoded.ParseFromString(payload)
    assert len(decoded.entity) == 1
    assert decoded.entity[0].alert.header_text.translation[0].text == "Flooding at Silk Board"


def test_empty_alert_list_produces_a_valid_empty_feed():
    """Distinct from the 503 the endpoint returns when MongoDB is down: this
    is the case where we genuinely know there are no active disruptions."""
    feed, stats = _build([])
    assert len(feed.entity) == 0
    assert feed.header.timestamp > 0
    assert stats["alerts"] == 0
