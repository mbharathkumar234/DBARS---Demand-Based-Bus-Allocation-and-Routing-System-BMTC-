"""Everything the assistant states as fact about the code must exist in the code.

The curated topic answers named `backend/app/api/predict.py`,
`services/transit_service.py`, `tracking/simulator.py`, `WaybillService`,
`validate_pass` and `get_database` -- none of which existed -- and said vehicle
blocking used the Hungarian algorithm and passwords used bcrypt. The grounding
verifier's whitelist confirmed sixteen invented symbols. All of it was reported
as CONFIRMED. These tests fail the moment a curated answer or the whitelist
names something the repository does not contain.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

import pytest

from app.ai.agents.codebase_agent import TOPICS
from app.ai.security.grounding_verifier import KNOWN_CORE_SYMBOLS

REPO = Path(__file__).resolve().parents[2]
SOURCE_DIRS = [REPO / "backend" / "app", REPO / "frontend" / "src"]
# Files that talk about the code rather than being it.
SELF_REFERENTIAL = ("codebase_agent.py", "grounding_verifier.py", "/evaluation/")

_BACKTICKED = re.compile(r"`([^`]+)`")
_ENDPOINT = re.compile(r"^(GET|POST|PUT|DELETE|PATCH) (/[\w/{}\-.]*)$")


@lru_cache(maxsize=1)
def _source_text() -> str:
    parts = []
    for root in SOURCE_DIRS:
        for path in root.rglob("*"):
            if path.suffix not in {".py", ".ts", ".tsx"} or "__pycache__" in path.parts:
                continue
            if any(mark in path.as_posix() for mark in SELF_REFERENTIAL):
                continue
            parts.append(path.read_text(encoding="utf-8", errors="replace"))
    return "\n".join(parts)


@lru_cache(maxsize=1)
def _route_paths() -> set:
    from app.main import create_app
    return {getattr(r, "path", "") for r in create_app().routes}


def _route_exists(path: str) -> bool:
    prefix = path.rstrip("*").rstrip("/") or "/"
    return any(p == prefix or p.startswith(prefix + "/") for p in _route_paths())


@lru_cache(maxsize=1)
def _repo_paths() -> tuple:
    return tuple(
        p.relative_to(REPO).as_posix()
        for root in (REPO / "backend", REPO / "frontend" / "src", REPO / "docs")
        for p in root.rglob("*")
        if ".venv" not in p.parts and "node_modules" not in p.parts
    )


def _path_exists(token: str) -> bool:
    """A repo-relative path, or the shorthand `api/routes.py` for a file under one of the source roots."""
    if (REPO / token).exists():
        return True
    suffix = "/" + token.rstrip("/")
    return any(p.endswith(suffix) for p in _repo_paths())


def _topic_texts():
    for index, topic in enumerate(TOPICS):
        for text in (topic.direct, topic.reasoning, *topic.flow):
            yield index, text


def _claims():
    for index, text in _topic_texts():
        for token in _BACKTICKED.findall(text):
            yield index, token


@pytest.mark.parametrize("index,path", [(i, f) for i, t in enumerate(TOPICS) for f in t.files])
def test_topic_files_exist(index: int, path: str) -> None:
    assert (REPO / path).is_file(), f"topic {index} names {path}, which does not exist"


@pytest.mark.parametrize("index,token", list(_claims()))
def test_backticked_claims_exist(index: int, token: str) -> None:
    endpoint = _ENDPOINT.match(token)
    if endpoint or token.startswith("/"):
        path = endpoint.group(2) if endpoint else token
        assert _route_exists(path), f"topic {index} names endpoint {token}, which the app does not register"
        return
    if "/" in token:
        assert _path_exists(token), f"topic {index} names {token}, which does not exist"
        return
    if token.endswith((".csv", ".txt")):
        return
    # `Depends(require_role(...))`, `app.state.predictor.predict(...)`: check each name.
    for name in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", token):
        if name in {"Depends", "app", "state"} or name.isupper():
            continue
        assert re.search(rf"\b{re.escape(name)}\b", _source_text()), (
            f"topic {index} names `{name}` (in `{token}`), which appears nowhere in the code"
        )


@pytest.mark.parametrize("symbol", KNOWN_CORE_SYMBOLS)
def test_verifier_whitelist_symbols_exist(symbol: str) -> None:
    assert re.search(rf"\b{re.escape(symbol)}\b", _source_text(), re.I), (
        f"grounding verifier whitelists `{symbol}`, which appears nowhere in the code"
    )


def test_blocking_is_not_described_as_an_assignment_solver() -> None:
    blocking = next(t for t in TOPICS if "blocking" in t.keywords)
    assert "not a Hungarian" in blocking.direct
    assert "linear_sum_assignment" not in _source_text()


@pytest.mark.parametrize(
    "query,matches",
    [
        ("how do I restart the tracking simulator", "tracking"),  # not "start"
        ("who is the author of this module", None),  # not "auth"
        ("where does the application start?", "start"),
    ],
)
def test_topics_match_whole_words(query: str, matches) -> None:
    from app.ai.agents.codebase_agent import CodebaseAssistant

    topic = CodebaseAssistant._match_topic(query.lower())
    if matches is None:
        assert topic is None
    else:
        assert topic is not None and matches in topic.keywords
