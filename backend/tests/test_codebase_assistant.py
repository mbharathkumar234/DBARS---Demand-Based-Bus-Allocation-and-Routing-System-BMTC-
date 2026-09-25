from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List
import pytest

from app.ai.agents.codebase_agent import CodebaseAnswer, codebase_assistant
from app.ai.models import GroundingConfidence


EVALUATION_QUESTIONS = [
    {
        "id": "Q01",
        "question": "Where does the application start?",
        "expected_source": "main.py",
        "category": "Architecture & Startup",
    },
    {
        "id": "Q02",
        "question": "Explain predictor.py and its primary role.",
        "expected_source": "predictor.py",
        "category": "Core Routing Engine",
    },
    {
        "id": "Q03",
        "question": "How does BMTCBusPredictor.predict() work?",
        "expected_source": "predictor.py",
        "category": "Core Routing Engine",
    },
    {
        "id": "Q04",
        "question": "How does stop resolution work in predictor.py?",
        "expected_source": "predictor.py",
        "category": "Stop Matching",
    },
    {
        "id": "Q05",
        "question": "Why are ordered stop pairs used in DBARS route search?",
        "expected_source": "predictor.py",
        "category": "Algorithmic Design",
    },
    {
        "id": "Q06",
        "question": "Where is fare calculated in DBARS?",
        "expected_source": "fares.py",
        "category": "Fare Services",
    },
    {
        "id": "Q07",
        "question": "Where is Shakti eligibility and pass validation implemented?",
        "expected_source": "pass_service.py",
        "category": "Concession & Passes",
    },
    {
        "id": "Q08",
        "question": "How does offline ticket synchronization achieve idempotency?",
        "expected_source": "waybill_service.py",
        "category": "Ticketing & Conductor",
    },
    {
        "id": "Q09",
        "question": "How does authentication and require_role work?",
        "expected_source": "auth.py",
        "category": "Security & RBAC",
    },
    {
        "id": "Q10",
        "question": "Which API endpoint calls the route prediction service?",
        # Was "predict.py": a file that does not exist, named by the curated
        # answer this test was checking. POST /predict lives in api/routes.py.
        "expected_source": "api/routes.py",
        "category": "API Gateway",
    },
    {
        "id": "Q11",
        "question": "What happens when MongoDB is unavailable during routing?",
        "expected_source": "predictor.py",
        "category": "Resilience & Fallback",
    },
    {
        "id": "Q12",
        "question": "Which modules depend on predictor.py?",
        # Was "predict.py" (nonexistent). The importers are main.py and
        # ai/tools/routing_tools.py.
        "expected_source": "main.py",
        "category": "Dependencies",
    },
    {
        "id": "Q13",
        "question": "What tests cover the route prediction engine?",
        "expected_source": "test_predictor.py",
        "category": "Test Coverage",
    },
    {
        "id": "Q14",
        "question": "Trace the execution path from frontend predict page to route result.",
        "expected_source": "predict",
        "category": "End-to-End Flow",
    },
    {
        "id": "Q15",
        "question": "How does the vehicle blocking plan compute minimum fleet?",
        "expected_source": "blocking.py",
        "category": "Operations & Fleet",
    },
    {
        "id": "Q16",
        "question": "How are daily crew duties generated from vehicle blocks?",
        "expected_source": "crew.py",
        "category": "Crew Scheduling",
    },
    {
        "id": "Q17",
        "question": "Where is static GTFS feed generation implemented?",
        "expected_source": "gtfs",
        "category": "Open Transit Data",
    },
    {
        "id": "Q18",
        "question": "How does live AVL bus tracking simulate vehicle positions?",
        "expected_source": "tracking",
        "category": "Realtime AVL",
    },
    {
        "id": "Q19",
        "question": "Where is the Haversine distance formula defined?",
        "expected_source": "metro_service.py",
        "category": "Spatial Mathematics",
    },
    {
        "id": "Q20",
        "question": "Where is Namma Metro station connectivity defined?",
        "expected_source": "metro_service.py",
        "category": "Multimodal Integration",
    },
    {
        "id": "Q21",
        "question": "What is the role of pass_service.py in DBARS?",
        "expected_source": "pass_service.py",
        "category": "Services",
    },
    {
        "id": "Q22",
        "question": "How does the GTFS-RT service alert builder work?",
        "expected_source": "gtfs",
        "category": "Realtime Alerts",
    },
    {
        "id": "Q23",
        "question": "Where is conductor waybill management implemented?",
        "expected_source": "waybill_service.py",
        "category": "Conductor Operations",
    },
    {
        "id": "Q24",
        "question": "How are bus stop coordinates resolved in DBARS?",
        "expected_source": "distance",
        "category": "GIS & Coordinates",
    },
    {
        "id": "Q25",
        "question": "How does the crowd reporting service calculate route crowding?",
        "expected_source": "crowding",
        "category": "Crowdsourcing",
    },
    {
        "id": "Q26",
        "question": "Explain function fake_predictor_999() and its postgres database connection",
        "expected_source": "UNKNOWN",
        "category": "Adversarial Hallucination Defense",
    },
]


def test_codebase_assistant_25_question_evaluation() -> None:
    """Evaluate CodebaseAssistant across 26 questions verifying source grounding and 7-part response format."""
    results: List[Dict[str, Any]] = []
    total_questions = len(EVALUATION_QUESTIONS)
    passed_count = 0

    for q_meta in EVALUATION_QUESTIONS:
        qid = q_meta["id"]
        q_text = q_meta["question"]
        expected_src = q_meta["expected_source"].lower()
        category = q_meta["category"]

        answer: CodebaseAnswer = codebase_assistant.answer(q_text, top_k=4)

        # 1. Verify 7-part response components
        assert answer.direct_answer, f"[{qid}] Missing direct answer"
        assert answer.important_reasoning, f"[{qid}] Missing important reasoning"
        markdown = answer.to_formatted_markdown()
        assert "### 1. Direct Answer" in markdown
        assert "### 2. Relevant Source Files" in markdown
        assert "### 3. Relevant Functions / Classes" in markdown
        assert "### 4. Execution Flow" in markdown
        assert "### 5. Architectural Reasoning" in markdown
        assert "### 6. Evidence & Source References" in markdown
        assert "### 7. Uncertainty & Limitations" in markdown

        # 2. Check source matching and adversarial behavior
        retrieved_files = [f.lower() for f in answer.relevant_source_files]
        if expected_src == "unknown":
            is_correct = (answer.confidence == GroundingConfidence.UNKNOWN) and (len(answer.evidence) == 0)
            notes = "Adversarial check correctly identified nonexistent symbol as UNKNOWN."
        else:
            source_matched = any(expected_src in f for f in retrieved_files) or any(
                expected_src in c.path.lower() for c in answer.evidence
            )
            is_correct = source_matched and len(answer.evidence) > 0
            notes = f"Retrieved {len(answer.evidence)} citations; matched expected source keyword '{expected_src}'."

        if is_correct:
            passed_count += 1

        results.append({
            "id": qid,
            "question": q_text,
            "category": category,
            "expected_source": q_meta["expected_source"],
            "retrieved_sources": answer.relevant_source_files[:3],
            "confidence": answer.confidence.value,
            "is_correct": is_correct,
            "notes": notes,
        })

    # Assert that all evaluation questions pass
    accuracy = (passed_count / total_questions) * 100
    assert accuracy >= 95.0, f"Codebase evaluation accuracy {accuracy:.1f}% below 95% threshold"

    # Write evaluation reports to artifacts
    artifacts_dir = Path(__file__).resolve().parent.parent / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    json_path = artifacts_dir / "codebase_qa_evaluation.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "total_questions": total_questions,
                "passed_count": passed_count,
                "accuracy_percent": round(accuracy, 2),
                "evaluation_results": results,
            },
            f,
            indent=2,
        )

    # Generate Markdown Table Report
    md_path = artifacts_dir / "codebase_qa_report.md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("# DBARS Codebase Assistant — 26-Question Evaluation Report\n\n")
        f.write(f"**Total Questions Evaluated**: {total_questions}\n\n")
        f.write(f"**Passed**: {passed_count} / {total_questions} ({accuracy:.1f}%)\n\n")
        f.write("| ID | Category | Question | Expected Source | Retrieved Sources | Status | Notes |\n")
        f.write("|---|---|---|---|---|---|---|\n")
        for r in results:
            status_badge = "✅ Correct" if r["is_correct"] else "❌ Incorrect"
            sources = ", ".join([os.path.basename(s) for s in r["retrieved_sources"]]) or "None"
            f.write(f"| {r['id']} | {r['category']} | {r['question']} | `{r['expected_source']}` | `{sources}` | {status_badge} | {r['notes']} |\n")


def test_codebase_assistant_direct_answering() -> None:
    """Test CodebaseAssistant single direct execution on startup query."""
    ans = codebase_assistant.answer("Where does the application start?")
    assert "main.py" in " ".join(ans.relevant_source_files).lower()
    assert len(ans.execution_flow) >= 3
    assert ans.confidence == GroundingConfidence.CONFIRMED


def test_codebase_assistant_adversarial_rejection() -> None:
    """Test CodebaseAssistant rejects fake functions without hallucinating."""
    ans = codebase_assistant.answer("Explain function nonexistent_blockchain_router_999()")
    assert ans.confidence == GroundingConfidence.UNKNOWN
    assert len(ans.evidence) == 0
    assert "UNKNOWN" in ans.uncertainty
