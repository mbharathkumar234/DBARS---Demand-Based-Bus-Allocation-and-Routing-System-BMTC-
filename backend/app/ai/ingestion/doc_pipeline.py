from __future__ import annotations

import datetime
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.ai.config import WORKSPACE_DIR, ai_settings
from app.ai.ingestion.doc_parser import DocChunk, DocxParser, MarkdownDocParser
from app.ai.ingestion.freshness import INDEX_SCHEMA_VERSION, doc_sources, fingerprint
from app.ai.rag.embeddings import BaseEmbeddings, get_embedding_provider
from app.ai.rag.vector_store import VectorStore
from app.ai.security.secret_filter import sanitize_content

logger = logging.getLogger("bmtc-ai-doc-ingestion")


class DocumentationIngestionPipeline:
    """Discovers, parses, chunks, and indexes all DBARS documentation."""

    def __init__(self, repo_root: Path, output_dir: Path, embedder: Optional[BaseEmbeddings] = None) -> None:
        self.repo_root = repo_root.resolve()
        self.output_dir = output_dir.resolve()
        self.embedder = embedder or get_embedding_provider()
        self.vector_store = VectorStore(embedding_provider=self.embedder)

    def run(self) -> Dict[str, Any]:
        """Execute documentation ingestion."""
        logger.info("Starting documentation ingestion pipeline from %s", self.repo_root)
        start_time = datetime.datetime.now(datetime.timezone.utc)

        sources = doc_sources(self.repo_root)
        source_print = fingerprint(sources)
        all_chunks: List[DocChunk] = []
        files_failed: List[str] = []

        for path in sources:
            rel_path = str(path.relative_to(self.repo_root)).replace("\\", "/")
            try:
                if path.suffix.lower() == ".docx":
                    # Sanitized like every other source; .docx content used to
                    # go into the index unscrubbed.
                    chunks = DocxParser.parse_file(rel_path, path, sanitize=sanitize_content)
                else:
                    content = sanitize_content(path.read_text(encoding="utf-8", errors="replace"))
                    chunks = MarkdownDocParser.parse_file(rel_path, content)
                all_chunks.extend(chunks)
            except Exception as e:
                logger.error("Failed to parse document %s: %s", rel_path, e)
                files_failed.append(f"{rel_path}: {e}")

        self.vector_store.add_chunks([c.to_dict() for c in all_chunks])
        self.vector_store.save(self.output_dir, manifest={
            "schema_version": INDEX_SCHEMA_VERSION,
            "fingerprint": source_print,
        })

        end_time = datetime.datetime.now(datetime.timezone.utc)
        duration_s = (end_time - start_time).total_seconds()
        report = {
            "ingestion_timestamp": end_time.isoformat(),
            "duration_seconds": round(duration_s, 2),
            "files_discovered": len(sources),
            "files_indexed": len(sources) - len(files_failed),
            "files_failed": files_failed,
            "chunks_created": len(all_chunks),
            "embedding_model": getattr(self.embedder, "name", type(self.embedder).__name__),
            "schema_version": INDEX_SCHEMA_VERSION,
            "vector_store": "FAISS-IndexFlatIP",
            "output_directory": str(self.output_dir),
        }
        with open(self.output_dir / "doc_ingestion_report.json", "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)

        logger.info(
            "Doc Ingestion complete: %s files indexed, %s chunks created in %ss",
            report["files_indexed"], len(all_chunks), round(duration_s, 2),
        )
        return report


def run_doc_ingestion(embedder: Optional[BaseEmbeddings] = None) -> Dict[str, Any]:
    """Helper to run doc ingestion using configured paths."""
    pipeline = DocumentationIngestionPipeline(
        repo_root=WORKSPACE_DIR, output_dir=ai_settings.doc_index_path, embedder=embedder,
    )
    return pipeline.run()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    rep = run_doc_ingestion()
    print(json.dumps(rep, indent=2))
