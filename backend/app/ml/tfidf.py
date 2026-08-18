from __future__ import annotations

import math
from collections import Counter

from .text import tokenize


class TfidfIndex:
    def __init__(self) -> None:
        self.vocabulary: dict[str, int] = {}
        self.idf: dict[str, float] = {}
        self.document_vectors: list[dict[str, float]] = []
        self.document_norms: list[float] = []

    def fit(self, documents: list[str]) -> "TfidfIndex":
        # tokenize() now includes words, bigrams, AND character 3-grams
        doc_tokens = [set(tokenize(document)) for document in documents]
        df: Counter[str] = Counter()
        for tokens in doc_tokens:
            df.update(tokens)
        self.vocabulary = {token: index for index, token in enumerate(sorted(df))}
        total = len(documents)
        self.idf = {
            token: math.log((1 + total) / (1 + count)) + 1.0
            for token, count in df.items()
        }
        self.document_vectors = [self.transform(document) for document in documents]
        self.document_norms = [self._norm(vector) for vector in self.document_vectors]
        return self

    def transform(self, document: str) -> dict[str, float]:
        counts = Counter(token for token in tokenize(document) if token in self.idf)
        total = sum(counts.values()) or 1
        return {token: (count / total) * self.idf[token] for token, count in counts.items()}

    def similarities(self, query: str) -> list[float]:
        query_vector = self.transform(query)
        query_norm = self._norm(query_vector)
        if query_norm == 0:
            return [0.0 for _ in self.document_vectors]
        scores: list[float] = []
        for vector, norm in zip(self.document_vectors, self.document_norms):
            if norm == 0:
                scores.append(0.0)
                continue
            dot = sum(weight * vector.get(token, 0.0) for token, weight in query_vector.items())
            scores.append(dot / (query_norm * norm))
        return scores

    @staticmethod
    def _norm(vector: dict[str, float]) -> float:
        return math.sqrt(sum(value * value for value in vector.values()))
