"""The codebase assistant must answer from code, not from prose about code.

Asked "how travelling time is calculated and displayed when searched for bus
route between any pair of bus stops", the copilot answered:

    The topic ... is addressed in `README.md`. DBARS implements this logic
    within the `README.md:L1-L60` component.

    4. Execution Flow
    1. Execution enters through `README.md`.
    ...
    7. Uncertainty & Limitations
    Confirmed by authoritative DBARS source code.

Every part of that was wrong, and it was reported as CONFIRMED. Travelling time
is computed in `GoogleMapsDistanceService.route_distance`
(`app/ml/distance.py`), totalled in `_make_transfer_suggestion`
(`app/ml/predictor.py`), and rendered by the frontend.

Three causes:

1. **Retrieval could not reach the code.** The index is lexical, so
   "travelling time" shares no token with `duration_minutes` and README.md,
   en.json and a planning document outranked `distance.py` -- which was in the
   same index all along, 23 chunks of it.
2. **The answer template invented structure.** The fallback branch took
   `citations[0]`, whatever it was, and asserted "Execution enters through X",
   "Processes request data using Y", "Returns structured outputs to the caller
   or API gateway" -- three fixed sentences applied to a markdown file.
3. **Chunk addresses were presented as functions.** `README.md:L1-L60` is a
   line range produced by the generic chunker, listed under "Relevant Functions
   / Classes".
"""

from __future__ import annotations

import re

import pytest

from app.ai.agents.codebase_agent import (
    _is_code_path,
    _is_implementation,
    _is_real_symbol,
    codebase_assistant,
)
from app.ai.rag.hybrid_retriever import expand_query
from app.ai.models import RetrievalMode
from app.ai.rag.hybrid_retriever import hybrid_retriever

TRAVEL_TIME_Q = (
    "how travelling time is calculated and displayed when searched for "
    "bus route between any pair of bus stops"
)


# ── Chunk classification ────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "symbol,is_real",
    [
        ("GoogleMapsDistanceService.route_distance", True),
        ("BMTCBusPredictor._make_transfer_leg", True),
        ("README.md:L1-L60", False),
        ("en.json:L61-L120", False),
        ("accuracy-improvement-plan.md:L61-L120", False),
    ],
)
def test_line_ranges_are_not_symbols(symbol: str, is_real: bool) -> None:
    assert _is_real_symbol(symbol) is is_real


@pytest.mark.parametrize(
    "path,code,impl",
    [
        ("backend/app/ml/distance.py", True, True),
        ("frontend/src/types/api.ts", True, True),
        ("backend/tests/test_accuracy_metrics.py", True, False),
        ("README.md", False, False),
        ("frontend/src/i18n/en.json", False, False),
        ("docs/accuracy-improvement-plan.md", False, False),
    ],
)
def test_code_and_implementation_classification(path: str, code: bool, impl: bool) -> None:
    assert _is_code_path(path) is code
    assert _is_implementation(path) is impl


# ── Retrieval reaches the implementation ────────────────────────────────────

def test_plain_language_expands_to_the_identifiers_the_code_uses() -> None:
    expanded = expand_query(TRAVEL_TIME_Q)
    assert "duration_minutes" in expanded
    assert TRAVEL_TIME_Q in expanded, "the user's own wording must survive"


def test_an_exact_symbol_query_is_left_alone() -> None:
    assert expand_query("where is BMTCBusPredictor defined") == "where is BMTCBusPredictor defined"


def test_retrieval_surfaces_the_file_that_computes_duration() -> None:
    citations = hybrid_retriever.retrieve_citations(
        query=TRAVEL_TIME_Q, mode=RetrievalMode.CODE, top_k=6
    )
    paths = " ".join(str(c.path) for c in citations)
    assert "distance.py" in paths or "predictor.py" in paths, (
        f"neither file that computes travel time was retrieved: {paths}"
    )


# ── The answer itself ───────────────────────────────────────────────────────

def test_the_answer_names_source_code_not_a_readme() -> None:
    answer = codebase_assistant.answer(TRAVEL_TIME_Q)
    direct = answer.direct_answer
    assert re.search(r"`[^`]+\.(py|ts|tsx)`", direct), f"no source file named: {direct}"
    assert "README.md" not in direct


def test_no_answer_lists_a_line_range_as_a_function() -> None:
    answer = codebase_assistant.answer(TRAVEL_TIME_Q)
    for symbol in answer.relevant_symbols:
        assert _is_real_symbol(symbol), f"{symbol!r} is a chunk address, not a function"


def test_execution_flow_is_never_fabricated() -> None:
    """The old template asserted a call path through whatever ranked first."""
    answer = codebase_assistant.answer(TRAVEL_TIME_Q)
    flow = " ".join(answer.execution_flow).lower()
    assert "execution enters through `readme.md`" not in flow
    assert "returns structured outputs to the caller or api gateway" not in flow


@pytest.mark.parametrize(
    "question",
    [
        "how travelling time is calculated",
        "how is distance between two stops calculated",
        "where is stop matching implemented",
        "how does transfer planning work",
        "how does the ranking decide the best bus",
    ],
)
def test_implementation_questions_land_on_implementation_files(question: str) -> None:
    answer = codebase_assistant.answer(question)
    assert re.search(r"`[^`]+\.(py|ts|tsx)`", answer.direct_answer), answer.direct_answer
    assert ":L" not in answer.direct_answer, "a chunk address was quoted as the location"


def test_a_documentation_only_match_is_admitted_rather_than_dressed_up() -> None:
    """When nothing but prose matches, the answer must say so and flag it."""
    from app.ai.models import Citation

    doc_only = [
        Citation(source_type="documentation", title="README.md", path="README.md",
                 symbol="README.md:L1-L60", start_line=1, end_line=60, snippet="..."),
    ]
    direct, _files, syms, flow, _reasoning, uncertainty = codebase_assistant._synthesize_answer(
        query="how travelling time is calculated",
        citations=doc_only,
        source_files=["README.md"],
        symbols=["README.md:L1-L60"],
    )
    assert uncertainty, "a documentation-only answer must carry a limitation"
    assert not flow, "no execution flow can be claimed from documentation alone"
    assert not syms, "no functions can be claimed from documentation alone"
    assert "not the code that implements it" in direct or "documentation" in direct.lower()
