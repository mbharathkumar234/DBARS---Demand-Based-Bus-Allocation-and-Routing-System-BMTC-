"""Regression tests for AI Intelligence Layer access control.

Each test here corresponds to a defect found while auditing the AI layer:

1. The AI layer was an authentication bypass. `GET /depot/blocking-plan`
   correctly returns 401 to an anonymous caller, but asking `POST /ai/chat`
   "what is the minimum fleet requirement?" returned the same depot figures
   with no credential at all.
2. Session history was an IDOR. Both `session_id` and `user_id` came from the
   client, so anyone supplying a matching pair read that user's conversation
   and journey context -- origin and destination included.
3. Observability and evaluation endpoints were anonymous, exposing other users'
   query text, a destructive buffer reset, and an expensive benchmark run.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.ai.security.authorization import AIPrincipal, reset_ai_principal, set_ai_principal
from app.ai.tools.registry import tool_registry
from app.auth.auth import create_access_token
from app.main import create_app


@pytest.fixture(scope="module")
def client():
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client


def _headers(user_id: str, role: str) -> dict:
    token = create_access_token(user_id, f"{user_id}@example.com", role, user_id)
    return {"Authorization": f"Bearer {token}"}


# ── Authentication ──────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "method,path",
    [
        ("post", "/ai/chat"),
        ("post", "/ai/session/clear"),
        ("get", "/ai/session/any-session/history"),
        ("get", "/ai/observability/traces"),
        ("get", "/ai/observability/metrics"),
        ("delete", "/ai/observability/traces"),
        ("post", "/ai/evaluation/run"),
        ("get", "/ai/evaluation/latest"),
    ],
)
def test_ai_endpoints_reject_anonymous_callers(client: TestClient, method: str, path: str) -> None:
    kwargs = {"json": {"query": "hello", "session_id": "s"}} if method == "post" else {}
    resp = getattr(client, method)(path, **kwargs)
    assert resp.status_code == 401, f"{method.upper()} {path} must require authentication"


def test_ai_health_stays_public(client: TestClient) -> None:
    """Parity with GET /health: readiness is not sensitive."""
    assert client.get("/ai/health").status_code == 200


# ── Role enforcement: no side door around require_role() ────────────────────

def test_commuter_cannot_read_depot_fleet_data_through_the_assistant(client: TestClient) -> None:
    resp = client.post(
        "/ai/chat",
        headers=_headers("probe-commuter", "commuter"),
        json={"query": "What is the minimum fleet requirement and how many buses are interlined?"},
    )
    assert resp.status_code == 200
    data = resp.json()

    fleet_calls = [t for t in data["tools_called"] if t["tool_name"] == "get_fleet_plan"]
    assert fleet_calls, "expected the fleet tool to be attempted"
    assert all(t["status"] == "error" for t in fleet_calls)

    # The network-wide bus count must not appear in an unprivileged answer.
    assert "13,850" not in data["answer"] and "13850" not in data["answer"]
    assert "access denied" in data["answer"].lower()


def test_depot_manager_can_read_fleet_data_through_the_assistant(client: TestClient) -> None:
    resp = client.post(
        "/ai/chat",
        headers=_headers("probe-depot", "depot_manager"),
        json={"query": "What is the minimum fleet requirement and how many buses are interlined?"},
    )
    assert resp.status_code == 200
    data = resp.json()
    fleet_calls = [t for t in data["tools_called"] if t["tool_name"] == "get_fleet_plan"]
    assert fleet_calls and all(t["status"] == "success" for t in fleet_calls)


def test_commuter_travel_queries_are_unaffected(client: TestClient) -> None:
    """Role gating must not restrict ordinary commuter journey planning."""
    resp = client.post(
        "/ai/chat",
        headers=_headers("probe-commuter", "commuter"),
        json={"query": "How do I travel from Silk Board to Marathahalli?"},
    )
    assert resp.status_code == 200
    assert "Marathahalli" in resp.json()["answer"]


def test_commuter_is_forbidden_from_observability(client: TestClient) -> None:
    resp = client.get("/ai/observability/traces", headers=_headers("probe-commuter", "commuter"))
    assert resp.status_code == 403


def test_admin_may_read_observability(client: TestClient) -> None:
    resp = client.get("/ai/observability/traces", headers=_headers("probe-admin", "admin"))
    assert resp.status_code == 200


# ── Tool registry fails closed ──────────────────────────────────────────────

def test_restricted_tool_is_denied_without_a_principal() -> None:
    """The chokepoint must fail closed if a call path binds no principal."""
    token = set_ai_principal(None)
    try:
        record = tool_registry.execute_tool("get_fleet_plan")
    finally:
        reset_ai_principal(token)

    assert record.status == "error"
    assert record.output["error"] == "access_denied"


def test_unrestricted_tool_needs_no_principal() -> None:
    token = set_ai_principal(None)
    try:
        record = tool_registry.execute_tool("search_bus_route",
                                            current_stop="Silk Board", destination="Marathahalli")
    finally:
        reset_ai_principal(token)
    assert record.status != "error" or record.output.get("error") != "access_denied"


def test_commuter_principal_denied_crew_plan() -> None:
    token = set_ai_principal(AIPrincipal(user_id="u1", role="commuter"))
    try:
        record = tool_registry.execute_tool("get_crew_plan")
    finally:
        reset_ai_principal(token)
    assert record.status == "error"
    assert "depot_manager" in record.output["message"]


# ── Session isolation (IDOR) ────────────────────────────────────────────────

def test_session_history_is_scoped_to_the_token_holder(client: TestClient) -> None:
    session_id = "idor-probe-session"
    victim = _headers("victim-user", "commuter")
    attacker = _headers("attacker-user", "commuter")

    created = client.post(
        "/ai/chat",
        headers=victim,
        # A spoofed body user_id must be ignored in favour of the token.
        json={"query": "How do I travel from Silk Board to Marathahalli?",
              "session_id": session_id, "user_id": "attacker-user"},
    )
    assert created.status_code == 200

    own = client.get(f"/ai/session/{session_id}/history", headers=victim)
    assert own.status_code == 200
    assert len(own.json()["turns"]) >= 2, "victim should see their own conversation"

    stolen = client.get(f"/ai/session/{session_id}/history", headers=attacker)
    assert stolen.status_code == 200
    assert stolen.json()["turns"] == []
    assert stolen.json()["journey_context"] == {}


def test_session_clear_cannot_target_another_user(client: TestClient) -> None:
    session_id = "clear-probe-session"
    victim = _headers("victim-two", "commuter")

    client.post("/ai/chat", headers=victim,
                json={"query": "How do I travel from Majestic to Whitefield?", "session_id": session_id})

    attacker = _headers("attacker-two", "commuter")
    client.post("/ai/session/clear", headers=attacker,
                json={"session_id": session_id, "user_id": "victim-two"})

    still_there = client.get(f"/ai/session/{session_id}/history", headers=victim)
    assert len(still_there.json()["turns"]) >= 2, "another user's clear must not wipe this session"
