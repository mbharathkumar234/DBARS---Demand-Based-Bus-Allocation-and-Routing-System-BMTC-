"""Shared test fixtures.

The AI layer's tools are role-restricted (see app/ai/security/authorization.py).
Tests that drive agents or the tool registry directly -- rather than through
the HTTP API, which derives the principal from the bearer token -- have no
principal bound and would fail closed. This binds a staff principal for those
in-process calls.

It does not weaken the API-level checks: authentication on /ai/* is enforced by
FastAPI dependencies, so an unauthenticated request still gets 401 regardless of
what is bound here. Tests that assert a *denial* bind their own principal, which
overrides this one for the duration of the test.
"""

from __future__ import annotations

import os

# Pin the AI layer to its offline model BEFORE anything imports app.ai.config,
# whose settings are read from the environment once at import time. A developer
# with GEMINI_API_KEY in .env would otherwise make ~100 live API calls per test
# run: slow, billable, and dependent on network and quota. Tests assert the
# layer's retrieval, grounding and authorization behaviour, none of which
# should hinge on a remote model being reachable.
os.environ["LLM_PROVIDER"] = "offline"

import pytest

from app.ai.security.authorization import AIPrincipal, reset_ai_principal, set_ai_principal


@pytest.fixture(autouse=True)
def _staff_ai_principal():
    """Bind an admin principal for direct (non-HTTP) AI tool and agent calls."""
    token = set_ai_principal(AIPrincipal(user_id="test-harness", role="admin"))
    try:
        yield
    finally:
        reset_ai_principal(token)
