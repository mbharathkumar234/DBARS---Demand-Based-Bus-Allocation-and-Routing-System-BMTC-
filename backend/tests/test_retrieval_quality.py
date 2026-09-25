"""Retrieval must hand the answer model text that contains the answer.

Asked "what is smart auto", the copilot retrieved the right file and still
answered with nothing, under a CONFIRMED badge. The chunker had folded the
object defining every assistant mode into the `ChatMessage` interface's chunk,
the snippet sent to the model was that chunk's first 350 characters, and
"Smart Auto" sat at character 2083. Confidence was CONFIRMED because some
citation existed. Each test here pins one of those failures.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.ai.ingestion.chunking import MAX_CHUNK_CHARS, split_windows
from app.ai.ingestion.code_parser import PythonCodeParser, TypeScriptCodeParser
from app.ai.models import Citation, GroundingConfidence, RetrievalMode, ToolExecutionRecord
from app.ai.rag.text import analyze_query, best_excerpt, split_identifier, stem, tokenize

REPO = Path(__file__).resolve().parents[2]


# ── Text analysis ───────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "a,b",
    [
        ("computed", "compute"), ("computes", "compute"), ("routes", "routing"),
        ("buses", "bus"), ("passwords", "password"), ("stored", "store"),
        ("crowded", "crowding"), ("calculation", "calculated"), ("maximum", "max"),
    ],
)
def test_word_forms_share_a_term(a: str, b: str) -> None:
    assert stem(a) == stem(b)


def test_identifiers_split_into_words() -> None:
    assert split_identifier("AIAssistantModal") == ["ai", "assistant", "modal"]
    assert split_identifier("route_rank_score") == ["route", "rank", "score"]
    assert {"apiclient", "api", "client"} <= set(tokenize("apiClient"))


def test_question_framing_words_are_not_terms() -> None:
    assert analyze_query("how big is the dataset").terms == ["dataset"]


def test_ui_label_becomes_a_phrase() -> None:
    q = analyze_query("what is smart auto")
    assert q.terms == ["smart", "auto"]
    assert "smart auto" in q.phrases


# ── Chunking ────────────────────────────────────────────────────────────────

def test_typescript_constant_objects_are_their_own_chunks() -> None:
    path = "frontend/src/components/AIAssistantModal.tsx"
    chunks = TypeScriptCodeParser.parse_file(path, (REPO / path).read_text(encoding="utf-8"))
    holding = [c for c in chunks if 'label: "Smart Auto"' in c.content]
    assert holding and all(c.symbol == "MODE_CONFIG" for c in holding)
    assert all(len(c.content) <= MAX_CHUNK_CHARS + 200 for c in chunks)


def test_typescript_preamble_and_async_functions_are_kept() -> None:
    code = (
        "// Backend URL, in one place.\n"
        "import x from 'y';\n\n"
        "export const API_BASE_URL = 'http://localhost:8000';\n\n"
        "export async function apiFetch(path: string) {\n  return fetch(path);\n}\n"
    )
    chunks = TypeScriptCodeParser.parse_file("lib/apiClient.ts", code)
    assert [c.symbol for c in chunks] == ["apiClient.__init__", "API_BASE_URL", "apiFetch"]
    assert chunks[2].type == "function"


def test_python_module_constants_and_class_fields_are_indexed() -> None:
    code = (
        '"""Doc."""\n'
        "import os\n\n"
        "# Lookup used by the router.\n"
        "TABLE = {'a': 1}\n\n\n"
        "class Settings:\n"
        '    """Settings."""\n'
        + "".join(f"    field_{i}: int = {i}\n" for i in range(30))
        + "    limit: int = 720\n\n"
        "    def __init__(self, ttl: int = 1800) -> None:\n"
        "        self.ttl = ttl\n\n"
        "    @property\n"
        "    def doubled(self) -> int:\n"
        "        return self.limit * 2\n"
    )
    chunks = PythonCodeParser.parse_file("pkg/settings.py", code)
    by_symbol = {c.symbol: c for c in chunks}
    assert "# Lookup used by the router." in by_symbol["TABLE"].content
    assert any("limit: int = 720" in c.content for c in chunks if c.symbol == "Settings")
    assert any("ttl: int = 1800" in c.content for c in chunks if c.symbol == "Settings")
    assert "@property" in by_symbol["Settings.doubled"].content


def test_windows_of_a_long_function_carry_its_signature() -> None:
    body = "".join(f"    step_{i} = compute_something_long(argument_{i}, other_{i})\n" for i in range(80))
    chunks = PythonCodeParser.parse_file("m.py", "def plan(a, b):\n" + body)
    assert len(chunks) > 1
    assert chunks[0].signature is None
    assert all(c.signature == "def plan(a, b):" for c in chunks[1:])


def test_split_windows_cover_every_line_with_overlap() -> None:
    lines = [f"line {i} " + "x" * 50 for i in range(200)]
    windows = split_windows(lines)
    covered = set()
    for a, b in windows:
        covered.update(range(a, b + 1))
    assert covered == set(range(200))
    assert all(windows[i + 1][0] <= windows[i][1] for i in range(len(windows) - 1))


def test_docx_tables_are_indexed() -> None:
    from app.ai.ingestion.doc_parser import DocxParser

    rel = "docs/DBARS_Project_Defense_and_Codebase_Mastery.docx"
    chunks = DocxParser.parse_file(rel, REPO / rel)
    assert any("mongodb://localhost:27017" in c.content for c in chunks), "table text missing from the index"
    assert any(" > " in c.section for c in chunks), "chunks lost their heading path"


def test_fixtures_and_doc_build_scripts_are_not_indexed() -> None:
    from app.ai.ingestion.freshness import code_sources, doc_sources

    code = {p.relative_to(REPO).as_posix() for p in code_sources(REPO)}
    docs = {p.relative_to(REPO).as_posix() for p in doc_sources(REPO)}
    assert "backend/app/ai/evaluation/dataset.py" not in code
    assert "backend/app/ai/evaluation/retrieval_benchmark.py" not in code
    assert not any(p.startswith("docs/build/") for p in docs)
    assert not any("node_modules" in p for p in code)


# ── Excerpts ────────────────────────────────────────────────────────────────

def test_excerpt_is_the_part_that_answers() -> None:
    content = "\n".join([f"filler line {i} about nothing in particular" for i in range(60)]
                        + ['  auto: {', '    label: "Smart Auto",', '  },']
                        + [f"more filler {i}" for i in range(40)])
    q = analyze_query("what is smart auto")
    text, first, last = best_excerpt(content, q, {"smart": 5.0, "auto": 2.0}, max_chars=400)
    assert 'label: "Smart Auto"' in text
    assert first <= 61 <= last
    assert len(text) <= 400


# ── End to end over the real index ──────────────────────────────────────────

def test_smart_auto_is_answered_from_its_definition() -> None:
    from app.ai.rag.hybrid_retriever import hybrid_retriever

    citations = hybrid_retriever.retrieve_citations("what is smart auto", RetrievalMode.AUTO, top_k=4)
    top = citations[0]
    assert top.path == "frontend/src/components/AIAssistantModal.tsx"
    assert 'label: "Smart Auto"' in (top.snippet or "")
    assert top.symbol == "MODE_CONFIG"
    assert (top.relevance or 0) >= 0.75
    assert top.start_line <= 92 <= top.end_line


def test_citation_lines_point_at_the_excerpt() -> None:
    from app.ai.rag.hybrid_retriever import hybrid_retriever

    for c in hybrid_retriever.retrieve_citations("where is require_role defined", RetrievalMode.CODE, top_k=3):
        if not c.path or not c.path.endswith(".py") or not c.start_line:
            continue
        lines = (REPO / c.path).read_text(encoding="utf-8").splitlines()
        body = (c.snippet or "").splitlines()
        # A signature line may be prepended to mid-function windows; the rest is verbatim.
        if len(body) > 2 and body[1].strip() == "...":
            body = body[2:]
        assert lines[c.start_line - 1] == body[0]
        assert lines[c.end_line - 1] == body[-1]


@pytest.mark.parametrize("split,floor", [("dev", 0.78), ("test", 0.58)])
def test_retrieval_benchmark_floor(split: str, floor: float) -> None:
    """Regression floor at k=4, a few points below the measured scores.

    Measured on 2026-09-22: dev 0.833 (tuned on, and ground truth widened after
    inspection -- optimistic), held-out test 0.625 (never tuned on; the honest
    estimate). Before this work both splits scored 0.25.
    """
    from app.ai.evaluation.retrieval_benchmark import CASES, run, summarize, validate_cases

    cases = [c for c in CASES if c.split == split]
    assert not validate_cases(cases), "benchmark ground truth no longer matches the source files"
    summary = summarize(run(cases))
    assert summary["evidence@k"] >= floor, summary


# ── Confidence ──────────────────────────────────────────────────────────────

def _cite(relevance: float) -> Citation:
    return Citation(source_type="code", title="x", path="backend/app/main.py", relevance=relevance)


@pytest.mark.parametrize(
    "relevance,expected",
    [
        (0.9, GroundingConfidence.CONFIRMED),
        (0.6, GroundingConfidence.INFERRED),
        (0.3, GroundingConfidence.UNKNOWN),
    ],
)
def test_confidence_follows_evidence_support(relevance: float, expected: GroundingConfidence) -> None:
    from app.ai.agents.orchestrator import LangChainOrchestrator

    assert LangChainOrchestrator._grounding_from_support([_cite(relevance)], []) == expected


def test_a_successful_tool_call_is_confirmed() -> None:
    from app.ai.agents.orchestrator import LangChainOrchestrator

    tool = ToolExecutionRecord(tool_name="get_fleet_plan", status="success")
    assert LangChainOrchestrator._grounding_from_support([], [tool]) == GroundingConfidence.CONFIRMED


@pytest.mark.asyncio
async def test_an_unrelated_question_is_not_confirmed() -> None:
    from app.ai.agents.orchestrator import orchestrator
    from app.ai.models import AIChatRequest

    response = await orchestrator.execute(AIChatRequest(query="how do I bake a chocolate sponge cake"))
    assert response.grounding != GroundingConfidence.CONFIRMED


@pytest.mark.asyncio
async def test_smart_auto_answer_is_grounded_in_its_definition() -> None:
    from app.ai.agents.orchestrator import orchestrator
    from app.ai.models import AIChatRequest

    response = await orchestrator.execute(AIChatRequest(query="what is smart auto"))
    assert response.grounding == GroundingConfidence.CONFIRMED
    assert "Smart Auto" in response.answer
    assert any("AIAssistantModal.tsx" in (s.path or "") for s in response.sources)
    assert response.model_used != "gemini-3.6-flash", "the offline model must not report Gemini's name"
