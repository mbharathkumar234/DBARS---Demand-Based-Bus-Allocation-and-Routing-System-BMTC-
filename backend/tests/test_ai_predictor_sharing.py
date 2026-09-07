"""The AI tool layer must reuse the application's trained predictor.

`get_shared_predictor()` falls back to constructing and training its own
instance when nobody injects one, and for a while nobody did:
`set_shared_predictor` was exported but never called. The first chat request of
each process therefore paid a full training run -- about 7 seconds, which is
what a user saw as an ~8-10 second reply -- and the process then carried a
second complete index, roughly 900MB, for the rest of its life.

The cost is invisible after the first request, so a plain latency test would
not catch a regression. These assert the wiring instead.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.ai.tools.routing_tools import get_shared_predictor, set_shared_predictor
from app.main import create_app


def test_startup_injects_the_application_predictor() -> None:
    app = create_app()
    with TestClient(app):
        shared = get_shared_predictor()
        assert shared is app.state.predictor, (
            "the AI tool layer built its own predictor instead of reusing the "
            "one the application already trained"
        )


def test_the_shared_predictor_is_already_trained() -> None:
    """Reusing an untrained instance would just move the cost, not remove it."""
    app = create_app()
    with TestClient(app):
        assert get_shared_predictor().ready


def test_injection_is_honoured(monkeypatch: pytest.MonkeyPatch) -> None:
    """The accessor must prefer an injected predictor over building one."""
    sentinel = object()
    import app.ai.tools.routing_tools as routing_tools

    original = routing_tools._shared_predictor
    try:
        set_shared_predictor(sentinel)  # type: ignore[arg-type]
        assert get_shared_predictor() is sentinel
    finally:
        routing_tools._shared_predictor = original
