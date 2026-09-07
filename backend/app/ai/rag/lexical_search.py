from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from typing import Any, Dict, List, Set, Tuple


class LexicalIndex:
    """BM25 and exact symbol index for source code and documentation chunks."""

    def __init__(self, k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b
        self.corpus: List[Dict[str, Any]] = []
        self.doc_len: List[int] = []
        self.avg_doc_len: float = 0.0
        self.inverted_index: Dict[str, List[Tuple[int, int]]] = defaultdict(list)  # term -> [(doc_idx, freq)]
        self.symbol_index: Dict[str, List[int]] = defaultdict(list)  # normalized symbol -> [doc_idx]
        self.file_index: Dict[str, List[int]] = defaultdict(list)  # filename -> [doc_idx]

    STOP_WORDS = {
        "a", "an", "the", "and", "or", "in", "on", "at", "to", "for", "of", "with",
        "by", "from", "is", "are", "was", "were", "be", "been", "being", "have", "has",
        "had", "do", "does", "did", "what", "which", "who", "whom", "this", "that", "these",
        "those", "it", "its", "as", "if", "then", "else", "when", "where", "how", "all",
        "any", "both", "each", "few", "more", "most", "other", "some", "such", "no", "nor",
        "not", "only", "own", "same", "so", "than", "too", "very", "can", "will", "just", "about",
    }

    @staticmethod
    def _tokenize(text: str, filter_stops: bool = True) -> List[str]:
        tokens = re.findall(r"[A-Za-z0-9_]+", text.lower())
        sub_tokens: List[str] = []
        for t in tokens:
            if filter_stops and t in LexicalIndex.STOP_WORDS:
                continue
            sub_tokens.append(t)
            if "_" in t:
                sub_tokens.extend([part for part in t.split("_") if part and (not filter_stops or part not in LexicalIndex.STOP_WORDS)])
        return sub_tokens

    def build_index(self, chunks: List[Dict[str, Any]]) -> None:
        """Index a list of chunk metadata dictionaries."""
        self.corpus = chunks
        self.doc_len = []
        self.inverted_index.clear()
        self.symbol_index.clear()
        self.file_index.clear()

        total_tokens = 0
        for doc_idx, chunk in enumerate(chunks):
            # Index exact symbol name
            symbol = chunk.get("symbol", "")
            if symbol:
                norm_sym = symbol.lower()
                self.symbol_index[norm_sym].append(doc_idx)
                # also index short symbol if Class.method
                if "." in norm_sym:
                    short_sym = norm_sym.split(".")[-1]
                    self.symbol_index[short_sym].append(doc_idx)

            # Index filename
            filepath = chunk.get("file", "")
            if filepath:
                filename = filepath.replace("\\", "/").split("/")[-1].lower()
                self.file_index[filename].append(doc_idx)

            # Index full text for BM25
            content = f"{symbol} {filepath} {chunk.get('section', '')} {chunk.get('content', '')}"
            tokens = self._tokenize(content)
            self.doc_len.append(len(tokens))
            total_tokens += len(tokens)

            tf = Counter(tokens)
            for term, freq in tf.items():
                self.inverted_index[term].append((doc_idx, freq))

        self.avg_doc_len = total_tokens / max(1, len(chunks))

    def search(self, query: str, top_k: int = 5) -> List[Tuple[Dict[str, Any], float]]:
        """Search chunks using exact symbol boosting + BM25 scoring."""
        if not self.corpus:
            return []

        q_lower = query.lower()
        query_terms = self._tokenize(query)
        scores: Dict[int, float] = defaultdict(float)

        # 1. Exact Symbol / File Boost (Massive boost for exact identifier matches)
        COMMON_VERBS = {"stop", "start", "get", "set", "run", "close", "read", "write", "save", "load", "build", "parse", "test", "check", "add", "ready"}
        for term in query_terms:
            if term in self.symbol_index and term not in COMMON_VERBS:
                for doc_idx in self.symbol_index[term]:
                    scores[doc_idx] += 25.0
            if term in self.file_index:
                for doc_idx in self.file_index[term]:
                    scores[doc_idx] += 15.0

        # Check full query as symbol
        clean_q = re.sub(r"[^\w\.]", "", q_lower)
        if clean_q in self.symbol_index:
            for doc_idx in self.symbol_index[clean_q]:
                scores[doc_idx] += 30.0

        # 2. BM25 scoring across terms
        N = len(self.corpus)
        for term in query_terms:
            if term not in self.inverted_index:
                continue
            postings = self.inverted_index[term]
            df = len(postings)
            idf = math.log(1.0 + (N - df + 0.5) / (df + 0.5))

            for doc_idx, freq in postings:
                d_len = self.doc_len[doc_idx]
                numerator = freq * (self.k1 + 1.0)
                denominator = freq + self.k1 * (1.0 - self.b + self.b * (d_len / max(1.0, self.avg_doc_len)))
                bm25 = idf * (numerator / max(1e-6, denominator))
                scores[doc_idx] += bm25

        if not scores:
            return []

        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:top_k]
        return [(self.corpus[doc_idx], score) for doc_idx, score in ranked]
