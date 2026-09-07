from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from app.ai.config import ai_settings
from app.ai.models import Citation, RetrievalMode
from app.ai.rag.code_retriever import code_retriever
from app.ai.rag.doc_retriever import doc_retriever
from app.ai.rag.lexical_search import LexicalIndex

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

        # Default to hybrid if ambiguous so user gets comprehensive evidence
        return RetrievalMode.HYBRID



# Commuters and reviewers ask in plain words; the code names things in
# identifiers. Retrieval here is lexical -- hashed n-grams plus BM25 -- so
# "travelling time" shares no token with `duration_minutes` and the real
# implementation is unreachable by that phrasing. Asking "how travelling time
# is calculated" returned README.md, en.json and a planning document while
# distance.py, which actually computes it, sat unranked in the same index.
#
# Every identifier below is one that exists in this codebase; the mapping
# bridges vocabulary, it does not invent targets.
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
}


def expand_query(query: str) -> str:
    """Append the identifiers a plain-language question is really about.

    The original wording is kept first so exact-symbol queries are unaffected;
    the expansion only adds terms the lexical index can match against.
    """
    lowered = query.lower()
    extras = [ids for phrase, ids in QUERY_VOCABULARY.items() if phrase in lowered]
    return f"{query} {' '.join(extras)}" if extras else query


class HybridRetriever:
    """Fuses dense vector similarity with sparse exact-symbol BM25 retrieval."""

    def __init__(self) -> None:
        self.code_retriever = code_retriever
        self.doc_retriever = doc_retriever
        self._code_lexical: Optional[LexicalIndex] = None
        self._doc_lexical: Optional[LexicalIndex] = None

    @property
    def code_lexical(self) -> LexicalIndex:
        if self._code_lexical is None:
            self._code_lexical = LexicalIndex()
            if self.code_retriever.is_available():
                self._code_lexical.build_index(self.code_retriever.store.metadata)
        return self._code_lexical

    @property
    def doc_lexical(self) -> LexicalIndex:
        if self._doc_lexical is None:
            self._doc_lexical = LexicalIndex()
            if self.doc_retriever.is_available():
                self._doc_lexical.build_index(self.doc_retriever.store.metadata)
        return self._doc_lexical

    def _fuse_rankings(
        self,
        vector_results: List[Tuple[Dict[str, Any], float]],
        lexical_results: List[Tuple[Dict[str, Any], float]],
        top_k: int = 5,
        rrf_k: int = 60,
    ) -> List[Tuple[Dict[str, Any], float]]:
        """Reciprocal Rank Fusion (RRF) combining vector and lexical rankings."""
        scores: Dict[str, float] = {}
        chunk_map: Dict[str, Dict[str, Any]] = {}

        # When lexical search has 0 matches, verify if vector search is sufficiently strong
        if not lexical_results:
            # If no keyword matches and top vector similarity is below confidence floor, reject as ungrounded
            filtered_vec = [(meta, score) for meta, score in vector_results if score >= 0.45]
            if not filtered_vec:
                return []
            vector_results = filtered_vec

        for rank, (meta, score) in enumerate(vector_results, start=1):
            key = f"{meta.get('file', '')}:{meta.get('start_line', 0)}:{meta.get('symbol', '')}"
            scores[key] = scores.get(key, 0.0) + (1.0 / (rrf_k + rank))
            chunk_map[key] = meta

        for rank, (meta, score) in enumerate(lexical_results, start=1):
            key = f"{meta.get('file', '')}:{meta.get('start_line', 0)}:{meta.get('symbol', '')}"
            # Significant boost for exact symbol / identifier hits
            boost = 3.5 if score >= 20.0 else 1.2
            scores[key] = scores.get(key, 0.0) + (boost / (rrf_k + rank))
            chunk_map[key] = meta

        ranked_keys = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:top_k]
        return [(chunk_map[key], score) for key, score in ranked_keys]

    def retrieve(
        self,
        query: str,
        mode: RetrievalMode = RetrievalMode.AUTO,
        top_k: int = 5,
        file_filter: Optional[str] = None,
    ) -> List[Tuple[Dict[str, Any], float]]:
        """Retrieve evidence chunks according to the selected or auto-detected mode."""
        effective_mode = QueryRouter.route_query(query) if mode == RetrievalMode.AUTO else mode
        # Routing decides on the user's own words; matching gets the expansion.
        query = expand_query(query)
        logger.info("Executing retrieval for '%s' in mode: %s", query, effective_mode)

        results: List[Tuple[Dict[str, Any], float]] = []

        if effective_mode in (RetrievalMode.CODE, RetrievalMode.HYBRID):
            code_vec = self.code_retriever.retrieve(query, top_k=top_k * 2, file_filter=file_filter)
            code_lex = self.code_lexical.search(query, top_k=top_k * 2)
            fused_code = self._fuse_rankings(code_vec, code_lex, top_k=top_k)
            results.extend(fused_code)

        if effective_mode in (RetrievalMode.DOCUMENTATION, RetrievalMode.HYBRID):
            doc_vec = self.doc_retriever.retrieve(query, top_k=top_k * 2)
            doc_lex = self.doc_lexical.search(query, top_k=top_k * 2)
            fused_doc = self._fuse_rankings(doc_vec, doc_lex, top_k=top_k)
            results.extend(fused_doc)

        # Sort combined results if HYBRID
        if effective_mode == RetrievalMode.HYBRID:
            results.sort(key=lambda x: x[1], reverse=True)
            results = results[:top_k]

        return results

    def retrieve_citations(
        self,
        query: str,
        mode: RetrievalMode = RetrievalMode.AUTO,
        top_k: int = 4,
        file_filter: Optional[str] = None,
    ) -> List[Citation]:
        """Retrieve and format results as structured Citation objects."""
        raw_results = self.retrieve(query, mode=mode, top_k=top_k, file_filter=file_filter)
        citations: List[Citation] = []

        for meta, score in raw_results:
            source_type = meta.get("source_type", "code")
            citations.append(
                Citation(
                    source_type=source_type,
                    title=meta.get("title") or meta.get("symbol") or meta.get("file", "DBARS Source"),
                    path=meta.get("file"),
                    symbol=meta.get("symbol"),
                    section=meta.get("section"),
                    start_line=meta.get("start_line"),
                    end_line=meta.get("end_line"),
                    snippet=meta.get("content", "")[:350],
                )
            )

        return citations


hybrid_retriever = HybridRetriever()
