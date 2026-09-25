"""Which files each index covers, and whether an index still matches them.

The indices are build artifacts (gitignored) that nothing rebuilt: the one in
use in September 2026 predated three commits, and a fresh clone had no index
at all. Retrieval now checks, on first use and at startup, that
the index on disk was built by this chunker version, with this embedding
provider, from these files -- and rebuilds when it was not.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from app.ai.security.secret_filter import EXCLUDED_DIR_NAMES, is_path_safe_to_index

logger = logging.getLogger("bmtc-ai-index")

# Bump whenever chunking or indexed text changes shape. An index built by an
# older chunker is not wrong-looking -- it loads and answers -- it is just
# quietly worse, so the version is what forces the rebuild.
INDEX_SCHEMA_VERSION = 4
MANIFEST_NAME = "index_manifest.json"

CODE_SUFFIXES = {".py", ".ts", ".tsx", ".json", ".ini", ".md", ".yml", ".yaml", ".bat", ".ps1"}
CODE_NAMES = {"Dockerfile", "README.md"}

# Evaluation datasets: questions paired with their expected answers. Indexed,
# they are the best lexical match for every benchmark question -- the index
# would be grading itself on its own answer key.
FIXTURE_PATHS = {
    "backend/app/ai/evaluation/dataset.py",
    "backend/app/ai/evaluation/retrieval_benchmark.py",
}


def code_sources(repo_root: Path) -> Iterator[Path]:
    """Files the code index covers. Excluded directories are pruned, not
    filtered afterwards: walking node_modules to discard it was 33k stat calls."""
    root = repo_root.resolve()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in EXCLUDED_DIR_NAMES)
        for name in sorted(filenames):
            path = Path(dirpath) / name
            if path.suffix.lower() not in CODE_SUFFIXES and name not in CODE_NAMES:
                continue
            if path.relative_to(root).as_posix() in FIXTURE_PATHS:
                continue
            if is_path_safe_to_index(path, root):
                yield path


def doc_sources(repo_root: Path) -> List[Path]:
    """Files the documentation index covers.

    ``docs/build/*.py`` are the scripts that generate the .docx files; indexing
    them duplicated every document as a single 16-56k character chunk.
    Underscore-prefixed files are scratch output (``_smoke.docx``).
    """
    root = repo_root.resolve()
    targets = [root / "README.md"]
    docs_dir = root / "docs"
    if docs_dir.exists():
        for path in sorted(docs_dir.rglob("*")):
            rel_parts = path.relative_to(docs_dir).parts
            if not path.is_file() or path.name.startswith(("_", "~$")):
                continue
            if "build" in rel_parts[:-1]:
                continue
            if path.suffix.lower() in {".md", ".docx"}:
                targets.append(path)
    return [p for p in targets if p.is_file()]


def fingerprint(paths: List[Path]) -> Dict[str, Any]:
    latest = 0.0
    for path in paths:
        try:
            latest = max(latest, path.stat().st_mtime)
        except OSError:
            continue
    return {"files": len(paths), "latest_mtime": round(latest, 3)}


def read_manifest(index_dir: Path) -> Optional[Dict[str, Any]]:
    try:
        with open(index_dir / MANIFEST_NAME, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def index_status(index_dir: Path, sources: List[Path], provider_name: str) -> str:
    """fresh | missing | incompatible | stale"""
    if not (index_dir / "index.faiss").exists() or not (index_dir / "metadata.json").exists():
        return "missing"
    manifest = read_manifest(index_dir)
    if not manifest or manifest.get("schema_version") != INDEX_SCHEMA_VERSION:
        return "incompatible"
    if manifest.get("provider") != provider_name:
        return "incompatible"
    built = manifest.get("fingerprint") or {}
    current = fingerprint(sources)
    if current["files"] != built.get("files") or current["latest_mtime"] > float(built.get("latest_mtime", 0)):
        return "stale"
    return "fresh"


_lock = threading.Lock()
_background: Optional[threading.Thread] = None


def ensure_indices(block_on_stale: bool = False) -> Dict[str, str]:
    """Bring both indices up to date.

    A missing or incompatible index is rebuilt synchronously: there is nothing
    correct to serve until it exists. A merely stale one (sources edited since
    the build) keeps serving while a background thread rebuilds it, unless
    ``block_on_stale`` is set.
    """
    from app.ai.config import ai_settings
    from app.ai.rag.embeddings import get_embedding_provider

    global _background
    with _lock:
        embedder = get_embedding_provider()
        provider = getattr(embedder, "name", type(embedder).__name__)
        repo_root = ai_settings.code_index_path.parents[3]
        plan = {
            "code": index_status(ai_settings.code_index_path, list(code_sources(repo_root)), provider),
            "doc": index_status(ai_settings.doc_index_path, doc_sources(repo_root), provider),
        }
        urgent = [kind for kind, state in plan.items() if state in ("missing", "incompatible")]
        stale = [kind for kind, state in plan.items() if state == "stale"]

        if urgent or (stale and block_on_stale):
            _rebuild(urgent + (stale if block_on_stale else []), embedder)
        if stale and not block_on_stale and not (_background and _background.is_alive()):
            _background = threading.Thread(
                target=_rebuild, args=(stale, None), name="ai-index-refresh", daemon=True,
            )
            _background.start()
        return plan


def _rebuild(kinds: List[str], embedder) -> None:
    from app.ai.ingestion.doc_pipeline import run_doc_ingestion
    from app.ai.ingestion.pipeline import run_codebase_ingestion

    for kind in kinds:
        started = time.perf_counter()
        try:
            report = run_codebase_ingestion(embedder) if kind == "code" else run_doc_ingestion(embedder)
            logger.info(
                "Rebuilt %s index: %s chunks in %.1fs", kind, report.get("chunks_created"),
                time.perf_counter() - started,
            )
        except Exception:
            logger.exception("Rebuilding the %s index failed; retrieval keeps the previous one", kind)
            continue
        from app.ai.rag.hybrid_retriever import hybrid_retriever
        hybrid_retriever.reload(kind)
