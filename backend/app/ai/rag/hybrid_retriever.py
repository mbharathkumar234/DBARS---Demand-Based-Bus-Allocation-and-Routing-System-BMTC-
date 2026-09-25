from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, Tuple

from app.ai.models import Citation, RetrievalMode
from app.ai.rag.code_retriever import code_retriever
from app.ai.rag.doc_retriever import doc_retriever
from app.ai.rag.lexical_search import LexicalIndex
from app.ai.rag.text import AnalyzedQuery, analyze_query, best_excerpt, term_weights, tokenize

logger = logging.getLogger("bmtc-ai-hybrid-retriever")


class QueryRouter:
    """Intelligently routes natural language queries to CODE, DOCUMENTATION, or HYBRID domains."""

    CODE_PATTERNS = [
        re.compile(r"\b(?:where is|which file|which function|class|def|symbol|endpoint|router|import)\b", re.I),
        re.compile(r"\b(?:require_role|create_app|predict|route_rank_score|hash_password|BMTCBusPredictor)\b", re.I),
        re.compile(r"\b\w+\.(?:py|ts|tsx|json|ini)\b", re.I),
        re.compile(r"/(?:predict|health|routes|metrics|autocomplete|gtfs|tracking)", re.I),
    ]

    DOC_PATTERNS = [
        re.compile(r"\b(?:why does|why do|architecture|defense|design decision|relevance-set|rationale|policy)\b", re.I),
        re.compile(r"\b(?:mongodb|postgresql|ranking methodology|accuracy definition|metric definition)\b", re.I),
        re.compile(r"\b(?:what is the purpose of|explain the concept)\b", re.I),
    ]

    @classmethod
    def route_query(cls, query: str) -> RetrievalMode:
        q = query.strip()
        has_code = any(p.search(q) for p in cls.CODE_PATTERNS)
        has_doc = any(p.search(q) for p in cls.DOC_PATTERNS)
        if has_code and has_doc:
            return RetrievalMode.HYBRID
        if has_code:
            return RetrievalMode.CODE
        if has_doc:
            return RetrievalMode.DOCUMENTATION
        # Ambiguous questions search both indices.
        return RetrievalMode.HYBRID


# Commuters and reviewers ask in plain words; the code names things in
# identifiers. "travelling time" shares no token with `duration_minutes`, so
# asking "how travelling time is calculated" returned README.md, en.json and a
# planning document while distance.py, which actually computes it, sat unranked.
#
# Every identifier below is one that exists in this codebase; the mapping
# bridges vocabulary, it does not invent targets. The synonym entries at the
# end add plain words ("rate limit" for "flooding"), not identifiers.
QUERY_VOCABULARY: Dict[str, str] = {
    "travelling time": "duration_minutes route_distance",
    "travel time": "duration_minutes route_distance",
    "journey time": "duration_minutes route_distance",
    "travel duration": "duration_minutes",
    "how long": "duration_minutes",
    "eta": "duration_minutes estimate_arrival",
    "distance": "distance_km route_distance haversine_km",
    "how far": "distance_km route_distance",
    "fare": "price_ticket fare",
    "ticket price": "price_ticket fare",
    "transfer": "_find_transfer_suggestions transfers",
    "interchange": "_interchange_is_walkable transfers",
    "stop matching": "_resolve_stop_name normalize_text",
    "stop resolution": "_resolve_stop_name normalize_text",
    "crowding": "crowding get_route_crowding",
    "crew": "schedule_crew CrewParameters",
    "blocking": "block_interlined BlockingEngine",
    "fleet": "block_interlined BlockingEngine",
    "ranking": "route_rank_score",
    "recommend": "route_rank_score predict",
    "prediction": "predict BMTCBusPredictor",
    "idle": "ttl ttl_seconds",
    "expire": "ttl ttl_seconds",
    "expiry": "ttl ttl_seconds",
    "expiration": "ttl ttl_seconds",
    "timeout": "ttl timeout",
    "unreachable": "reach server",
    "backend": "server",
    # General software synonyms: the words people use for a mechanism versus
    # the words its code uses.
    "flood": "rate limit throttle",
    "flooding": "rate limit throttle",
    "spam": "rate limit",
    "too many requests": "rate limit",
    "arrival": "eta",
    "arrive": "eta",
    "language": "i18n multilingual locale",
    "languages": "i18n multilingual locale",
    "translation": "i18n locale",
    "sign in": "login",
    "log in": "login",
    "draw": "geometry polyline",
    "slow": "latency",
    "speed": "latency",
}


def _vocabulary_matches(query: str) -> List[Tuple[str, str]]:
    lowered = query.lower()
    return [
        (phrase, ids) for phrase, ids in QUERY_VOCABULARY.items()
        if re.search(rf"\b{re.escape(phrase)}\b", lowered)
    ]


def expand_query(query: str) -> str:
    """Append the identifiers a plain-language question is really about.

    The original wording is kept first so exact-symbol queries are unaffected;
    the expansion only adds terms the lexical index can match against.
    """
    extras = [ids for _, ids in _vocabulary_matches(query)]
    return f"{query} {' '.join(extras)}" if extras else query


def term_alternatives(query: str) -> Dict[str, Set[str]]:
    """Question term -> index terms that also count as covering it.

    "idle" is covered by a chunk that says ``ttl``; without this, coverage
    punished exactly the chunks the vocabulary bridge was added to reach.
    """
    alternatives: Dict[str, Set[str]] = {}
    for phrase, ids in _vocabulary_matches(query):
        bridge = set(tokenize(ids))
        for term in tokenize(phrase):
            alternatives.setdefault(term, set()).update(bridge)
    return alternatives


_TEST_PATH = re.compile(r"(^|/)tests?/|(^|/)test_[^/]*$|_test\.\w+$|\.test\.tsx?$|(^|/)conftest\.py$")


@dataclass
class ScoredChunk:
    meta: Dict[str, Any]
    score: float
    relevance: float
    lexical: LexicalIndex


class HybridRetriever:
    """Candidates from BM25 and dense search, re-ranked on how much of the question each chunk answers.

    Rank fusion alone ordered chunks by agreement between two weak signals,
    so a test file that repeated the query's words outranked the code it
    tested, and a chunk mentioning one rare query term beat a chunk containing
    all of them. The re-ranker scores coverage of the question's terms,
    verbatim phrases, and exact symbol or file hits directly.
    """

    CANDIDATES = 40
    MAX_PER_FILE = 2
    EXCERPT_CHARS = 1000

    WEIGHTS = {
        "coverage": 0.40,
        "bm25": 0.20,
        "dense": 0.15,
        "phrase": 0.25,
        "exact": 0.30,
        "expanded_exact": 0.15,
        "symbol": 0.30,
        "definition": 0.25,
        "file_overview": 0.30,
        "ai_layer": -0.15,
        "tiny": -0.20,
    }

    def __init__(self) -> None:
        self.code_retriever = code_retriever
        self.doc_retriever = doc_retriever
        self._lexical: Dict[str, LexicalIndex] = {}
        self._freshness_checked = False
        self._lock = threading.Lock()

    # ── index lifecycle ─────────────────────────────────────────────────────

    def _ensure_fresh(self) -> None:
        if self._freshness_checked:
            return
        self._freshness_checked = True
        try:
            from app.ai.ingestion.freshness import ensure_indices
            plan = ensure_indices()
            logger.info("AI index status at first use: %s", plan)
        except Exception:
            logger.exception("Index freshness check failed; using indices as they are")

    def reload(self, kind: str) -> None:
        """Drop cached stores so the next query reads a rebuilt index."""
        with self._lock:
            target = self.code_retriever if kind == "code" else self.doc_retriever
            target._store = None
            self._lexical.pop(kind, None)

    def _retriever(self, kind: str):
        return self.code_retriever if kind == "code" else self.doc_retriever

    def lexical(self, kind: str) -> LexicalIndex:
        index = self._lexical.get(kind)
        if index is None:
            with self._lock:
                index = self._lexical.get(kind)
                if index is None:
                    index = LexicalIndex()
                    retriever = self._retriever(kind)
                    if retriever.is_available():
                        index.build_index(retriever.store.metadata)
                    self._lexical[kind] = index
        return index

    @property
    def code_lexical(self) -> LexicalIndex:
        return self.lexical("code")

    @property
    def doc_lexical(self) -> LexicalIndex:
        return self.lexical("doc")

    # ── ranking ─────────────────────────────────────────────────────────────

    def _score_pool(
        self,
        kind: str,
        query: AnalyzedQuery,
        expanded: AnalyzedQuery,
        dense_text: str,
        file_filter: Optional[str],
    ) -> List[ScoredChunk]:
        lex = self.lexical(kind)
        if not lex.corpus:
            return []

        bm25 = lex.bm25(expanded)
        exact = lex.exact_hits(query)
        # Identifiers added by vocabulary expansion are curated but still a
        # guess about what the question meant, so they count for less.
        expanded_exact = {i for i in lex.exact_hits(expanded) if i not in exact}
        top_lexical = sorted(bm25.items(), key=lambda x: x[1], reverse=True)[: self.CANDIDATES]
        pool: Dict[int, float] = {idx: 0.0 for idx, _ in top_lexical}
        pool.update({idx: 0.0 for idx in exact})
        pool.update({idx: 0.0 for idx in expanded_exact})

        dense_scores: Dict[int, float] = {}
        for meta, sim in self._retriever(kind).retrieve(dense_text, top_k=self.CANDIDATES, file_filter=file_filter):
            idx = lex.position_of(meta)
            if idx is not None:
                dense_scores[idx] = sim
                pool.setdefault(idx, 0.0)

        weights = term_weights(query, lex.idf)
        alternatives = term_alternatives(query.raw)
        # The question's own words only: bridge terms like `distance_km` are
        # defined in dozens of chunks and would make every one a "definition".
        vocabulary = set(query.term_set)
        named_files = {f.lower() for f in query.filenames}
        bm25_max = max((bm25.get(i, 0.0) for i in pool), default=0.0) or 1.0
        lo, span = 0.0, 1.0
        if dense_scores:
            lo = min(dense_scores.values())
            span = (max(dense_scores.values()) - lo) or 1.0
        w = self.WEIGHTS
        scored: List[ScoredChunk] = []
        for idx in pool:
            meta = lex.corpus[idx]
            path = str(meta.get("file") or "").replace("\\", "/")
            if file_filter and file_filter.lower() not in path.lower():
                continue
            # Tests are excluded unless the question is about tests. A test
            # is never the answer to "what is X" -- the code it tests is --
            # and tests quote the questions they check verbatim, so they
            # outranked the definitions they were written to find.
            if _TEST_PATH.search(path.lower()) and not query.mentions_tests:
                continue
            coverage = lex.coverage(idx, weights, alternatives)
            phrase = lex.phrase_score(idx, query)
            dense = (dense_scores[idx] - lo) / span if idx in dense_scores else 0.0
            symbol = lex.symbol_overlap(idx, query)
            definition = lex.definition_hit(idx, vocabulary)
            # "What does offlineQueue.ts do" is answered by the file's opening
            # comment, not by whichever inner window repeats its words most.
            file_overview = (
                path.rsplit("/", 1)[-1].lower() in named_files and (meta.get("start_line") or 1) <= 3
            )
            # The assistant's own source (canned answers, prompts, tool
            # wrappers) describes the rest of the system in prose, so it
            # matches questions about fares or crew as well as the code that
            # implements them. It is evidence about the AI layer, not about
            # fares or crew.
            is_ai_layer = path.startswith("backend/app/ai/") and not query.about_ai_layer
            tiny = len((meta.get("content") or "").strip()) < 60
            score = (
                w["coverage"] * coverage
                + w["bm25"] * bm25.get(idx, 0.0) / bm25_max
                + w["dense"] * dense
                + w["phrase"] * phrase
                + w["exact"] * (1.0 if idx in exact else 0.0)
                + w["expanded_exact"] * (1.0 if idx in expanded_exact else 0.0)
                + w["symbol"] * symbol
                + w["definition"] * definition
                + w["file_overview"] * file_overview
                + w["ai_layer"] * is_ai_layer
                + w["tiny"] * tiny
            )
            relevance = max(coverage, phrase, symbol, definition, 1.0 if idx in exact else 0.0)
            scored.append(ScoredChunk(meta=meta, score=score, relevance=relevance, lexical=lex))
        return scored

    @staticmethod
    def _diversify(ranked: List[ScoredChunk], top_k: int, per_file: int) -> List[ScoredChunk]:
        """Drop overlapping windows of one file and cap chunks per file."""
        chosen: List[ScoredChunk] = []
        per: Dict[str, int] = {}
        for item in ranked:
            path = str(item.meta.get("file") or "")
            start, end = item.meta.get("start_line") or 0, item.meta.get("end_line") or 0
            overlaps = any(
                str(c.meta.get("file") or "") == path
                and start <= (c.meta.get("end_line") or 0)
                and (c.meta.get("start_line") or 0) <= end
                for c in chosen
            )
            if overlaps or per.get(path, 0) >= per_file:
                continue
            chosen.append(item)
            per[path] = per.get(path, 0) + 1
            if len(chosen) >= top_k:
                break
        return chosen

    def _ranked(
        self,
        query: str,
        mode: RetrievalMode,
        top_k: int,
        file_filter: Optional[str],
    ) -> Tuple[List[ScoredChunk], AnalyzedQuery]:
        self._ensure_fresh()
        if mode == RetrievalMode.AUTO:
            mode = QueryRouter.route_query(query)
        kinds = {
            RetrievalMode.CODE: ["code"],
            RetrievalMode.DOCUMENTATION: ["doc"],
        }.get(mode, ["code", "doc"])

        analyzed = analyze_query(query)
        expanded_text = expand_query(query)
        expanded = analyze_query(expanded_text)
        logger.info("Retrieval for %r over %s", query, "+".join(kinds))

        pooled: List[ScoredChunk] = []
        for kind in kinds:
            pooled.extend(self._score_pool(kind, analyzed, expanded, expanded_text, file_filter))
        pooled.sort(key=lambda s: s.score, reverse=True)
        per_file = top_k if file_filter else self.MAX_PER_FILE
        return self._diversify(pooled, top_k, per_file), analyzed

    def retrieve(
        self,
        query: str,
        mode: RetrievalMode = RetrievalMode.AUTO,
        top_k: int = 5,
        file_filter: Optional[str] = None,
    ) -> List[Tuple[Dict[str, Any], float]]:
        """Retrieve evidence chunks according to the selected or auto-detected mode."""
        ranked, _ = self._ranked(query, mode, top_k, file_filter)
        return [(item.meta, item.score) for item in ranked]

    def retrieve_citations(
        self,
        query: str,
        mode: RetrievalMode = RetrievalMode.AUTO,
        top_k: int = 4,
        file_filter: Optional[str] = None,
        min_relevance: float = 0.0,
    ) -> List[Citation]:
        """Citations whose snippet is the part of the chunk that answers the query.

        The snippet is what the answer model reads, so it is chosen for the
        question and its line range narrowed to match. Sources covering less
        than ``min_relevance`` of the question are dropped.
        """
        ranked, analyzed = self._ranked(query, mode, top_k, file_filter)
        citations: List[Citation] = []
        for item in ranked:
            if item.relevance < min_relevance:
                continue
            meta = item.meta
            content = meta.get("content", "") or ""
            weights = term_weights(analyzed, item.lexical.idf)
            excerpt, first, last = best_excerpt(content, analyzed, weights, self.EXCERPT_CHARS)
            start_line = meta.get("start_line")
            end_line = meta.get("end_line")
            if isinstance(start_line, int) and excerpt != content:
                start_line, end_line = start_line + first, start_line + last
            signature = meta.get("signature")
            if signature and signature.strip() not in excerpt:
                indent = signature[: len(signature) - len(signature.lstrip())]
                excerpt = f"{signature}\n{indent}    ...\n{excerpt}"
            citations.append(
                Citation(
                    source_type=meta.get("source_type", "code"),
                    title=meta.get("title") or meta.get("symbol") or meta.get("file", "DBARS Source"),
                    path=meta.get("file"),
                    symbol=meta.get("symbol"),
                    section=meta.get("section"),
                    start_line=start_line,
                    end_line=end_line,
                    snippet=excerpt,
                    relevance=round(item.relevance, 3),
                )
            )
        return citations


hybrid_retriever = HybridRetriever()
