"""Endpoint guards for the blocking panel.

The point of these is the auth boundary and the no-database promise. The
blocking panel is the one meant to be shown to BMTC, so it must render when
MongoDB is unreachable -- unlike the vote-driven panels beside it, which
correctly report themselves unavailable. If that ever regresses, the demo dies
on a connectivity problem in someone else's building.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api import routes as routes_api
from app.auth.auth import UserRole, create_access_token
from app.main import create_app


@pytest.fixture(scope="module")
def client():
    with TestClient(create_app()) as test_client:
        yield test_client


def _auth(role: str) -> dict:
    token = create_access_token(f"uid-{role}", f"{role}@example.com", role, role.title())
    return {"Authorization": f"Bearer {token}"}


def test_blocking_plan_requires_authentication(client):
    assert client.get("/depot/blocking-plan").status_code in (401, 403)


def test_blocking_plan_rejects_commuters(client):
    response = client.get("/depot/blocking-plan", headers=_auth(UserRole.COMMUTER.value))
    assert response.status_code == 403


def test_blocking_plan_returns_a_coherent_network_summary(client):
    response = client.get("/depot/blocking-plan", headers=_auth(UserRole.DEPOT_MANAGER.value))
    assert response.status_code == 200
    body = response.json()

    net = body["network"]
    # Interlining must release buses, never add them, and can never beat the
    # hard floor -- both would be arithmetically impossible.
    assert net["buses_interlined"] < net["buses_scheduled"]
    assert net["buses_interlined"] >= net["buses_floor"]
    assert net["buses_released"] == net["buses_scheduled"] - net["buses_interlined"]
    assert 4_000 <= net["buses_interlined"] <= 9_000

    # The assumptions must travel with the numbers. A figure shown to BMTC
    # without its assumptions attached is the failure mode this whole panel is
    # built to avoid.
    assert body["assumptions"]["average_speed_kmph"] > 0
    assert body["caveats"]
    assert body["depots"]


def test_blocking_plan_never_invents_dead_km_for_inferred_depots(client):
    """Where the operating depot was guessed by proximity, dead km must be null
    rather than a number that looks authoritative and is not."""
    response = client.get("/depot/blocking-plan", headers=_auth(UserRole.ADMIN.value))
    for depot in response.json()["depots"]:
        for proposal in depot["proposals"]:
            if proposal["depot_source"] != "route_code":
                assert proposal["dead_km"] is None


def test_blocking_plan_scopes_to_one_depot(client):
    headers = _auth(UserRole.DEPOT_MANAGER.value)
    key = client.get("/depot/blocking-plan", headers=headers).json()["depots"][0]["key"]

    response = client.get("/depot/blocking-plan", params={"depot": key}, headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["depot"]["key"] == key
    assert body["depot"]["buses_interlined"] <= body["depot"]["buses_scheduled"]


def test_unknown_depot_is_a_404_not_an_empty_success(client):
    response = client.get(
        "/depot/blocking-plan",
        params={"depot": "D999 Nowhere"},
        headers=_auth(UserRole.ADMIN.value),
    )
    assert response.status_code == 404


def test_blocking_plan_works_without_a_database(client, monkeypatch):
    """The whole reason this endpoint reads CSVs instead of Mongo."""
    import app.db.database as database

    monkeypatch.setattr(database, "db_available", lambda: False)
    response = client.get("/depot/blocking-plan", headers=_auth(UserRole.ADMIN.value))
    assert response.status_code == 200
    assert response.json()["network"]["buses_interlined"] > 0


def test_blocking_decision_is_recorded_against_the_real_user(client):
    routes_api.BLOCKING_DECISIONS.clear()
    response = client.post(
        "/depot/blocking-decision",
        json={
            "depot": "D7 KBS/Subahsh Nagar",
            "route_number": "375-D",
            "decision": "approve",
            "buses_released": 9,
        },
        headers=_auth(UserRole.DEPOT_MANAGER.value),
    )
    assert response.status_code == 200
    decision = response.json()["decision"]
    assert decision["decision"] == "approve"
    assert decision["reviewed_by"] == "uid-depot_manager"
    assert len(routes_api.BLOCKING_DECISIONS) == 1


def test_blocking_decision_rejects_an_invalid_verb(client):
    response = client.post(
        "/depot/blocking-decision",
        json={"depot": "D7", "route_number": "375-D", "decision": "dispatch"},
        headers=_auth(UserRole.DEPOT_MANAGER.value),
    )
    assert response.status_code == 422


def test_blocking_decision_requires_a_depot_role(client):
    response = client.post(
        "/depot/blocking-decision",
        json={"depot": "D7", "route_number": "375-D", "decision": "approve"},
        headers=_auth(UserRole.COMMUTER.value),
    )
    assert response.status_code == 403
