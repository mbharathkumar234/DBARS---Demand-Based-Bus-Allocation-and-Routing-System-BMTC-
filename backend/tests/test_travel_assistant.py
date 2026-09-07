"""Comprehensive evaluation and verification test suite for Phase 9: Natural-Language Travel Assistant.

Tests:
1. Spelling mistakes tolerance (e.g., 'Majestik', 'Witefeeld', 'Marthahalli', 'Slik Board').
2. Colloquial transit hub resolution (e.g., 'Majestic', 'Silk Board', 'Airport', 'Tin Factory').
3. Incomplete queries triggering proactive clarification rather than hallucination.
4. Multilingual / code-mixed input parsing (Kannada 'inda... ge', Hindi 'se... kaise').
5. Strict rejection of fictional/invalid stops (e.g., 'Hogwarts', 'Narnia', 'Atlantis') with zero manufactured routes.
6. One-transfer journeys detailing intermediate transfer hubs and multi-bus chains.
7. Least-walking transit preference evaluation (prioritizing 0-transfer routes).
8. Corridor bus availability listings from authentic BMTC catalogue data.
9. Grounded recommendation explanations ('Why did you recommend this bus?').
10. End-to-end FastAPI `/ai/chat` travel assistant integration.
"""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from app.ai.agents.travel_agent import TravelAssistant, travel_assistant
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



@pytest.fixture
def client() -> TestClient:
    import app.db.database as db_mod
    db_mod._client = None
    db_mod._initialized = False
    app = create_app()
    return TestClient(app)


def test_spelling_mistakes_tolerance() -> None:
    """Verify that common commuter misspellings resolve to valid BMTC stops and routes."""
    ans = travel_assistant.answer("I need to go from Majestik to Witefeeld.")
    assert ans.route_found is True
    assert ans.confirmation_status == "CONFIRMED"
    assert ans.best_route is not None
    assert "KBS-1K" in str(ans.best_route) or "333" in str(ans.best_route)
    assert len(ans.tools_called) > 0
    assert "search_bus_route" in ans.tools_called


def test_colloquial_transit_hub_resolution() -> None:
    """Verify that colloquial Bangalore transit names resolve to canonical stops."""
    ans = travel_assistant.answer("How do I travel from Silk Board to Marathahalli?")
    assert ans.route_found is True
    assert ans.confirmation_status == "CONFIRMED"
    assert "Central Silk Board" in ans.content
    assert "Marathahalli" in ans.content
    assert "KIA-8E" in ans.content


def test_incomplete_queries_ask_clarification() -> None:
    """Verify that incomplete queries ask for missing origin/destination rather than fabricating."""
    # Missing origin
    ans_dest_only = travel_assistant.answer("How do I reach Whitefield?")
    assert ans_dest_only.route_found is False
    assert ans_dest_only.confirmation_status == "UNKNOWN"
    assert ans_dest_only.clarification_prompt is not None
    assert "starting" in ans_dest_only.content.lower() or "where" in ans_dest_only.content.lower()

    # Missing destination
    ans_orig_only = travel_assistant.answer("I am starting from Majestic.")
    assert ans_orig_only.route_found is False
    assert ans_orig_only.confirmation_status == "UNKNOWN"
    assert ans_orig_only.clarification_prompt is not None
    assert "destination" in ans_orig_only.content.lower() or "where" in ans_orig_only.content.lower()


def test_code_mixed_multilingual_queries() -> None:
    """Verify that code-mixed queries (Kannada, Hindi) correctly extract stops."""
    # Kannada transliterated
    ans_kannada = travel_assistant.answer("Majestic inda Whitefield ge hege hogodu?")
    assert ans_kannada.parameters.origin == "Majestic"
    assert ans_kannada.parameters.destination == "Whitefield"
    assert ans_kannada.route_found is True

    # Hindi transliterated
    ans_hindi = travel_assistant.answer("Silk Board se Marathahalli kaise jaye?")
    assert ans_hindi.parameters.origin == "Silk Board"
    assert ans_hindi.parameters.destination == "Marathahalli"
    assert ans_hindi.route_found is True


def test_adversarial_invalid_stops_rejected() -> None:
    """Verify that fictional/invalid locations are rejected with zero manufactured buses."""
    ans = travel_assistant.answer("How do I travel from Hogwarts to Narnia?")
    assert ans.route_found is False
    assert ans.confirmation_status == "UNKNOWN"
    assert "UNKNOWN" in ans.content or "INVALID" in ans.content
    assert ans.best_route is None
    # Ensure no fabricated bus numbers
    assert "Take " not in ans.content

    ans_partial = travel_assistant.answer("I need to go from Majestic to Atlantis.")
    assert ans_partial.route_found is False
    assert ans_partial.confirmation_status == "UNKNOWN"
    assert "Atlantis" in ans_partial.content


def test_one_transfer_journey_details() -> None:
    """Verify that transfer requests identify connecting buses and transfer points."""
    ans = travel_assistant.answer("How do I reach Marathahalli from Majestic with only one transfer?")
    assert ans.route_found is True
    assert ans.confirmation_status == "CONFIRMED"
    assert ans.parameters.max_transfers == 1
    # Must have route details
    assert ans.best_route is not None
    assert len(ans.alternatives) > 0


def test_least_walking_preference() -> None:
    """Verify that least walking queries prioritize direct services (0 transfer walking)."""
    ans = travel_assistant.answer("Which option involves the least walking from Majestic to Whitefield?")
    assert ans.route_found is True
    assert ans.confirmation_status == "CONFIRMED"
    assert "Least Walking" in ans.content or "0 transfers" in ans.content
    assert ans.parameters.preferences.get("walking") == "low"


def test_corridor_bus_availability_listing() -> None:
    """Verify that commuter questions about available buses list genuine BMTC numbers."""
    ans = travel_assistant.answer("What buses are available from Majestic to Whitefield?")
    assert ans.route_found is True
    assert ans.confirmation_status == "CONFIRMED"
    assert "Available BMTC Buses" in ans.content
    # Known direct buses on this corridor
    assert "KBS-1K" in ans.content or "333" in ans.content


def test_why_recommendation_explanation() -> None:
    """Verify that recommendation explanations cite deterministic criteria."""
    ans = travel_assistant.answer(
        "Why did you recommend this bus from Majestic to Whitefield?"
    )
    assert ans.route_found is True
    assert ans.confirmation_status == "CONFIRMED"
    assert "Recommendation Analysis" in ans.content
    assert "Frequency" in ans.content or "Direct" in ans.content or "Distance" in ans.content


def test_travel_chat_api_end_to_end(client: TestClient) -> None:
    """Verify full end-to-end travel assistant query via POST /ai/chat."""
    response = client.post(
        "/ai/chat",
        headers=ai_auth_headers("commuter"),
        json={
            "query": "I need to travel from Majestic to Whitefield.",
            "retrieval_mode": "auto",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["grounding"] == GroundingConfidence.CONFIRMED.value
    assert len(data["tools_called"]) > 0
    assert data["tools_called"][0]["tool_name"] == "search_bus_route"
    assert "Journey Plan" in data["answer"] or "White Field" in data["answer"]
    assert len(data["sources"]) > 0
