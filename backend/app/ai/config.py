from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


AI_DIR = Path(__file__).resolve().parent
BACKEND_DIR = AI_DIR.parent.parent
WORKSPACE_DIR = BACKEND_DIR.parent

# Load .env here rather than relying on app.core.config having been imported
# first. AISettings reads os.getenv in its field defaults, which are evaluated
# once when this module is imported -- so if that happened before anything
# loaded .env, every setting silently fell back to its default and
# GEMINI_API_KEY read as empty, quietly selecting the offline model. Mirrors
# app/core/config.py; load_dotenv does not override variables already set.
load_dotenv(BACKEND_DIR / ".env")
load_dotenv(WORKSPACE_DIR / ".env")


@dataclass(frozen=True)
class AISettings:
    """Settings dedicated to the AI Intelligence Layer."""

    # General AI Configuration
    enabled: bool = os.getenv("AI_ENABLED", "true").strip().lower() == "true"
    environment: str = os.getenv("ENV", "development").lower()

    # Provider & Model Settings
    llm_provider: str = os.getenv("LLM_PROVIDER", "auto")  # auto | gemini | openai | offline
    model_name: str = os.getenv("AI_MODEL_NAME", "gemini-3.6-flash")
    embedding_model: str = os.getenv("AI_EMBEDDING_MODEL", "all-MiniLM-L6-v2")
    embedding_provider: str = os.getenv("AI_EMBEDDING_PROVIDER", "deterministic")
    temperature: float = float(os.getenv("AI_TEMPERATURE", "0.2"))
    max_tokens: int = int(os.getenv("AI_MAX_TOKENS", "2048"))

    # API Keys (read safely from environment)
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", os.getenv("GOOGLE_API_KEY", ""))
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")

    # Storage & Indices
    index_storage_dir: Path = Path(os.getenv("AI_INDEX_DIR", BACKEND_DIR / "artifacts" / "ai_indices"))
    code_index_path: Path = Path(os.getenv("AI_CODE_INDEX_PATH", BACKEND_DIR / "artifacts" / "ai_indices" / "code_index"))
    doc_index_path: Path = Path(os.getenv("AI_DOC_INDEX_PATH", BACKEND_DIR / "artifacts" / "ai_indices" / "doc_index"))

    # Security & Guardrails
    max_query_length: int = int(os.getenv("AI_MAX_QUERY_LENGTH", "1000"))
    max_context_length: int = int(os.getenv("AI_MAX_CONTEXT_LENGTH", "8000"))
    session_history_limit: int = int(os.getenv("AI_SESSION_HISTORY_LIMIT", "10"))
    enable_prompt_guardrails: bool = os.getenv("AI_ENABLE_PROMPT_GUARDRAILS", "true").strip().lower() == "true"


ai_settings = AISettings()
