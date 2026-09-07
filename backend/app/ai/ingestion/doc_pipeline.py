from __future__ import annotations

import datetime
import json
import logging
from pathlib import Path
from typing import Any, Dict, List

from app.ai.config import ai_settings
from app.ai.ingestion.doc_parser import DocChunk, DocxParser, MarkdownDocParser
from app.ai.rag.embeddings import get_embedding_provider
from app.ai.rag.vector_store import VectorStore
from app.ai.security.secret_filter import sanitize_content

logger = logging.getLogger("bmtc-ai-doc-ingestion")


class DocumentationIngestionPipeline:
    """Discovers, parses, chunks, and indexes all DBARS documentation."""

    def __init__(self, repo_root: Path, output_dir: Path) -> None:
        self.repo_root = repo_root.resolve()
        self.output_dir = output_dir.resolve()
        self.embedder = get_embedding_provider()
        self.vector_store = VectorStore(embedding_provider=self.embedder)

    def run(self) -> Dict[str, Any]:
        """Execute documentation ingestion."""
        logger.info("Starting documentation ingestion pipeline from %s", self.repo_root)
        start_time = datetime.datetime.now(datetime.timezone.utc)

        files_discovered = 0
        files_indexed = 0
        all_chunks: List[DocChunk] = []

        # 1. Target files and directories
        doc_targets: List[Path] = [
            self.repo_root / "README.md",
        ]

        docs_dir = self.repo_root / "docs"
        if docs_dir.exists():
            for p in docs_dir.rglob("*"):
                if p.is_file() and p.suffix.lower() in {".md", ".docx", ".py"}:
                    doc_targets.append(p)

        for path in doc_targets:
            if not path.exists() or not path.is_file():
                continue
            files_discovered += 1
            rel_path = str(path.relative_to(self.repo_root)).replace("\\", "/")

            suffix = path.suffix.lower()
            try:
                if suffix == ".docx":
                    chunks = DocxParser.parse_file(rel_path, path)
                elif suffix == ".md":
                    content = path.read_text(encoding="utf-8", errors="replace")
                    sanitized = sanitize_content(content)
                    chunks = MarkdownDocParser.parse_file(rel_path, sanitized)
                elif suffix == ".py":
                    # Parse build doc scripts as supplemental documentation
                    content = path.read_text(encoding="utf-8", errors="replace")
                    sanitized = sanitize_content(content)
                    chunks = MarkdownDocParser.parse_file(rel_path, sanitized)
                else:
                    continue

                all_chunks.extend(chunks)
                files_indexed += 1
            except Exception as e:
                logger.error("Failed to parse document %s: %s", rel_path, e)

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
            "embedding_model": getattr(self.embedder, "name", type(self.embedder).__name__),
            "vector_store": "FAISS-IndexFlatIP",
            "output_directory": str(self.output_dir),
        }

        report_path = self.output_dir / "doc_ingestion_report.json"
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)

        logger.info(
            "Doc Ingestion complete: %s files indexed, %s chunks created in %ss",
            files_indexed,
            len(all_chunks),
            round(duration_s, 2),
        )
        return report


def run_doc_ingestion() -> Dict[str, Any]:
    """Helper to run doc ingestion using configured paths."""
    repo_root = ai_settings.doc_index_path.parent.parent.parent.parent
    output_dir = ai_settings.doc_index_path
    pipeline = DocumentationIngestionPipeline(repo_root=repo_root, output_dir=output_dir)
    return pipeline.run()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    rep = run_doc_ingestion()
    print(json.dumps(rep, indent=2))
