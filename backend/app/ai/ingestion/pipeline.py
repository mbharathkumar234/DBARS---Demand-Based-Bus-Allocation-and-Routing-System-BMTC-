from __future__ import annotations

import datetime
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.ai.config import WORKSPACE_DIR, ai_settings
from app.ai.ingestion.code_parser import (
    CodeChunk,
    GenericFileParser,
    PythonCodeParser,
    TypeScriptCodeParser,
)
from app.ai.ingestion.freshness import INDEX_SCHEMA_VERSION, code_sources, fingerprint
from app.ai.rag.embeddings import BaseEmbeddings, get_embedding_provider
from app.ai.rag.vector_store import VectorStore
from app.ai.security.secret_filter import sanitize_content

logger = logging.getLogger("bmtc-ai-ingestion")


class CodebaseIngestionPipeline:
    """Discovers, parses, chunks, and indexes the entire DBARS codebase."""

    def __init__(self, repo_root: Path, output_dir: Path, embedder: Optional[BaseEmbeddings] = None) -> None:
        self.repo_root = repo_root.resolve()
        self.output_dir = output_dir.resolve()
        self.embedder = embedder or get_embedding_provider()
        self.vector_store = VectorStore(embedding_provider=self.embedder)

    def run(self) -> Dict[str, Any]:
        """Execute full codebase ingestion."""
        logger.info("Starting codebase ingestion pipeline from %s", self.repo_root)
        start_time = datetime.datetime.now(datetime.timezone.utc)

        sources = list(code_sources(self.repo_root))
        source_print = fingerprint(sources)
        files_failed: List[str] = []
        all_chunks: List[CodeChunk] = []

        for path in sources:
            rel_path = str(path.relative_to(self.repo_root)).replace("\\", "/")
            suffix = path.suffix.lower()
            try:
                sanitized = sanitize_content(path.read_text(encoding="utf-8", errors="replace"))
                if suffix == ".py":
                    chunks = PythonCodeParser.parse_file(rel_path, sanitized)
                elif suffix in {".ts", ".tsx"}:
                    chunks = TypeScriptCodeParser.parse_file(rel_path, sanitized)
                else:
                    chunks = GenericFileParser.parse_file(rel_path, sanitized, language=suffix.lstrip(".") or "config")
                all_chunks.extend(chunks)
            except Exception as e:
                logger.error("Failed to parse %s: %s", rel_path, e)
                files_failed.append(f"{rel_path}: {str(e)}")

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
            "files_indexed": len(sources) - len(files_failed),
            "chunks_created": len(all_chunks),
            "files_failed": files_failed,
            "embedding_model": getattr(self.embedder, "name", type(self.embedder).__name__),
            "schema_version": INDEX_SCHEMA_VERSION,
            "vector_store": "FAISS-IndexFlatIP",
            "output_directory": str(self.output_dir),
        }
        with open(self.output_dir / "code_ingestion_report.json", "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)

        logger.info(
            "Ingestion complete: %s files indexed, %s chunks created in %ss",
            report["files_indexed"], len(all_chunks), round(duration_s, 2),
        )
        return report


def run_codebase_ingestion(embedder: Optional[BaseEmbeddings] = None) -> Dict[str, Any]:
    """Helper to run ingestion using workspace paths."""
    pipeline = CodebaseIngestionPipeline(
        repo_root=WORKSPACE_DIR, output_dir=ai_settings.code_index_path, embedder=embedder,
    )
    return pipeline.run()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    rep = run_codebase_ingestion()
    print(json.dumps(rep, indent=2))
