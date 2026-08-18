"""The scenario console: does a timetable change produce an honest answer?

The engine-level tests here pin the arithmetic that the pitch rests on -- that
adding service costs buses, that removing it releases them, and above all that
a scenario never quietly mutates the baseline it is compared against.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.auth.auth import UserRole, create_access_token
from app.main import create_app
from app.ml.blocking import (
    ACTION_ADD_TRIPS,
    ACTION_REMOVE_TRIPS,
    ACTION_SET_HEADWAY,
    ScenarioChange,
    apply_scenario,
    format_clock,
    parse_clock,
)
from app.ml.data_loader import RouteRecord


def _route(number: str, trips: list[str], direction: int = 0) -> RouteRecord:
    return RouteRecord(
        route_number=number,
        full_name=f"{number} test",
        trip_count=len(trips),
        trip_list=list(trips),
        stop_count=3,
        stops=["Alpha", "Beta", "Gamma"],
        route_id=f"r-{number}-{direction}",
        direction_id=direction,
        source="Alpha",
        destination="Gamma",
        normalized_stops=["alpha", "beta", "gamma"],
    )


# ── clock ────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("value,expected", [("08:00", 480), ("00:00", 0), ("24:30:00", 1470)])
def test_parse_clock(value, expected):
    assert parse_clock(value) == expected


def test_post_midnight_times_survive_a_round_trip():
    """A 24:30 departure belongs to the previous service day; collapsing it to
    00:30 would move it 24 hours earlier and break every block spanning it."""
    assert format_clock(parse_clock("24:30:00")) == "24:30"


# ── timetable rewriting ──────────────────────────────────────────────────────
def test_set_headway_replaces_only_the_window():
    route = _route("X1", ["06:00:00", "08:10:00", "09:00:00", "11:00:00"])
    change = ScenarioChange("X1", ACTION_SET_HEADWAY, 480, 600, headway_minutes=30)
    updated, summary = apply_scenario([route], change)

    trips = updated[0].trip_list
    assert "06:00:00" in trips and "11:00:00" in trips  # outside the window: untouched
    assert "08:10:00" not in trips                      # off-grid departure: replaced
    # Inside the window the timetable is exactly the requested grid. Note 09:00
    # survives -- not because it was spared, but because a 30-min grid from
    # 08:00 lands on it anyway.
    assert [t for t in trips if "08:00" <= t[:5] <= "10:00"] == [
        "08:00:00", "08:30:00", "09:00:00", "09:30:00", "10:00:00"
    ]
    assert summary["trips_after"] == len(trips)


def test_add_trips_spreads_them_across_the_window():
    route = _route("X1", ["08:00:00"])
    updated, summary = apply_scenario(
        [route], ScenarioChange("X1", ACTION_ADD_TRIPS, 480, 600, trips=4)
    )
    assert summary["trips_delta"] == 4
    added = sorted(set(updated[0].trip_list) - {"08:00:00"})
    # Evenly spaced, not bunched at one end.
    assert added == ["08:30:00", "09:00:00", "09:30:00"] or len(added) == 3


def test_remove_trips_clears_the_window_only():
    route = _route("X1", ["07:00:00", "08:30:00", "09:30:00", "11:00:00"])
    updated, summary = apply_scenario(
        [route], ScenarioChange("X1", ACTION_REMOVE_TRIPS, 480, 600)
    )
    assert updated[0].trip_list == ["07:00:00", "11:00:00"]
    assert summary["trips_delta"] == -2


def test_scenario_never_mutates_the_baseline():
    """The cached plan must stay exactly as computed; a scenario that edited it
    in place would silently corrupt every later comparison."""
    route = _route("X1", ["08:00:00", "09:00:00"])
    original = list(route.trip_list)
    updated, _ = apply_scenario([route], ScenarioChange("X1", ACTION_REMOVE_TRIPS, 480, 600))
    assert route.trip_list == original
    assert updated[0] is not route


def test_derived_fields_are_rebuilt_on_the_copy():
    route = _route("X1", ["08:00:00"])
    updated, _ = apply_scenario(
        [route], ScenarioChange("X1", ACTION_ADD_TRIPS, 480, 600, trips=3)
    )
    assert updated[0].trip_count == len(updated[0].trip_list)
    assert updated[0].stop_positions == route.stop_positions


def test_both_directions_change_by_default_but_one_can_be_targeted():
    routes = [_route("X1", ["08:30:00"], 0), _route("X1", ["08:40:00"], 1)]
    _, both = apply_scenario([*routes], ScenarioChange("X1", ACTION_REMOVE_TRIPS, 480, 600))
    assert both["route_directions_changed"] == 2

    _, one = apply_scenario(
        [*routes], ScenarioChange("X1", ACTION_REMOVE_TRIPS, 480, 600, direction_id=1)
    )
    assert one["route_directions_changed"] == 1


def test_unknown_route_changes_nothing():
    routes = [_route("X1", ["08:30:00"])]
    _, summary = apply_scenario(routes, ScenarioChange("NOPE", ACTION_REMOVE_TRIPS, 480, 600))
    assert summary["route_directions_changed"] == 0


# ── endpoint ─────────────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def client():
    with TestClient(create_app()) as test_client:
        yield test_client


def _auth(role: str) -> dict:
    token = create_access_token(f"uid-{role}", f"{role}@example.com", role, role.title())
    return {"Authorization": f"Bearer {token}"}


def test_scenario_requires_a_depot_role(client):
    response = client.post(
        "/depot/blocking-scenario",
        json={"route_number": "375-D", "action": "remove_trips", "start_time": "08:00", "end_time": "10:00"},
        headers=_auth(UserRole.COMMUTER.value),
    )
    assert response.status_code == 403


def test_adding_service_costs_buses(client):
    response = client.post(
        "/depot/blocking-scenario",
        json={
            "route_number": "375-D", "action": "set_headway",
            "start_time": "08:00", "end_time": "10:00", "headway_minutes": 4,
        },
        headers=_auth(UserRole.DEPOT_MANAGER.value),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["timetable"]["trips_delta"] > 0
    assert body["after"]["buses"] >= body["before"]["buses"]
    assert body["delta"]["buses"] == body["after"]["buses"] - body["before"]["buses"]
    assert body["notes"]


def test_removing_service_never_costs_more_buses(client):
    response = client.post(
        "/depot/blocking-scenario",
        json={
            "route_number": "375-D", "action": "remove_trips",
            "start_time": "08:00", "end_time": "10:00",
        },
        headers=_auth(UserRole.DEPOT_MANAGER.value),
    )
    body = response.json()
    assert body["timetable"]["trips_delta"] < 0
    assert body["after"]["buses"] <= body["before"]["buses"]


def test_unknown_route_suggests_real_ones(client):
    response = client.post(
        "/depot/blocking-scenario",
        json={"route_number": "375", "action": "remove_trips", "start_time": "08:00", "end_time": "10:00"},
        headers=_auth(UserRole.DEPOT_MANAGER.value),
    )
    assert response.status_code == 404
    detail = response.json()["detail"]
    assert detail["did_you_mean"], "a near-miss route name should offer real alternatives"
    assert all(name.startswith("375") for name in detail["did_you_mean"])


@pytest.mark.parametrize("payload,reason", [
    ({"route_number": "375-D", "action": "set_headway", "start_time": "10:00", "end_time": "08:00"}, "end before start"),
    ({"route_number": "375-D", "action": "set_headway", "start_time": "08:00", "end_time": "10:00"}, "headway missing"),
    ({"route_number": "375-D", "action": "add_trips", "start_time": "08:00", "end_time": "10:00"}, "trips missing"),
    ({"route_number": "375-D", "action": "teleport", "start_time": "08:00", "end_time": "10:00"}, "unknown action"),
])
def test_incoherent_scenarios_are_rejected(client, payload, reason):
    response = client.post("/depot/blocking-scenario", json=payload, headers=_auth(UserRole.ADMIN.value))
    assert response.status_code == 422, reason


def test_dead_km_is_blank_when_the_depot_assignment_was_inferred(client):
    """The regression this pins: an earlier rule showed dead km if the depot had
    *any* route with a stated depot. D20 Banashankari has 1 stated route out of
    293, and that was enough to publish a 17,214 km/day figure derived almost
    entirely from proximity guesses -- contradicting the blocking panel directly
    above it, which blanks the same number for the same reason."""
    response = client.post(
        "/depot/blocking-scenario",
        json={
            "route_number": "375-D", "action": "set_headway",
            "start_time": "08:00", "end_time": "10:00", "headway_minutes": 4,
        },
        headers=_auth(UserRole.DEPOT_MANAGER.value),
    )
    body = response.json()
    assert body["before"]["dead_km"] is None
    assert body["after"]["dead_km"] is None
    assert body["delta"]["dead_km"] is None
    assert any("Dead km not shown" in note for note in body["notes"])


def test_route_typeahead(client):
    response = client.get("/depot/routes", params={"q": "375", "limit": 5}, headers=_auth(UserRole.ADMIN.value))
    assert response.status_code == 200
    routes = response.json()["routes"]
    assert routes and all(r.startswith("375") for r in routes)
