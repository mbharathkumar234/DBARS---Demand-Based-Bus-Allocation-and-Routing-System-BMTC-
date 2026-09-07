from __future__ import annotations

import hashlib
import logging
import os
import logging
from abc import ABC, abstractmethod
from typing import List
import numpy as np

logger = logging.getLogger("bmtc-ai")


class BaseEmbeddings(ABC):
    """Abstract base class for vector embeddings."""

    @abstractmethod
    def embed_documents(self, texts: List[str]) -> np.ndarray:
        """Generate embedding vectors for a list of document texts."""
        pass

    @abstractmethod
    def embed_query(self, text: str) -> np.ndarray:
        """Generate an embedding vector for a single query text."""
        pass

    @property
    @abstractmethod
    def dimension(self) -> int:
        """Return the vector dimensionality."""
        pass


class DeterministicLocalEmbeddings(BaseEmbeddings):
    """High-speed deterministic local embedding generator.

    Produces normalized 384-dimensional dense vectors using a combination of
    subword n-gram hashing and term frequency features. This guarantees:
    1. Zero remote network calls or token fees.
    2. Identical, deterministic vector representations across runs.
    3. Seamless offline execution for CI/CD and automated tests.
    """

    def __init__(self, dimension: int = 384) -> None:
        self._dimension = dimension

    @property
    def name(self) -> str:
        return f"DeterministicLocalEmbeddings-{self._dimension}d"

    @property
    def dimension(self) -> int:
        return self._dimension

    def _embed_text(self, text: str) -> np.ndarray:
        vec = np.zeros(self._dimension, dtype=np.float32)
        words = text.lower().split()
        if not words:
            return vec

        for word in words:
            # Word level hash
            h = int(hashlib.md5(word.encode("utf-8")).hexdigest(), 16)
            idx = h % self._dimension
            sign = 1.0 if ((h >> 8) & 1) else -1.0
            vec[idx] += sign

            # Character 3-gram hashes for subword sensitivity
            if len(word) >= 3:
                for i in range(len(word) - 2):
                    sub = word[i : i + 3]
                    sh = int(hashlib.sha256(sub.encode("utf-8")).hexdigest(), 16)
                    s_idx = sh % self._dimension
                    s_sign = 0.5 if ((sh >> 4) & 1) else -0.5
                    vec[s_idx] += s_sign

        norm = np.linalg.norm(vec)
        if norm > 1e-6:
            vec /= norm
        return vec

    def embed_documents(self, texts: List[str]) -> np.ndarray:
        if not texts:
            return np.empty((0, self._dimension), dtype=np.float32)
        vectors = [self._embed_text(t) for t in texts]
        return np.vstack(vectors).astype(np.float32)

    def embed_query(self, text: str) -> np.ndarray:
        return self._embed_text(text)


class SentenceTransformerEmbeddings(BaseEmbeddings):
    """Real semantic embeddings via sentence-transformers.

    Opt-in. Unlike the deterministic provider below, this places texts with the
    same meaning but different wording close together, which is what makes
    retrieval genuinely semantic rather than fuzzy-lexical.
    """

    def __init__(self, model_name: str) -> None:
        from sentence_transformers import SentenceTransformer

        self.model_name = model_name
        self._model = SentenceTransformer(model_name)
        # Renamed in newer sentence-transformers; support both.
        dim_fn = getattr(self._model, "get_embedding_dimension", None) or self._model.get_sentence_embedding_dimension
        self._dimension = int(dim_fn())

    @property
    def name(self) -> str:
        return f"SentenceTransformer-{self.model_name}"

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed_documents(self, texts: List[str]) -> np.ndarray:
        vectors = self._model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        return np.asarray(vectors, dtype="float32")

    def embed_query(self, text: str) -> np.ndarray:
        return self.embed_documents([text])[0]


def get_embedding_provider() -> BaseEmbeddings:
    """Factory returning the configured embedding provider.

    Defaults to the deterministic hashing provider, which needs no model
    download and makes indexing reproducible offline. Note what that trades
    away: hashed n-grams are lexical, so "how is the fare computed" and "where
    is pricing calculated" do NOT land near each other the way true sentence
    embeddings would. Retrieval behaves like a fuzzy keyword index.

    Set AI_EMBEDDING_PROVIDER=sentence-transformers for real semantic
    embeddings. It is opt-in rather than automatic because the model is a
    ~90MB download on first use, and because switching providers invalidates
    any existing index -- both are 384-d, so a mismatch would not fail loudly,
    it would just return quietly wrong neighbours. VectorStore records which
    provider built an index and warns when they disagree.
    """
    from app.ai.config import ai_settings  # imported here: loads .env on first use

    provider = (ai_settings.embedding_provider or "deterministic").strip().lower()

    if provider in {"sentence-transformers", "sentence_transformers", "st"}:
        model_name = ai_settings.embedding_model or "all-MiniLM-L6-v2"
        try:
            return SentenceTransformerEmbeddings(model_name)
        except Exception as exc:
            logger.warning(
                "Could not load sentence-transformers model %r (%s); falling back to "
                "deterministic hashing embeddings. Retrieval will be lexical, not semantic.",
                model_name, exc,
            )

    return DeterministicLocalEmbeddings(dimension=384)
