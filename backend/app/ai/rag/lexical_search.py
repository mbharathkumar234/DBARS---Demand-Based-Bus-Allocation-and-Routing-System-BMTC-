from __future__ import annotations

import math
from collections import Counter, defaultdict
from pathlib import PurePosixPath
from typing import Any, Dict, FrozenSet, List, Mapping, Optional, Set, Tuple, Union

from app.ai.rag.text import (
    STOP_WORDS,
    AnalyzedQuery,
    analyze_query,
    chunk_search_text,
    defined_names,
    normalize_for_phrases,
    split_identifier,
    stem,
    tokenize,
)


class LexicalIndex:
    """BM25 index plus exact symbol and file-name lookup over chunk metadata."""

    STOP_WORDS = STOP_WORDS

    def __init__(self, k1: float = 1.2, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b
        self.corpus: List[Dict[str, Any]] = []
        self.doc_len: List[int] = []
        self.avg_doc_len: float = 0.0
        self.inverted_index: Dict[str, List[Tuple[int, int]]] = defaultdict(list)
        self.idf: Dict[str, float] = {}
        self.term_sets: List[FrozenSet[str]] = []
        self.phrase_text: List[str] = []
        self.symbol_index: Dict[str, List[int]] = defaultdict(list)
        self.symbol_parts: List[FrozenSet[str]] = []
        self.definition_parts: List[Tuple[FrozenSet[str], ...]] = []
        self.file_index: Dict[str, List[int]] = defaultdict(list)
        self._position: Dict[int, int] = {}

    @staticmethod
    def _tokenize(text: str, filter_stops: bool = True) -> List[str]:
        return tokenize(text, filter_stops=filter_stops)

    def build_index(self, chunks: List[Dict[str, Any]]) -> None:
        """Index a list of chunk metadata dictionaries."""
        self.corpus = chunks
        self.doc_len = []
        self.inverted_index = defaultdict(list)
        self.term_sets = []
        self.phrase_text = []
        self.symbol_index = defaultdict(list)
        self.symbol_parts = []
        self.definition_parts = []
        self.file_index = defaultdict(list)
        self._position = {id(chunk): i for i, chunk in enumerate(chunks)}

        total = 0
        for doc_idx, chunk in enumerate(chunks):
            symbol = str(chunk.get("symbol") or "")
            short = symbol.split(".")[-1]
            parts: FrozenSet[str] = frozenset()
            if symbol and ":L" not in symbol:
                lowered = symbol.lower()
                keys = {lowered, lowered.split(".")[-1]}
                for key in keys:
                    self.symbol_index[key].append(doc_idx)
                if not short.startswith("__"):
                    parts = frozenset(stem(p) for p in split_identifier(short) if p not in STOP_WORDS)
            self.symbol_parts.append(parts)
            defined = []
            for name in set(defined_names(chunk.get("content", "") or "")):
                name_parts = frozenset(stem(p) for p in split_identifier(name) if p not in STOP_WORDS)
                if len(name_parts) >= 2:
                    defined.append(name_parts)
            self.definition_parts.append(tuple(defined))

            filepath = str(chunk.get("file") or "").replace("\\", "/")
            if filepath:
                name = PurePosixPath(filepath).name.lower()
                self.file_index[name].append(doc_idx)
                stem_name = name.split(".")[0]
                if stem_name != name:
                    self.file_index[stem_name].append(doc_idx)

            text = chunk_search_text(chunk)
            tokens = tokenize(text)
            self.doc_len.append(len(tokens))
            total += len(tokens)
            tf = Counter(tokens)
            for term, freq in tf.items():
                self.inverted_index[term].append((doc_idx, freq))
            self.term_sets.append(frozenset(tf))
            self.phrase_text.append(normalize_for_phrases(chunk.get("content", "") + " " + symbol))

        n = max(1, len(chunks))
        self.avg_doc_len = total / n
        self.idf = {
            term: math.log(1.0 + (n - len(postings) + 0.5) / (len(postings) + 0.5))
            for term, postings in self.inverted_index.items()
        }

    def position_of(self, meta: Mapping[str, Any]) -> Optional[int]:
        return self._position.get(id(meta))

    def exact_hits(self, query: AnalyzedQuery) -> Dict[int, str]:
        """Chunks named by the query: an identifier it spells, or a file it names."""
        hits: Dict[int, str] = {}
        for ident in query.identifiers:
            for key in {ident.lower(), ident.lower().split(".")[-1]}:
                for doc_idx in self.symbol_index.get(key, []):
                    hits[doc_idx] = "symbol"
        # A single distinctive word can still be a symbol name ("predictor",
        # "lifespan"); common words cannot, so require it to be rare.
        for word in query.raw.replace("(", " ").replace(")", " ").split():
            key = word.strip("`'\".,?!:;").lower()
            if len(key) >= 6 and key not in STOP_WORDS and len(self.symbol_index.get(key, [])) <= 3:
                for doc_idx in self.symbol_index.get(key, []):
                    hits.setdefault(doc_idx, "symbol")
        for filename in query.filenames:
            for key in {filename, filename.split(".")[0]}:
                for doc_idx in self.file_index.get(key, []):
                    hits.setdefault(doc_idx, "file")
        for ident in query.identifiers:
            for doc_idx in self.file_index.get(ident.lower(), []):
                hits.setdefault(doc_idx, "file")
        return hits

    def bm25(self, query: AnalyzedQuery) -> Dict[int, float]:
        scores: Dict[int, float] = defaultdict(float)
        for term in query.terms:
            postings = self.inverted_index.get(term)
            if not postings:
                continue
            idf = self.idf[term]
            for doc_idx, freq in postings:
                norm = 1.0 - self.b + self.b * (self.doc_len[doc_idx] / max(1.0, self.avg_doc_len))
                scores[doc_idx] += idf * (freq * (self.k1 + 1.0)) / (freq + self.k1 * norm)
        return scores

    def coverage(
        self,
        doc_idx: int,
        weights: Mapping[str, float],
        alternatives: Optional[Mapping[str, Set[str]]] = None,
    ) -> float:
        """IDF-weighted share of the query's terms that the chunk contains.

        A term also counts as present when the chunk has one of its
        ``alternatives`` -- the identifiers a vocabulary bridge maps it to.
        """
        total = sum(weights.values())
        if total <= 0:
            return 0.0
        present = self.term_sets[doc_idx]
        alternatives = alternatives or {}
        covered = sum(
            w for t, w in weights.items()
            if t in present or not present.isdisjoint(alternatives.get(t, ()))
        )
        return covered / total

    def symbol_overlap(self, doc_idx: int, query: AnalyzedQuery) -> float:
        """How fully the question names this chunk's symbol.

        "what crowding levels exist" names ``CrowdingLevel`` although it never
        spells it. Every part must match: sharing two of three words with
        ``_AI_LAYER_TOPIC`` does not make a question about that regex.
        """
        parts = self.symbol_parts[doc_idx]
        if not parts or not parts <= query.term_set:
            return 0.0
        return 1.0 if len(parts) > 1 or len(next(iter(parts))) >= 5 else 0.0

    def definition_hit(self, doc_idx: int, vocabulary: Set[str]) -> float:
        """Whether the chunk defines a field or constant the question names.

        "What is the maximum deadhead distance" names `max_deadhead_km: float
        = 5.0` -- the line holding the answer -- without spelling it. Counted
        when at least two of the name's words, and two thirds of them, are in
        the question (units like `_minutes` are rarely said aloud).
        """
        for parts in self.definition_parts[doc_idx]:
            matched = len(parts & vocabulary)
            if matched >= 2 and matched * 3 >= len(parts) * 2:
                return 1.0
        return 0.0

    def phrase_score(self, doc_idx: int, query: AnalyzedQuery) -> float:
        """Share of the query's adjacent word pairs that appear verbatim."""
        if not query.phrases:
            return 0.0
        text = self.phrase_text[doc_idx]
        pairs = [p for p in query.phrases if len(p.split()) == 2]
        longer = [p for p in query.phrases if len(p.split()) > 2]
        score = sum(f" {p} " in text for p in pairs) / len(pairs) if pairs else 0.0
        if any(f" {p} " in text for p in longer + query.quoted):
            score = max(score, 1.0)
        return score

    def search(self, query: Union[str, AnalyzedQuery], top_k: int = 5) -> List[Tuple[Dict[str, Any], float]]:
        """BM25 ranking, with chunks the query names exactly always included."""
        if not self.corpus:
            return []
        analyzed = analyze_query(query) if isinstance(query, str) else query
        scores = self.bm25(analyzed)
        top = max(scores.values(), default=1.0)
        for doc_idx in self.exact_hits(analyzed):
            scores[doc_idx] = scores.get(doc_idx, 0.0) + top
        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:top_k]
        return [(self.corpus[doc_idx], score) for doc_idx, score in ranked]
