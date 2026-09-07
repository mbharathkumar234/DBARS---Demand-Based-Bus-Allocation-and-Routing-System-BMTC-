from __future__ import annotations

import re
from pathlib import Path
from typing import Set

# Paths and patterns that MUST NEVER be indexed or ingested
EXCLUDED_DIR_NAMES: Set[str] = {
    ".git",
    ".github",
    ".idea",
    ".vscode",
    ".claude",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".pytest_tmp",
    "dist",
    "build",
    "android",
    "artifacts",
}

EXCLUDED_FILE_EXTENSIONS: Set[str] = {
    ".env",
    ".pyc",
    ".pyo",
    ".pyd",
    ".db",
    ".sqlite",
    ".sqlite3",
    ".zip",
    ".tar",
    ".gz",
    ".pb",
    ".pdf",
    ".exe",
    ".dll",
    ".so",
    ".bin",
    ".png",
    ".jpg",
    ".jpeg",
    ".ico",
    ".gif",
    ".svg",
    ".woff",
    ".woff2",
    ".ttf",
    ".eot",
    ".xlsx",
    ".csv",  # Cleaned datasets are ingested separately if needed, not as raw code chunks
}

EXCLUDED_FILE_NAMES: Set[str] = {
    ".env",
    ".env.local",
    ".env.production",
    "id_rsa",
    "id_rsa.pub",
    "package-lock.json",
    "tsconfig.tsbuildinfo",
}

# Regex to detect API keys, tokens, or private secrets in file content
SECRET_PATTERNS = [
    re.compile(r"(?i)(?:api_key|apikey|secret_key|private_key|auth_token|jwt_secret)\s*[:=]\s*['\"][a-zA-Z0-9_\-]{16,}['\"]"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"AIza[0-9A-Za-z-_]{35}"),  # Google API key, legacy format
    re.compile(r"\bAQ\.[A-Za-z0-9_\-]{20,}\b"),  # Google AI Studio, current format
]


def is_path_safe_to_index(path: Path, repo_root: Path) -> bool:
    """Determine if a file path is safe to index (excludes build artifacts, venvs, secrets)."""
    try:
        rel_path = path.resolve().relative_to(repo_root.resolve())
    except ValueError:
        return False

    # Check directory components
    for part in rel_path.parts[:-1]:
        if part in EXCLUDED_DIR_NAMES:
            return False

    filename = path.name.lower()
    if filename in EXCLUDED_FILE_NAMES or filename.startswith(".env"):
        return False

    suffix = path.suffix.lower()
    if suffix in EXCLUDED_FILE_EXTENSIONS:
        return False

    return True


def sanitize_content(content: str) -> str:
    """Scrub potential accidental secrets or sensitive tokens from text content."""
    sanitized = content
    for pattern in SECRET_PATTERNS:
        sanitized = pattern.sub("[REDACTED_SECRET]", sanitized)
    return sanitized
