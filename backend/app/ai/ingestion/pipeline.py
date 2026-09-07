from __future__ import annotations

import datetime
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Set

from app.ai.config import ai_settings
from app.ai.ingestion.code_parser import (
    CodeChunk,
    GenericFileParser,
    PythonCodeParser,
    TypeScriptCodeParser,
)
from app.ai.rag.embeddings import get_embedding_provider
from app.ai.rag.vector_store import VectorStore
from app.ai.security.secret_filter import is_path_safe_to_index, sanitize_content

logger = logging.getLogger("bmtc-ai-ingestion")


class CodebaseIngestionPipeline:
    """Discovers, parses, chunks, and indexes the entire DBARS codebase."""

    def __init__(self, repo_root: Path, output_dir: Path) -> None:
        self.repo_root = repo_root.resolve()
        self.output_dir = output_dir.resolve()
        self.embedder = get_embedding_provider()
        self.vector_store = VectorStore(embedding_provider=self.embedder)

    def run(self) -> Dict[str, Any]:
        """Execute full codebase ingestion."""
        logger.info("Starting codebase ingestion pipeline from %s", self.repo_root)
        start_time = datetime.datetime.now(datetime.timezone.utc)

        files_discovered = 0
        files_indexed = 0
        files_excluded = 0
        files_failed: List[str] = []
        all_chunks: List[CodeChunk] = []

        for path in self.repo_root.rglob("*"):
            if not path.is_file():
                continue
            files_discovered += 1

            if not is_path_safe_to_index(path, self.repo_root):
                files_excluded += 1
                continue

            rel_path = str(path.relative_to(self.repo_root)).replace("\\", "/")

            # Filter for codebase relevant files
            suffix = path.suffix.lower()
            if suffix not in {".py", ".ts", ".tsx", ".json", ".ini", ".md", ".yml", ".yaml", ".bat", ".ps1"}:
                if path.name not in {"Dockerfile", "README.md"}:
                    files_excluded += 1
                    continue

            try:
                content = path.read_text(encoding="utf-8", errors="replace")
                sanitized = sanitize_content(content)

                if suffix == ".py":
                    chunks = PythonCodeParser.parse_file(rel_path, sanitized)
                elif suffix in {".ts", ".tsx"}:
                    chunks = TypeScriptCodeParser.parse_file(rel_path, sanitized)
                else:
                    chunks = GenericFileParser.parse_file(rel_path, sanitized, language=suffix.lstrip("."))

                all_chunks.extend(chunks)
                files_indexed += 1
            except Exception as e:
                logger.error("Failed to parse %s: %s", rel_path, e)
                files_failed.append(f"{rel_path}: {str(e)}")

        # Index chunks into VectorStore
        chunk_dicts = [c.to_dict() for c in all_chunks]
        self.vector_store.add_chunks(chunk_dicts)
        self.vector_store.save(self.output_dir)

        end_time = datetime.datetime.now(datetime.timezone.utc)
        duration_s = (end_time - start_time).total_seconds()

        report = {
            "ingestion_timestamp": end_time.isoformat(),
            "duration_seconds": round(duration_s, 2),
            "files_discovered": files_discovered,
            "files_indexed": files_indexed,
            "chunks_created": len(all_chunks),
            "files_excluded": files_excluded,
            "files_failed": files_failed,
            # Reported from the embedder actually used. This was a hardcoded
            # string, so the report claimed hashed embeddings even after the
            # index had been rebuilt with sentence-transformers.
            "embedding_model": getattr(self.embedder, "name", type(self.embedder).__name__),
            "vector_store": "FAISS-IndexFlatIP",
            "output_directory": str(self.output_dir),
        }

        # Write report to disk
        report_path = self.output_dir / "code_ingestion_report.json"
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)

        logger.info(
            "Ingestion complete: %s files indexed, %s chunks created, %s excluded in %ss",
            files_indexed,
            len(all_chunks),
            files_excluded,
            round(duration_s, 2),
        )
        return report


def run_codebase_ingestion() -> Dict[str, Any]:
    """Helper to run ingestion using workspace paths."""
    repo_root = ai_settings.code_index_path.parent.parent.parent.parent  # s6/dbars
    output_dir = ai_settings.code_index_path
    pipeline = CodebaseIngestionPipeline(repo_root=repo_root, output_dir=output_dir)
    return pipeline.run()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    rep = run_codebase_ingestion()
    print(json.dumps(rep, indent=2))
