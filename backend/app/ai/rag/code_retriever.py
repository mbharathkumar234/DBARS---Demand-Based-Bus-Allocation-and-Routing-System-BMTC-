from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from app.ai.config import ai_settings
from app.ai.models import Citation
from app.ai.rag.vector_store import VectorStore

logger = logging.getLogger("bmtc-ai-code-retriever")


class CodebaseRetriever:
    """Retrieves code implementations and symbols from the DBARS codebase."""

    def __init__(self, index_path: Optional[str] = None) -> None:
        self.index_path = ai_settings.code_index_path
        self._store: Optional[VectorStore] = None

    @property
    def store(self) -> VectorStore:
        if self._store is None:
            self._store = VectorStore.load(self.index_path)
        return self._store

    def is_available(self) -> bool:
        return (self.index_path / "index.faiss").exists() and (self.index_path / "metadata.json").exists()

    def retrieve(
        self, query: str, top_k: int = 5, file_filter: Optional[str] = None
    ) -> List[Tuple[Dict[str, Any], float]]:
        """Retrieve top-k code chunks with relevance scores."""
        if not self.is_available():
            logger.warning("Codebase index not found at %s", self.index_path)
            return []
        return self.store.similarity_search(query, top_k=top_k, file_filter=file_filter)

    def retrieve_citations(self, query: str, top_k: int = 3, file_filter: Optional[str] = None) -> List[Citation]:
        """Retrieve top matching code chunks formatted as structured Citations."""
        results = self.retrieve(query, top_k=top_k, file_filter=file_filter)
        citations: List[Citation] = []
        for meta, score in results:
            citations.append(
                Citation(
                    source_type="code",
                    title=meta.get("symbol", meta.get("file", "DBARS Code")),
                    path=meta.get("file"),
                    symbol=meta.get("symbol"),
                    start_line=meta.get("start_line"),
                    end_line=meta.get("end_line"),
                    snippet=meta.get("content", "")[:300],
                )
            )
        return citations


code_retriever = CodebaseRetriever()
