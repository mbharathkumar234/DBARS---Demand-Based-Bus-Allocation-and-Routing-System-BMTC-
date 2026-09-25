"""Retrieval benchmark: does the evidence handed to the answer model contain the answer?

The headline metric is ``evidence@k``: a case passes only when one of the top-k
citations comes from the expected file AND its snippet -- the exact text the
answer model receives -- contains the expected fact. Retrieving the right file
is not enough; "what is smart auto" retrieved AIAssistantModal.tsx and still
failed, because the snippet was cut off before the definition.

Cases are split into ``dev`` (used while tuning retrieval) and ``test`` (held
out, only run for before/after reporting). Every expected fact is re-checked
against the source file on each run, so an edit that moves or removes it fails
the benchmark loudly instead of silently turning a case into a false negative.

Run:  python -m app.ai.evaluation.retrieval_benchmark [--split dev|test|all] [--show-failures]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from app.ai.config import WORKSPACE_DIR
from app.ai.models import Citation, RetrievalMode

DEFENSE_DOC = "docs/DBARS_Project_Defense_and_Codebase_Mastery.docx"
REVISION_DOC = "docs/DBARS_Master_Revision_Sheet.docx"
MODAL = "frontend/src/components/AIAssistantModal.tsx"


@dataclass(frozen=True)
class RetrievalCase:
    id: str
    split: str  # dev | test
    kind: str
    query: str
    # Any one (path, fact) pair satisfies the case.
    expected: Tuple[Tuple[str, str], ...]
    mode: RetrievalMode = RetrievalMode.AUTO


def _c(id: str, split: str, kind: str, query: str, *expected: Tuple[str, str],
       mode: RetrievalMode = RetrievalMode.AUTO) -> RetrievalCase:
    return RetrievalCase(id=id, split=split, kind=kind, query=query, expected=tuple(expected), mode=mode)


CASES: List[RetrievalCase] = [
    # ── dev ──────────────────────────────────────────────────────────────────
    _c("D01", "dev", "ui_label", "what is smart auto", (MODAL, 'label: "Smart Auto"')),
    _c("D02", "dev", "ui_label", "what does the Depot & Fleet Ops mode cover", (MODAL, "Bipartite vehicle blocking")),
    _c("D03", "dev", "ui_label", "what is the Docs & Manuals mode", (MODAL, "Query project design documents")),
    _c("D04", "dev", "frontend_text", "what error does the app show when the backend is unreachable",
       ("frontend/src/lib/apiClient.ts", "Can't reach the server"),
       (DEFENSE_DOC, "Can't reach the server")),
    _c("D05", "dev", "frontend_text", "which demo accounts can I log in with",
       ("frontend/src/pages/Login.tsx", "admin@bmtc.ai / admin123")),
    _c("D06", "dev", "symbol", "where is require_role defined", ("backend/app/auth/auth.py", "def require_role")),
    _c("D07", "dev", "symbol", "what does hash_password do", ("backend/app/auth/auth.py", "def hash_password")),
    _c("D08", "dev", "symbol", "where is load_depots", ("backend/app/ml/blocking.py", "def load_depots")),
    _c("D09", "dev", "symbol", "where is scan_query implemented",
       ("backend/app/ai/security/guardrails.py", "def scan_query")),
    _c("D10", "dev", "paraphrase", "how is the distance between two coordinates computed",
       ("backend/app/ml/blocking.py", "def haversine_km"),
       ("backend/app/services/metro_service.py", "def haversine_km")),
    _c("D11", "dev", "paraphrase", "how long can a driver work before a break is required",
       ("backend/app/ml/crew.py", "max_continuous_driving_minutes")),
    _c("D12", "dev", "paraphrase", "how does the app find transfer options when there is no direct bus",
       ("backend/app/ml/predictor.py", "def _find_transfer_suggestions")),
    _c("D13", "dev", "paraphrase", "how does the AI block prompt injection attempts",
       ("backend/app/ai/security/guardrails.py", "PROMPT_INJECTION_PATTERNS")),
    _c("D14", "dev", "config_value", "what crowding levels can a commuter report",
       ("backend/app/services/crowding_service.py", 'FULL = "full"'),
       ("frontend/src/pages/PredictPage.tsx", '["low", "medium", "high", "full"]')),
    _c("D15", "dev", "config_value", "what grounding confidence values can the AI return",
       ("backend/app/ai/models.py", 'INFERRED = "INFERRED"')),
    _c("D16", "dev", "config_value", "how long is AI session memory kept when idle",
       ("backend/app/ai/memory/session_memory.py", "ttl_seconds: int = 1800")),
    _c("D17", "dev", "config_value", "which LLM model does the AI layer use by default",
       ("backend/app/ai/config.py", '"gemini-3.6-flash"'),
       (REVISION_DOC, "Gemini when a key is set")),
    _c("D18", "dev", "config_value", "what is the maximum spreadover for a crew duty",
       ("backend/app/ml/crew.py", "max_spreadover_minutes: int = 720")),
    _c("D19", "dev", "doc_prose", "what is the Shakti scheme", (DEFENSE_DOC, "free bus travel for women"),
       ("backend/app/core/shakti.py", "free bus travel to women")),
    _c("D20", "dev", "doc_prose", "how do I start the backend server", ("README.md", "uvicorn app.main:app"),
       ("start_backend.ps1", "uvicorn app.main:app"), ("start_backend.bat", "uvicorn app.main:app")),
    _c("D21", "dev", "doc_table", "which MongoDB driver and default connection string does DBARS use",
       (DEFENSE_DOC, "mongodb://localhost:27017")),
    _c("D22", "dev", "doc_table", "what does a conductor do in DBARS", (DEFENSE_DOC, "Sign on to a waybill")),
    _c("D23", "dev", "doc_table", "how big is the dataset in routes buses and stops",
       (REVISION_DOC, "6,737 route-directions")),
    _c("D24", "dev", "file", "what does apiClient.ts do",
       ("frontend/src/lib/apiClient.ts", "Single source of truth for the backend URL")),
    # ── dev, second batch: written after the first held-out measurement, on
    # targets the held-out cases do not use, to tune for generalisation
    # without reading the held-out results.
    _c("E01", "dev", "ui_label", "what passenger types can a conductor sell tickets for",
       ("frontend/src/pages/ConductorDuty.tsx", 'label: "Shakti (free)"')),
    _c("E02", "dev", "ui_label", "what does the Commuter Voting feature do",
       ("frontend/src/i18n/en.json", "Your votes directly influence bus predictions")),
    _c("E03", "dev", "ui_label", "what is the DBARS AI Copilot menu item",
       ("frontend/src/components/Navbar.tsx", "DBARS AI Copilot")),
    _c("E04", "dev", "ui_label", "what languages is the app available in",
       ("frontend/src/i18n/en.json", "Available in English")),
    _c("E05", "dev", "paraphrase", "how does the app check that an SMS webhook really came from Twilio",
       ("backend/app/api/sms.py", "def _expected_twilio_signature"),
       ("backend/app/api/sms.py", "async def _require_valid_twilio_signature")),
    _c("E06", "dev", "paraphrase", "how does the app stop one IP address from flooding the API",
       ("backend/app/core/rate_limit.py", "class RateLimitMiddleware")),
    _c("E07", "dev", "paraphrase", "how are offline ticket sales protected from being counted twice",
       ("frontend/src/lib/offlineQueue.ts", "client-generated UUID"),
       ("backend/app/services/waybill_service.py", "Record a batch of onboard sales, idempotently")),
    _c("E08", "dev", "paraphrase", "how is a bus arrival estimate given a confidence label",
       ("backend/app/api/tracking.py", "with a confidence label")),
    _c("E09", "dev", "paraphrase", "how are stop names turned into map coordinates to draw a route",
       ("backend/app/ml/route_geometry.py", "def resolve_route_geometry"),
       ("backend/app/ml/route_geometry.py", "def resolve_stop_sequence")),
    _c("E10", "dev", "frontend_text", "what happens when no microphone is found during voice search",
       ("frontend/src/components/VoiceButton.tsx", "No microphone found")),
    _c("E11", "dev", "paraphrase", "how does a commuter cast a vote for a route",
       ("backend/app/api/votes.py", "async def create_vote")),
    _c("E12", "dev", "symbol", "where is resolve_stop_sequence",
       ("backend/app/ml/route_geometry.py", "def resolve_stop_sequence")),
    _c("E13", "dev", "symbol", "what does _require_valid_twilio_signature do",
       ("backend/app/api/sms.py", "async def _require_valid_twilio_signature")),
    _c("E14", "dev", "symbol", "where is RateLimitMiddleware", ("backend/app/core/rate_limit.py", "class RateLimitMiddleware")),
    _c("E15", "dev", "config_value", "how many requests per minute are allowed from one IP",
       ("backend/app/core/rate_limit.py", "max_requests_per_minute: int = 120")),
    _c("E16", "dev", "config_value", "what is the maximum deadhead distance in the blocking plan",
       ("backend/app/ml/blocking.py", "max_deadhead_km: float = 5.0")),
    _c("E17", "dev", "config_value", "how many of my votes are listed by default",
       ("backend/app/api/votes.py", "limit: int = Query(20")),
    _c("E18", "dev", "config_value", "what earth radius is used for haversine distances",
       ("backend/app/services/metro_service.py", "radius_km = 6371.0088")),
    _c("E19", "dev", "file", "what does offlineQueue.ts do",
       ("frontend/src/lib/offlineQueue.ts", "Offline queue for onboard ticket sales")),
    _c("E20", "dev", "file", "what is in route_geometry.py", ("backend/app/ml/route_geometry.py", "class RouteGeometry")),
    _c("E21", "dev", "frontend_text", "what does the landing page subtitle say",
       ("frontend/src/i18n/en.json", "Type in your stop and where you want to go")),
    _c("E22", "dev", "frontend_text", "what message is shown when microphone permission is denied",
       ("frontend/src/components/VoiceButton.tsx", "Microphone access was blocked")),
    _c("E23", "dev", "doc_table", "what is the search latency of route prediction", (REVISION_DOC, "median 0.94 s")),
    _c("E24", "dev", "doc_prose", "why were semantic embeddings not adopted",
       (REVISION_DOC, "Reverted to the deterministic provider")),
    # ── test (held out) ──────────────────────────────────────────────────────
    _c("T01", "test", "ui_label", "what is the Commuter Travel tab",
       (MODAL, "Point-to-point transit routes")),
    _c("T02", "test", "ui_label", "what does Code & Architecture mode do", (MODAL, "AST codebase exploration")),
    _c("T03", "test", "ui_label", "what example questions does Smart Auto suggest",
       (MODAL, "How do I reach Whitefield from Majestic?")),
    _c("T04", "test", "frontend_text", "what is the subtitle on the login screen",
       ("frontend/src/i18n/en.json", "Sign in to your DBARS account")),
    _c("T05", "test", "frontend_text", "is there an SOS button in the safety panel",
       ("frontend/src/components/SafetyPanel.tsx", 'DELIBERATELY NOT INCLUDED: any "SOS" button')),
    _c("T06", "test", "frontend_text", "what backend URL does the frontend use by default",
       ("frontend/src/lib/apiClient.ts", "http://localhost:8000")),
    _c("T07", "test", "symbol", "where is create_access_token", ("backend/app/auth/auth.py", "def create_access_token")),
    _c("T08", "test", "symbol", "what does price_ticket do", ("backend/app/services/waybill_service.py", "def price_ticket")),
    _c("T09", "test", "symbol", "where is get_route_crowding",
       ("backend/app/services/crowding_service.py", "async def get_route_crowding")),
    _c("T10", "test", "symbol", "where is block_interlined", ("backend/app/ml/blocking.py", "def block_interlined")),
    _c("T11", "test", "paraphrase", "how is the ticket fare looked up between two stops",
       ("backend/app/core/fares.py", "def get_fare")),
    _c("T12", "test", "paraphrase", "how are user passwords checked at login",
       ("backend/app/auth/auth.py", "def verify_password")),
    _c("T13", "test", "paraphrase", "how are nearby metro stations found for a bus stop",
       ("backend/app/services/metro_service.py", "def find_nearest_stations")),
    _c("T14", "test", "paraphrase", "where is the FastAPI application object created",
       ("backend/app/main.py", "def create_app")),
    _c("T15", "test", "config_value", "what is the minimum break length for crew",
       ("backend/app/ml/crew.py", "min_break_minutes: int = 30")),
    _c("T16", "test", "config_value", "how many conversation turns does the AI remember",
       ("backend/app/ai/memory/session_memory.py", "max_turns: int = 10")),
    _c("T17", "test", "config_value", "what retrieval modes does the AI chat support",
       ("backend/app/ai/models.py", 'HYBRID = "hybrid"')),
    _c("T18", "test", "config_value", "how much paid time does a crew get after the last trip",
       ("backend/app/ml/crew.py", "sign_off_minutes: int = 15")),
    _c("T19", "test", "doc_prose", "why is Shakti travel not free for BMTC", (DEFENSE_DOC, "the state reimburses")),
    _c("T20", "test", "doc_table", "who are commuters in DBARS and what can they do",
       (DEFENSE_DOC, "vote for unserved routes")),
    _c("T21", "test", "doc_table", "how are passwords stored and what security is missing",
       (REVISION_DOC, "PBKDF2-SHA256 passwords")),
    _c("T22", "test", "doc_table", "what is the best_option_rate before and after phase 3",
       (REVISION_DOC, "best_option_rate | 0.57")),
    _c("T23", "test", "file", "what does session_memory.py do",
       ("backend/app/ai/memory/session_memory.py", "Sliding-window history")),
    _c("T24", "test", "paraphrase", "how does the planner compute travel duration along a route",
       ("backend/app/ml/distance.py", "def route_distance")),
]


_WS = re.compile(r"\s+")


def _norm(text: str) -> str:
    text = text.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    return _WS.sub(" ", text).strip().lower()


def _source_text(rel_path: str) -> str:
    path = WORKSPACE_DIR / rel_path
    if path.suffix.lower() == ".docx":
        from app.ai.ingestion.doc_parser import docx_blocks
        return "\n".join(text for _kind, text in docx_blocks(path))
    return path.read_text(encoding="utf-8", errors="replace")


def validate_cases(cases: Sequence[RetrievalCase]) -> List[str]:
    """Every expected fact must still exist in its file; returns problems found."""
    problems: List[str] = []
    cache: Dict[str, str] = {}
    for case in cases:
        for rel_path, fact in case.expected:
            if rel_path not in cache:
                try:
                    cache[rel_path] = _norm(_source_text(rel_path))
                except OSError as exc:
                    problems.append(f"{case.id}: cannot read {rel_path}: {exc}")
                    cache[rel_path] = ""
                    continue
            if _norm(fact) not in cache[rel_path]:
                problems.append(f"{case.id}: {fact!r} no longer appears in {rel_path}")
    return problems


def _matches(citation: Citation, case: RetrievalCase, require_fact: bool) -> bool:
    path = (citation.path or "").replace("\\", "/")
    snippet = _norm(citation.snippet or "")
    if not path:
        return False
    for rel_path, fact in case.expected:
        if path.endswith(rel_path) or rel_path.endswith(path):
            if not require_fact or _norm(fact) in snippet:
                return True
    return False


@dataclass
class CaseResult:
    case: RetrievalCase
    evidence_rank: Optional[int]
    file_rank: Optional[int]
    retrieved: List[str] = field(default_factory=list)


Retrieve = Callable[[str, RetrievalMode, int], List[Citation]]


def default_retrieve(query: str, mode: RetrievalMode, top_k: int) -> List[Citation]:
    from app.ai.rag.hybrid_retriever import hybrid_retriever
    return hybrid_retriever.retrieve_citations(query=query, mode=mode, top_k=top_k)


def run(cases: Sequence[RetrievalCase], retrieve: Retrieve = default_retrieve, top_k: int = 4) -> List[CaseResult]:
    results: List[CaseResult] = []
    for case in cases:
        citations = retrieve(case.query, case.mode, top_k)
        evidence_rank = next((i for i, c in enumerate(citations, 1) if _matches(c, case, True)), None)
        file_rank = next((i for i, c in enumerate(citations, 1) if _matches(c, case, False)), None)
        results.append(CaseResult(
            case=case,
            evidence_rank=evidence_rank,
            file_rank=file_rank,
            retrieved=[f"{c.path}:{c.start_line}-{c.end_line}" for c in citations],
        ))
    return results


def summarize(results: Sequence[CaseResult]) -> Dict[str, object]:
    n = len(results) or 1
    by_kind: Dict[str, List[CaseResult]] = {}
    for r in results:
        by_kind.setdefault(r.case.kind, []).append(r)
    return {
        "cases": len(results),
        "evidence@k": round(sum(r.evidence_rank is not None for r in results) / n, 3),
        "file@k": round(sum(r.file_rank is not None for r in results) / n, 3),
        "evidence_mrr": round(sum(1.0 / r.evidence_rank for r in results if r.evidence_rank) / n, 3),
        "by_kind": {
            kind: f"{sum(r.evidence_rank is not None for r in rs)}/{len(rs)}"
            for kind, rs in sorted(by_kind.items())
        },
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--split", choices=["dev", "test", "all"], default="dev")
    parser.add_argument("--top-k", type=int, default=4)
    parser.add_argument("--show-failures", action="store_true")
    args = parser.parse_args(argv)

    cases = [c for c in CASES if args.split == "all" or c.split == args.split]
    problems = validate_cases(cases)
    if problems:
        print("Benchmark ground truth is out of date:\n  " + "\n  ".join(problems))
        return 2

    # Measure the index the current code would build, not a stale one.
    from app.ai.ingestion.freshness import ensure_indices
    ensure_indices(block_on_stale=True)

    results = run(cases, top_k=args.top_k)
    print(json.dumps(summarize(results), indent=2))
    if args.show_failures:
        for r in results:
            if r.evidence_rank is None:
                where = "right file, fact not in snippet" if r.file_rank else "file not retrieved"
                print(f"FAIL {r.case.id} [{r.case.kind}] {r.case.query!r} -- {where}")
                for item in r.retrieved:
                    print(f"       {item}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
