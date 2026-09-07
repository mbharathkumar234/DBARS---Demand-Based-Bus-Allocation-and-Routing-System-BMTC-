"""Comprehensive verification test suite for Phase 13: Grounding and Source Verification Engine.

Verifies:
1. Citation alignment: valid file paths are verified; phantom citations without provenance are filtered out.
2. Authentic bus route claims (e.g. '335E', 'KIA-8') verified against live catalog / tool output.
3. Fabricated bus route claims (e.g. '999-Z') detected and downgraded to UNKNOWN.
4. Authentic code symbol claims (e.g. 'BMTCBusPredictor', 'predict') verified against AST index.
5. Fabricated symbol claims (e.g. 'quantum_teleport_fare_engine') detected and downgraded.
6. Fabricated API endpoint claims (e.g. 'POST /api/v1/warp_travel') detected and flagged.
7. Unsupported technology assertions (e.g. claiming DBARS uses PostgreSQL) detected and flagged.
8. Grounded negative claims (stating that a component does not exist) correctly accepted as grounded.
9. End-to-end integration via FastAPI /ai/chat.
"""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from app.ai.models import Citation, GroundingConfidence, ToolExecutionRecord
from app.ai.security.grounding_verifier import grounding_verifier
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


def test_citation_alignment_filters_phantom_citations() -> None:
    """Verify that citations to real files are accepted, while phantom citations are rejected."""
    citations = [
        # Valid citation to real file
        Citation(
            source_type="code",
            title="predictor.py",
            path="backend/app/ml/predictor.py",
            start_line=1,
            end_line=50,
            snippet="class BMTCBusPredictor:",
        ),
        # Valid tool citation
        Citation(
            source_type="dbars_tool",
            title="search_bus_route",
            snippet="Bus route found",
        ),
        # Valid system citation
        Citation(
            source_type="system",
            title="DBARS Grounding Engine",
            snippet="Adversarial check passed",
        ),
        # PHANTOM citation 1: non-existent file path
        Citation(
            source_type="code",
            title="portal.py",
            path="backend/app/magic/quantum_portal.py",
            start_line=10,
            end_line=20,
        ),
        # PHANTOM citation 2: empty path
        Citation(
            source_type="code",
            title="empty.py",
            path="",
        ),
        # PHANTOM citation 3: inverted invalid line numbers
        Citation(
            source_type="code",
            title="invalid_lines.py",
            path="backend/app/ml/predictor.py",
            start_line=500,
            end_line=100,
        ),
    ]

    verified, rejected = grounding_verifier.verify_citations(citations)

    assert len(verified) == 3
    assert len(rejected) == 3

    verified_titles = [c.title for c in verified]
    assert "predictor.py" in verified_titles
    assert "search_bus_route" in verified_titles
    assert "DBARS Grounding Engine" in verified_titles

    rejected_titles = [c.title for c in rejected]
    assert "portal.py" in rejected_titles
    assert "empty.py" in rejected_titles
    assert "invalid_lines.py" in rejected_titles


def test_authentic_bus_route_claim_verified() -> None:
    """Verify that claims referencing real BMTC bus routes are marked as verified."""
    answer = "Take bus `KBS-1K` from Kempegowda Bus Station directly to White Field Post Office."
    res = grounding_verifier.verify_answer_claims(answer=answer)

    assert res.is_fully_grounded is True
    assert res.grounding_confidence == GroundingConfidence.CONFIRMED
    assert any("KBS-1K" in claim for claim in res.verified_claims)
    assert len(res.ungrounded_claims) == 0


def test_fabricated_bus_route_claim_detected_and_downgraded() -> None:
    """Verify that claims inventing fictional bus routes are detected and downgraded to UNKNOWN."""
    answer = "You can board bus `999-Z` from Kempegowda Bus Station to Electronic City."
    res = grounding_verifier.verify_answer_claims(answer=answer)

    assert res.is_fully_grounded is False
    assert res.grounding_confidence == GroundingConfidence.UNKNOWN
    assert any("999-Z" in claim for claim in res.ungrounded_claims)
    assert "Grounding Verification Warning" in res.sanitized_answer


def test_authentic_symbol_claim_verified() -> None:
    """Verify that references to authentic codebase classes/methods are confirmed."""
    answer = "The route recommendation logic is handled by `BMTCBusPredictor` using `predict()`."
    res = grounding_verifier.verify_answer_claims(answer=answer)

    assert res.is_fully_grounded is True
    assert res.grounding_confidence == GroundingConfidence.CONFIRMED
    assert any("BMTCBusPredictor" in claim or "predict" in claim for claim in res.verified_claims)
    assert len(res.ungrounded_claims) == 0


def test_fabricated_symbol_claim_detected_and_downgraded() -> None:
    """Verify that references to non-existent functions are detected and flagged."""
    answer = "The ticket discount is computed by `quantum_teleport_fare_engine()` in the core engine."
    res = grounding_verifier.verify_answer_claims(answer=answer)

    assert res.is_fully_grounded is False
    assert res.grounding_confidence == GroundingConfidence.UNKNOWN
    assert any("quantum_teleport_fare_engine" in claim for claim in res.ungrounded_claims)


def test_fabricated_api_endpoint_detected() -> None:
    """Verify that claims inventing non-existent API endpoints are flagged."""
    answer = "To calculate faster routes, submit a request to `POST /api/v1/warp_travel`."
    res = grounding_verifier.verify_answer_claims(answer=answer)

    assert res.is_fully_grounded is False
    assert res.grounding_confidence == GroundingConfidence.UNKNOWN
    assert any("POST /api/v1/warp_travel" in claim for claim in res.ungrounded_claims)


def test_unsupported_technology_assertion_detected() -> None:
    """Verify that asserting DBARS uses unsupported technology (e.g. PostgreSQL) is flagged."""
    answer = "DBARS uses PostgreSQL for storing commuter accounts and vehicle waybills."
    res = grounding_verifier.verify_answer_claims(answer=answer)

    assert res.is_fully_grounded is False
    assert res.grounding_confidence == GroundingConfidence.UNKNOWN
    assert any("postgresql" in claim.lower() for claim in res.ungrounded_claims)


def test_negative_verification_claim_accepted() -> None:
    """Verify that statements confirming a component does NOT exist are accepted as grounded."""
    answer = (
        "PostgreSQL is not used in DBARS. The platform uses MongoDB via Motor for document persistence."
    )
    res = grounding_verifier.verify_answer_claims(answer=answer)

    assert res.is_fully_grounded is True
    assert res.grounding_confidence == GroundingConfidence.CONFIRMED
    assert len(res.ungrounded_claims) == 0


def test_end_to_end_api_grounding_verification(client: TestClient) -> None:
    """End-to-end API test verifying that legitimate queries return CONFIRMED with verified citations."""
    resp = client.post(
        "/ai/chat",
        headers=ai_auth_headers("commuter"),
        json={
            "query": "Where is BMTCBusPredictor implemented in the codebase?",
            "retrieval_mode": "code",
            "include_sources": True,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["grounding"] == GroundingConfidence.CONFIRMED.value
    assert len(data["sources"]) > 0

    # Ensure all citations returned by the API have real existing files
    from pathlib import Path
    for source in data["sources"]:
        if source["source_type"] in ["code", "documentation"]:
            assert source["path"] is not None
            p = Path(source["path"])
            exists = (
                p.exists() or
                (Path("backend") / p).exists() or
                (Path("..") / p).exists() or
                (Path(source["path"].replace("backend/", "", 1))).exists()
            )
            assert exists, f"File {source['path']} not found from cwd {Path.cwd()}"
