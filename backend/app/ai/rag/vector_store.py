from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import faiss

from app.ai.rag.embeddings import BaseEmbeddings, get_embedding_provider
from app.ai.rag.text import chunk_search_text

logger = logging.getLogger("bmtc-ai")

MANIFEST_NAME = "index_manifest.json"


class VectorStore:
    """FAISS-backed vector store with persistent metadata for code & doc chunks."""

    def __init__(self, embedding_provider: Optional[BaseEmbeddings] = None) -> None:
        self.embedder = embedding_provider or get_embedding_provider()
        self.dimension = self.embedder.dimension
        # IndexFlatIP computes inner product, which equals cosine similarity for normalized vectors
        self.index = faiss.IndexFlatIP(self.dimension)
        self.metadata: List[Dict[str, Any]] = []
        # False when the index on disk was built by a different embedding
        # provider. Every provider here is 384-d, so a mismatched query would
        # search without error and return meaningless neighbours; dense search
        # is disabled instead and retrieval runs on the lexical index alone.
        self.compatible = True

    @property
    def provider_name(self) -> str:
        return getattr(self.embedder, "name", type(self.embedder).__name__)

    def add_chunks(self, chunks: List[Dict[str, Any]]) -> int:
        """Add chunks, compute embeddings, and store in FAISS index."""
        if not chunks:
            return 0
        vectors = self.embedder.embed_documents([chunk_search_text(c) for c in chunks])
        faiss.normalize_L2(vectors)
        self.index.add(vectors)
        self.metadata.extend(chunks)
        return len(chunks)

    def similarity_search(
        self, query: str, top_k: int = 5, file_filter: Optional[str] = None
    ) -> List[Tuple[Dict[str, Any], float]]:
        """Search top-k most similar chunks for a query string."""
        if self.index.ntotal == 0 or not self.compatible:
            return []

        q_vec = self.embedder.embed_query(query).reshape(1, -1).astype("float32")
        faiss.normalize_L2(q_vec)

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

    def save(self, directory: Path, manifest: Optional[Dict[str, Any]] = None) -> None:
        """Persist index, metadata and a manifest describing how it was built.

        Each file is written beside its target and moved into place, and the
        manifest goes last: a rebuild interrupted part-way (a background
        refresh in a process that exits) leaves the previous index readable
        and still marked as the previous build, never a torn one.
        """
        directory.mkdir(parents=True, exist_ok=True)
        tmp_index = directory / "index.faiss.tmp"
        faiss.write_index(self.index, str(tmp_index))
        tmp_meta = directory / "metadata.json.tmp"
        with open(tmp_meta, "w", encoding="utf-8") as f:
            json.dump(self.metadata, f)
        record = {
            "provider": self.provider_name,
            "dimension": self.embedder.dimension,
            "chunks": len(self.metadata),
            "built_at": time.time(),
            **(manifest or {}),
        }
        tmp_manifest = directory / (MANIFEST_NAME + ".tmp")
        with open(tmp_manifest, "w", encoding="utf-8") as f:
            json.dump(record, f, indent=2)
        os.replace(tmp_index, directory / "index.faiss")
        os.replace(tmp_meta, directory / "metadata.json")
        os.replace(tmp_manifest, directory / MANIFEST_NAME)
        logger.info("Saved vector store with %s items to %s", self.index.ntotal, directory)

    @classmethod
    def load(cls, directory: Path, embedding_provider: Optional[BaseEmbeddings] = None) -> "VectorStore":
        """Load vector store from disk."""
        store = cls(embedding_provider=embedding_provider)
        index_file = directory / "index.faiss"
        meta_file = directory / "metadata.json"
        if not index_file.exists() or not meta_file.exists():
            raise FileNotFoundError(f"Vector store not found in {directory}")

        for attempt in range(3):
            store.index = faiss.read_index(str(index_file))
            with open(meta_file, "r", encoding="utf-8") as f:
                store.metadata = json.load(f)
            # Read between a rebuild's two file swaps: vectors and metadata
            # from different builds would pair each vector with the wrong text.
            if store.index.ntotal == len(store.metadata):
                break
            time.sleep(0.2)
        else:
            raise RuntimeError(
                f"Vector store at {directory} has {store.index.ntotal} vectors but "
                f"{len(store.metadata)} metadata entries; rebuild the index"
            )

        built_with = None
        try:
            with open(directory / MANIFEST_NAME, "r", encoding="utf-8") as f:
                built_with = json.load(f).get("provider")
        except (OSError, ValueError):
            pass
        if built_with != store.provider_name or store.index.d != store.embedder.dimension:
            store.compatible = False
            logger.warning(
                "Vector store at %s was built with %r but the active embedding provider is %r. "
                "Dense search is disabled for it; retrieval falls back to the lexical index "
                "until the index is rebuilt.",
                directory, built_with, store.provider_name,
            )

        logger.info("Loaded vector store with %s items from %s", store.index.ntotal, directory)
        return store
