"""Comprehensive test suite for Phase 11: Conversational Memory.

Verifies:
1. SessionMemoryManager sliding window, turn management, and clearing.
2. PII sanitization (phone numbers, emails, credit cards, govt IDs, credentials).
3. Cross-user isolation (zero context or journey leakage across users).
4. Idle TTL automatic pruning and expiration.
5. Multi-turn Travel Assistant context continuity (Turn 1 route search -> Turn 2 least walking -> Turn 3 why recommendation).
6. Cross-user leakage prevention in follow-up queries.
7. End-to-end FastAPI `/ai/chat` and `/ai/session` endpoints with session_id and user_id.
"""

from __future__ import annotations

import time
import pytest
from starlette.testclient import TestClient

from app.ai.agents.travel_agent import travel_assistant
from app.ai.memory.session_memory import SessionMemoryManager, session_memory
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


def _user_headers(user_id: str, role: str = "commuter") -> dict:
    """Bearer header for a specific user id."""
    token = create_access_token(user_id, f"{user_id}@example.com", role, user_id)
    return {"Authorization": f"Bearer {token}"}



@pytest.fixture
def client() -> TestClient:
    import app.db.database as db_mod
    db_mod._client = None
    db_mod._initialized = False
    app = create_app()
    return TestClient(app)


def test_session_memory_crud_and_sliding_window() -> None:
    """Verify basic CRUD and sliding-window bounded history."""
    mem = SessionMemoryManager(max_turns=4, ttl_seconds=300)
    session_id = "test_crud_session"
    user_id = "user_1"

    # Add 6 turns (should keep only last 4)
    for i in range(1, 7):
        role = "user" if i % 2 == 1 else "assistant"
        mem.add_turn(session_id, role, f"Message {i}", user_id=user_id)

    history = mem.get_history(session_id, user_id=user_id)
    assert len(history) == 4
    assert history[0]["content"] == "Message 3"
    assert history[-1]["content"] == "Message 6"

    # Clear session
    cleared = mem.clear_session(session_id, user_id=user_id)
    assert cleared is True
    assert len(mem.get_history(session_id, user_id=user_id)) == 0


def test_pii_sanitization_patterns() -> None:
    """Verify that sensitive commuter PII is stripped prior to storage."""
    mem = SessionMemoryManager()
    session_id = "test_pii_session"

    raw_text = (
        "My email is commuter42@gmail.com and my phone number is +91 9876543210. "
        "Also my card is 4111-2222-3333-4444 and Aadhaar is 1234 5678 9012. "
        "Bearer: secret_token_xyz123."
    )

    mem.add_turn(session_id, "user", raw_text)
    history = mem.get_history(session_id)
    stored_text = history[0]["content"]

    # Verify redaction tokens
    assert "[EMAIL_REDACTED]" in stored_text
    assert "[PHONE_REDACTED]" in stored_text
    assert "[CARD_REDACTED]" in stored_text
    assert "[GOVT_ID_REDACTED]" in stored_text
    assert "[CREDENTIAL_REDACTED]" in stored_text

    # Verify raw sensitive data is NOT present
    assert "commuter42@gmail.com" not in stored_text
    assert "9876543210" not in stored_text
    assert "4111-2222-3333-4444" not in stored_text
    assert "1234 5678 9012" not in stored_text
    assert "secret_token_xyz123" not in stored_text


def test_cross_user_isolation() -> None:
    """Verify that different users with identical or different session IDs are strictly isolated."""
    mem = SessionMemoryManager()
    session_id = "shared_session_name"

    # User A adds turn and sets journey context
    mem.add_turn(session_id, "user", "I need to travel to Majestic", user_id="user_alpha")
    mem.update_journey_context(
        session_id,
        user_id="user_alpha",
        origin="Kempegowda Bus Station",
        destination="White Field Post Office",
    )

    # User B checks history and journey context on same session name
    history_b = mem.get_history(session_id, user_id="user_beta")
    journey_b = mem.get_journey_context(session_id, user_id="user_beta")

    assert len(history_b) == 0
    assert journey_b == {}

    # User A checks their own history and journey context
    history_a = mem.get_history(session_id, user_id="user_alpha")
    journey_a = mem.get_journey_context(session_id, user_id="user_alpha")

    assert len(history_a) == 1
    assert "Majestic" in history_a[0]["content"]
    assert journey_a.get("origin") == "Kempegowda Bus Station"
    assert journey_a.get("destination") == "White Field Post Office"


def test_idle_ttl_session_expiration() -> None:
    """Verify that sessions inactive for longer than TTL are automatically pruned."""
    mem = SessionMemoryManager(ttl_seconds=1)
    mem.add_turn("expiring_session", "user", "Hello world")
    assert mem.active_sessions_count() == 1

    time.sleep(1.1)
    pruned = mem.prune_expired_sessions()
    assert pruned == 1
    assert mem.active_sessions_count() == 0


def test_travel_agent_multiturn_journey_continuity() -> None:
    """Verify multi-turn flow: Turn 1 route -> Turn 2 least walking -> Turn 3 why recommendation."""
    # Turn 1: Initial query
    t1_query = "How do I travel from Majestic to Whitefield?"
    t1_ans = travel_assistant.answer(t1_query)
    assert t1_ans.route_found is True
    assert t1_ans.confirmation_status == "CONFIRMED"

    journey_ctx = {
        "origin": "Kempegowda Bus Station",
        "destination": "White Field Post Office",
        "bus_chain": t1_ans.best_route.get("bus_chain") or t1_ans.best_route.get("bus_number"),
        "last_recommended_route": t1_ans.best_route,
    }
    history = [
        {"role": "user", "content": t1_query},
        {"role": "assistant", "content": t1_ans.content},
    ]

    # Turn 2: Follow-up asking for least walking without repeating stops
    t2_query = "What if I want less walking?"
    t2_ans = travel_assistant.answer(t2_query, history=history, journey_context=journey_ctx)
    assert t2_ans.route_found is True
    assert t2_ans.confirmation_status == "CONFIRMED"
    assert "Least Walking" in t2_ans.content or "Least walking" in t2_ans.content
    assert "Kempegowda Bus Station" in t2_ans.content

    # Turn 3: Follow-up asking why this bus was recommended
    t3_query = "Why did you recommend this bus?"
    t3_ans = travel_assistant.answer(t3_query, history=history, journey_context=journey_ctx)
    assert t3_ans.route_found is True
    assert t3_ans.confirmation_status == "CONFIRMED"
    assert "Why DBARS Recommends" in t3_ans.content
    assert "Kempegowda Bus Station" in t3_ans.content


def test_travel_agent_empty_context_asks_clarification() -> None:
    """Verify that a follow-up query without prior context does not hallucinate and asks for stops."""
    query = "What if I want less walking?"
    ans = travel_assistant.answer(query, history=None, journey_context=None)
    assert ans.route_found is False
    assert ans.confirmation_status == "UNKNOWN"
    assert "starting location and destination" in ans.content


def test_e2e_api_multiturn_conversational_memory(client: TestClient) -> None:
    """End-to-end FastAPI test verifying multi-turn journey context, cross-user isolation, and PII redaction."""
    session_id = "test_api_session_99"
    user_a = "commuter_alpha"
    user_b = "commuter_beta"

    # Turn 1: User A asks for route from Majestic to Whitefield
    resp1 = client.post(
        "/ai/chat",
        headers=_user_headers(user_a),
        json={
            "query": "How do I travel from Majestic to Whitefield?",
            "session_id": session_id,
        },
    )
    assert resp1.status_code == 200
    data1 = resp1.json()
    assert data1["grounding"] == GroundingConfidence.CONFIRMED.value
    assert "Kempegowda Bus Station" in data1["answer"]

    # Check session history endpoint for User A
    hist_resp = client.get(f"/ai/session/{session_id}/history", headers=_user_headers(user_a))
    assert hist_resp.status_code == 200
    hist_data = hist_resp.json()
    assert len(hist_data["turns"]) == 2  # 1 user + 1 assistant
    assert hist_data["journey_context"].get("origin") == "Kempegowda Bus Station"

    # Turn 2: User A asks "Which option involves the least walking?"
    resp2 = client.post(
        "/ai/chat",
        headers=_user_headers(user_a),
        json={
            "query": "Which option involves the least walking?",
            "session_id": session_id,
        },
    )
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert data2["grounding"] == GroundingConfidence.CONFIRMED.value
    assert "walking" in data2["answer"].lower()
    assert "Kempegowda Bus Station" in data2["answer"]

    # Turn 3: User B on the same session_id asks "Which option involves the least walking?"
    # Must NOT access User A's journey context
    resp3 = client.post(
        "/ai/chat",
        headers=_user_headers(user_b),
        json={
            "query": "Which option involves the least walking?",
            "session_id": session_id,
        },
    )
    assert resp3.status_code == 200
    data3 = resp3.json()
    # Should ask User B for starting location and destination (or return UNKNOWN)
    assert "starting location and destination" in data3["answer"].lower() or data3["grounding"] == GroundingConfidence.UNKNOWN.value

    # Turn 4: User with PII in query
    pii_session = "test_pii_sess_01"
    resp_pii = client.post(
        "/ai/chat",
        headers=_user_headers("user_pii"),
        json={
            "query": "My phone is 9876543210 and email test@bmtc.gov.in. How to travel from Silk Board to Marathahalli?",
            "session_id": pii_session,
        },
    )
    assert resp_pii.status_code == 200
    # Inspect history to verify scrubbing
    hist_pii = client.get(f"/ai/session/{pii_session}/history", headers=_user_headers("user_pii"))
    assert hist_pii.status_code == 200
    pii_data = hist_pii.json()
    stored_user_turn = pii_data["turns"][0]["content"]
    assert "[PHONE_REDACTED]" in stored_user_turn
    assert "[EMAIL_REDACTED]" in stored_user_turn
    assert "9876543210" not in stored_user_turn
    assert "test@bmtc.gov.in" not in stored_user_turn

    # Turn 5: Clear session
    clear_resp = client.post(
        "/ai/session/clear",
        headers=_user_headers(user_a),
        json={"session_id": session_id},
    )
    assert clear_resp.status_code == 200
    assert clear_resp.json()["cleared"] is True

    # History should now be empty
    hist_after = client.get(f"/ai/session/{session_id}/history", headers=_user_headers(user_a))
    assert hist_after.status_code == 200
    assert len(hist_after.json()["turns"]) == 0
