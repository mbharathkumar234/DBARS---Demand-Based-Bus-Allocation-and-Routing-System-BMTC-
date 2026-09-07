from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.ai.agents.operations_agent import OperationsAnswer, operations_assistant
from app.ai.models import GroundingConfidence
from app.auth.auth import create_access_token
from app.main import create_app


def ai_auth_headers(role: str = "admin") -> dict:
    """Bearer header for an account with the given role.

    Same pattern as tests/test_blocking_api.py. Defined per-file because a
    `tests` package on sys.path shadows this directory, so `from tests.conftest
    import ...` resolves to the wrong module.
    """
    token = create_access_token(f"uid-{role}", f"{role}@example.com", role, role.title())
    return {"Authorization": f"Bearer {token}"}



@pytest.fixture(scope="module")
def client():
    import app.db.database as db_mod
    db_mod._client = None
    db_mod._initialized = False
    app = create_app()
    with TestClient(app) as test_client:
        from app.ai.tools.routing_tools import set_shared_predictor
        set_shared_predictor(app.state.predictor)
        yield test_client


def test_fleet_plan_query_answers_with_tools() -> None:
    """Verify that 'How many buses are needed?' calls get_fleet_plan and returns real metrics."""
    ans: OperationsAnswer = operations_assistant.answer("How many buses are needed?")
    assert len(ans.tool_records) > 0
    assert ans.tool_records[0].tool_name == "get_fleet_plan"
    assert ans.tool_records[0].status == "success"
    assert "13,850" in ans.operational_summary or "total_buses_scheduled" in ans.key_metrics
    assert ans.confidence == GroundingConfidence.CONFIRMED

    md = ans.to_formatted_markdown()
    assert "### Operational Summary" in md
    assert "### Key Operating Metrics" in md
    assert "### Live DBARS Tool Executions" in md
    assert "### Operational Analysis & Rationale" in md


def test_why_buses_needed_explanation() -> None:
    """Verify that 'Why do we need that many buses?' returns Hungarian bipartite reasoning."""
    ans: OperationsAnswer = operations_assistant.answer("Why do we need that many buses?")
    assert "Hungarian bipartite matching" in ans.operational_reasoning or "deficit function" in ans.operational_reasoning.lower()
    assert len(ans.actionable_recommendations) >= 2


def test_crew_plan_query_answers_with_tools() -> None:
    """Verify that 'How many crew duties are required?' returns crew-to-bus ratio and duty details."""
    ans: OperationsAnswer = operations_assistant.answer("How many crew duties are required and what is the crew-to-bus ratio?")
    assert len(ans.tool_records) > 0
    assert ans.tool_records[0].tool_name == "get_crew_plan"
    assert "crew-to-bus ratio" in ans.operational_summary.lower()
    assert 2.0 <= ans.key_metrics.get("crew_to_bus_ratio", 0.0) <= 3.0


def test_crowding_query_answers_with_tools() -> None:
    """Verify that route crowding queries return crowding status and corridor demand."""
    ans: OperationsAnswer = operations_assistant.answer("Which routes have frequent crowding and what is the status for route 500-D?")
    assert len(ans.tool_records) > 0
    assert ans.tool_records[0].tool_name == "get_crowding_information"
    assert "500-D" in ans.operational_summary
    assert "crowding_status" in ans.key_metrics


def test_service_alerts_query_answers_with_tools() -> None:
    """Verify that service alert queries execute get_service_alerts tool."""
    ans: OperationsAnswer = operations_assistant.answer("What service alerts are active currently?")
    assert len(ans.tool_records) > 0
    assert ans.tool_records[0].tool_name == "get_service_alerts"
    assert "active_alerts_count" in ans.key_metrics


def test_metro_connectivity_query_answers_with_tools() -> None:
    """Verify that metro connectivity queries execute get_metro_information tool."""
    ans: OperationsAnswer = operations_assistant.answer("What metro stations are near Majestic?")
    assert len(ans.tool_records) > 0
    assert ans.tool_records[0].tool_name == "get_metro_information"
    assert ans.key_metrics.get("has_metro_connection") is True


def test_planning_parameter_sensitivity_explanation() -> None:
    """Verify that planning parameter queries explain turnaround and spreadover sensitivity."""
    ans: OperationsAnswer = operations_assistant.answer("What happens if I change a planning parameter?")
    assert "turnaround" in ans.operational_reasoning.lower() or "spreadover" in ans.operational_reasoning.lower()
    assert "minimum_turnaround_time" in ans.key_metrics


def test_operations_chat_api_end_to_end(client: TestClient) -> None:
    """Verify that POST /ai/chat handles operational queries and executes live DBARS tools."""
    response = client.post(
        "/ai/chat",
        headers=ai_auth_headers("commuter"),
        json={
            "query": "How many buses are needed across the network?",
            "retrieval_mode": "operations",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data["tools_called"]) > 0
    assert data["tools_called"][0]["tool_name"] == "get_fleet_plan"
    assert "### Operational Summary" in data["answer"]
    assert "### Live DBARS Tool Executions" in data["answer"]
