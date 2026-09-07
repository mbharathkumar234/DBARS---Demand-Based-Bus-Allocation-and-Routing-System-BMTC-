from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import faiss
import numpy as np

from app.ai.rag.embeddings import BaseEmbeddings, get_embedding_provider

logger = logging.getLogger("bmtc-ai")


class VectorStore:
    """FAISS-backed vector store with persistent metadata for code & doc chunks."""

    def __init__(self, embedding_provider: Optional[BaseEmbeddings] = None) -> None:
        self.embedder = embedding_provider or get_embedding_provider()
        self.dimension = self.embedder.dimension
        # IndexFlatIP computes inner product, which equals cosine similarity for normalized vectors
        self.index = faiss.IndexFlatIP(self.dimension)
        self.metadata: List[Dict[str, Any]] = []

    def add_chunks(self, chunks: List[Dict[str, Any]]) -> int:
        """Add chunks, compute embeddings, and store in FAISS index."""
        if not chunks:
            return 0

        texts = [c.get("content", "") for c in chunks]
        vectors = self.embedder.embed_documents(texts)

        # Normalize vectors for cosine similarity
        faiss.normalize_L2(vectors)
        self.index.add(vectors)
        self.metadata.extend(chunks)

        return len(chunks)

    def similarity_search(
        self, query: str, top_k: int = 5, file_filter: Optional[str] = None
    ) -> List[Tuple[Dict[str, Any], float]]:
        """Search top-k most similar chunks for a query string."""
        if self.index.ntotal == 0:
            return []

        q_vec = self.embedder.embed_query(query).reshape(1, -1)
        faiss.normalize_L2(q_vec)

        # Retrieve a wider pool if filtering is applied
        fetch_k = min(self.index.ntotal, top_k * 3 if file_filter else top_k)
        scores, indices = self.index.search(q_vec, fetch_k)

        results: List[Tuple[Dict[str, Any], float]] = []
        for score, idx in zip(scores[0], indices[0]):
            if idx < 0 or idx >= len(self.metadata):
                continue
            meta = self.metadata[idx]
            if file_filter and file_filter.lower() not in meta.get("file", "").lower():
                continue
            results.append((meta, float(score)))
            if len(results) >= top_k:
                break

        return results

    def save(self, directory: Path) -> None:
        """Persist index and metadata to disk."""
        directory.mkdir(parents=True, exist_ok=True)
        index_file = directory / "index.faiss"
        meta_file = directory / "metadata.json"

        faiss.write_index(self.index, str(index_file))
        with open(meta_file, "w", encoding="utf-8") as f:
            json.dump(self.metadata, f, indent=2)

        # Record which embedding provider built this index. Providers can share
        # a dimension (both the deterministic and MiniLM providers are 384-d),
        # so querying an index with the wrong one would not raise -- it would
        # silently return meaningless neighbours.
        with open(directory / "embedding_provider.json", "w", encoding="utf-8") as f:
            json.dump({"provider": getattr(self.embedder, "name", type(self.embedder).__name__),
                       "dimension": self.embedder.dimension}, f, indent=2)

        logger.info("Saved vector store with %s items to %s", self.index.ntotal, directory)

    @classmethod
    def load(cls, directory: Path, embedding_provider: Optional[BaseEmbeddings] = None) -> "VectorStore":
        """Load vector store from disk."""
        store = cls(embedding_provider=embedding_provider)
        index_file = directory / "index.faiss"
        meta_file = directory / "metadata.json"

        if not index_file.exists() or not meta_file.exists():
            raise FileNotFoundError(f"Vector store not found in {directory}")

        store.index = faiss.read_index(str(index_file))
        with open(meta_file, "r", encoding="utf-8") as f:
            store.metadata = json.load(f)

        provider_file = directory / "embedding_provider.json"
        active = getattr(store.embedder, "name", type(store.embedder).__name__)
        if provider_file.exists():
            with open(provider_file, "r", encoding="utf-8") as f:
                built_with = json.load(f).get("provider")
            if built_with and built_with != active:
                logger.warning(
                    "Vector store at %s was built with %r but is being queried with %r. "
                    "Vectors from different providers are not comparable -- results will be "
                    "meaningless. Re-run ingestion, or set AI_EMBEDDING_PROVIDER back.",
                    directory, built_with, active,
                )
        else:
            # An index written before this file existed. Silence here would be
            # the worst outcome: every provider is 384-dimensional, so querying
            # a hash-built index with sentence-transformer vectors loads and
            # searches without error and returns meaningless neighbours.
            logger.warning(
                "Vector store at %s does not record which embedding provider built it, and is "
                "being queried with %r. If it was built with a different provider the results "
                "are meaningless -- re-run ingestion to remove this warning.",
                directory, active,
            )

        logger.info("Loaded vector store with %s items from %s", store.index.ntotal, directory)
        return store
