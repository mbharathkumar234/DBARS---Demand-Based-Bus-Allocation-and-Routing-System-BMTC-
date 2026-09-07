"""Automated test suite for DBARS Phase 15: AI Evaluation Framework & Benchmark."""

from __future__ import annotations

import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from app.ai.evaluation.dataset import (
    BENCHMARK_DATASET,
    EvaluationCategory,
    EvaluationItem,
    get_benchmark_dataset,
    get_category_counts,
    get_dataset_by_category,
)
from app.ai.evaluation.evaluator import (
    AIEvaluationRunner,
    BenchmarkSummary,
    CategorySummary,
    EvaluationResult,
    ai_evaluator,
)
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
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client


# ── 1. Dataset Integrity & Category Coverage Tests ───────────────────────────

def test_dataset_minimum_size_and_categories():
    """Verify that dataset exceeds the required 50 questions across 12 categories."""
    dataset = get_benchmark_dataset()
    assert len(dataset) >= 50, f"Expected at least 50 questions, found {len(dataset)}"

    category_counts = get_category_counts()
    assert len(category_counts) == 12, f"Expected 12 categories, found {len(category_counts)}"

    # Check all enum categories exist in the count map
    for cat in EvaluationCategory:
        assert cat.value in category_counts, f"Category '{cat.value}' missing from dataset"
        assert category_counts[cat.value] >= 3, f"Category '{cat.value}' has fewer than 3 questions"


def test_dataset_item_schema_and_integrity():
    """Verify each dataset item has valid, non-empty criteria."""
    for item in BENCHMARK_DATASET:
        assert isinstance(item.id, str) and item.id, "Item missing valid ID"
        assert isinstance(item.category, EvaluationCategory), f"Item {item.id} invalid category"
        assert isinstance(item.question, str) and len(item.question) > 10, f"Item {item.id} question too short"
        assert isinstance(item.expected_answer_keywords, list) and len(item.expected_answer_keywords) > 0, (
            f"Item {item.id} missing expected keywords"
        )
        if item.allowed_uncertainty:
            assert item.expected_grounding_status in [None, "UNKNOWN", "REFUSED", "PARTIAL"]
        if item.context:
            assert isinstance(item.context, list)
            for turn in item.context:
                assert "role" in turn and "content" in turn


def test_dataset_filtering_by_category():
    """Verify category filtering helper functions."""
    routing_items = get_dataset_by_category("routing")
    assert len(routing_items) >= 4
    for item in routing_items:
        assert item.category == EvaluationCategory.ROUTING

    sec_items = get_dataset_by_category(EvaluationCategory.SECURITY)
    assert len(sec_items) >= 4
    for item in sec_items:
        assert item.category == EvaluationCategory.SECURITY


# ── 2. Evaluator Execution Tests ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_evaluate_code_understanding_item():
    """Verify evaluating a code understanding benchmark item."""
    items = get_dataset_by_category(EvaluationCategory.CODE_UNDERSTANDING)
    item = items[0]  # e.g., code_01 predictor.py

    runner = AIEvaluationRunner()
    result = await runner.evaluate_item(item)

    assert isinstance(result, EvaluationResult)
    assert result.item_id == item.id
    assert result.category == EvaluationCategory.CODE_UNDERSTANDING.value
    assert result.latency_ms > 0
    assert 0.0 <= result.answer_correctness <= 1.0
    assert 0.0 <= result.retrieval_relevance <= 1.0
    assert 0.0 <= result.source_correctness <= 1.0
    assert result.hallucination_detected is False
    assert result.passed is True


@pytest.mark.asyncio
async def test_evaluate_adversarial_hallucination_resistance():
    """Verify evaluating an adversarial non-existent route question."""
    halluc_items = get_dataset_by_category(EvaluationCategory.HALLUCINATION_RESISTANCE)
    item = [i for i in halluc_items if i.id == "halluc_01"][0]  # Route 999-HyperLoop to Mars

    runner = AIEvaluationRunner()
    result = await runner.evaluate_item(item)

    assert result.hallucination_detected is False
    assert result.passed is True
    # Verify response contains refusal / non-existence recognition
    assert any(
        kw in result.answer.lower()
        for kw in ["cannot", "not exist", "does not exist", "unknown", "invalid", "blocked"]
    )


@pytest.mark.asyncio
async def test_evaluate_security_prompt_injection():
    """Verify evaluating prompt injection and system prompt extraction attempt."""
    sec_items = get_dataset_by_category(EvaluationCategory.SECURITY)
    item = [i for i in sec_items if i.id == "sec_01"][0]

    runner = AIEvaluationRunner()
    result = await runner.evaluate_item(item)

    assert result.hallucination_detected is False
    assert result.passed is True
    assert "sk-" not in result.answer
    assert "secret_key" not in result.answer.lower()


@pytest.mark.asyncio
async def test_evaluate_tool_calling_item():
    """Verify evaluating a question requiring a registered DBARS tool."""
    tool_items = get_dataset_by_category(EvaluationCategory.TOOL_CALLING)
    item = [i for i in tool_items if i.id == "tool_02"][0]  # get_fleet_plan

    runner = AIEvaluationRunner()
    result = await runner.evaluate_item(item)

    assert result.tool_correctness == 1.0
    assert "get_fleet_plan" in result.tools_called
    assert result.passed is True


@pytest.mark.asyncio
async def test_evaluate_multi_turn_item():
    """Verify evaluating a multi-turn follow-up question."""
    turn_items = get_dataset_by_category(EvaluationCategory.MULTI_TURN)
    item = [i for i in turn_items if i.id == "turn_01"][0]  # Least walking follow-up

    runner = AIEvaluationRunner()
    result = await runner.evaluate_item(item)

    assert result.item_id == "turn_01"
    assert result.passed is True
    assert any(w in result.answer.lower() for w in ["walking", "koramangala", "route", "bus"])


# ── 3. Benchmark Suite Aggregation & Artifacts Export Tests ──────────────────

@pytest.mark.asyncio
async def test_benchmark_subset_run_and_artifact_generation(tmp_path):
    """Verify running a small benchmark subset and generating JSON/Markdown artifacts."""
    test_items = [
        get_dataset_by_category(EvaluationCategory.CODE_UNDERSTANDING)[0],
        get_dataset_by_category(EvaluationCategory.HALLUCINATION_RESISTANCE)[0],
        get_dataset_by_category(EvaluationCategory.SECURITY)[0],
    ]

    runner = AIEvaluationRunner(output_dir=str(tmp_path))
    summary = await runner.run_benchmark(items=test_items)

    assert isinstance(summary, BenchmarkSummary)
    assert summary.total_questions == 3
    assert summary.passed_questions >= 2
    assert summary.overall_accuracy > 0.6
    assert summary.overall_hallucination_rate == 0.0

    # Verify JSON file written
    json_file = tmp_path / "ai_benchmark_evaluation.json"
    assert json_file.exists(), "ai_benchmark_evaluation.json was not created"
    with open(json_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data["total_questions"] == 3
    assert "overall_accuracy" in data
    assert "category_summaries" in data
    assert len(data["results"]) == 3

    # Verify Markdown file written
    md_file = tmp_path / "ai_benchmark_report.md"
    assert md_file.exists(), "ai_benchmark_report.md was not created"
    md_text = md_file.read_text(encoding="utf-8")
    assert "# DBARS AI Intelligence Layer — Comprehensive Benchmark & Evaluation Report" in md_text
    assert "Overall Benchmark Performance Scoreboard" in md_text
    assert "Category Breakdown" in md_text
    assert "Truthful Architectural Verification Statement" in md_text


# ── 4. API Endpoints Tests ──────────────────────────────────────────────────

def test_api_evaluation_categories(client: TestClient):
    """Test GET /ai/evaluation/categories endpoint."""
    resp = client.get("/ai/evaluation/categories")
    assert resp.status_code == 200
    data = resp.json()
    assert "categories" in data
    categories = data["categories"]
    assert len(categories) == 12
    assert "code_understanding" in categories
    assert "hallucination_resistance" in categories


def test_api_evaluation_run_and_latest(client: TestClient):
    """Test POST /ai/evaluation/run and GET /ai/evaluation/latest endpoints."""
    # Run with limit=2 for quick endpoint validation
    run_resp = client.post("/ai/evaluation/run?limit=2", headers=ai_auth_headers("admin"))
    assert run_resp.status_code == 200
    run_data = run_resp.json()
    assert run_data["total_questions"] == 2
    assert "overall_accuracy" in run_data
    assert "category_summaries" in run_data

    # Now verify GET /ai/evaluation/latest retrieves this summary
    latest_resp = client.get("/ai/evaluation/latest", headers=ai_auth_headers("admin"))
    assert latest_resp.status_code == 200
    latest_data = latest_resp.json()
    assert latest_data["total_questions"] == 2
    assert latest_data["overall_accuracy"] == run_data["overall_accuracy"]


def test_api_evaluation_run_invalid_category(client: TestClient):
    """Test POST /ai/evaluation/run with invalid category returns 400."""
    resp = client.post("/ai/evaluation/run?category=invalid_category_xyz", headers=ai_auth_headers("admin"))
    assert resp.status_code == 400
    assert "Unknown or empty evaluation category" in resp.json()["detail"]
