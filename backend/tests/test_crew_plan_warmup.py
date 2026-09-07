"""Regression tests for crew-plan warm-up and key mapping.

Reported as "to answer this question it took more than 10 to 15 seconds" for
"What is the crew-to-bus ratio and duties required?".

Two causes:

1. **The crew plan was never warmed.** The lifespan warms the blocking plan and
   the GTFS feed, but not crew duties, so the first depot question paid the
   whole computation inline: ~5.6s rebuilding the blocking context plus ~7.6s
   scheduling the crew.

2. **The context cache next door was bypassed.** `get_crew_plan` called
   `_build_context()` directly instead of reusing
   `blocking_plan_service._context`, so it rebuilt a 5.6s structure that was
   already in memory.

Fixing the latency exposed a third defect: the tool read `duties_required`,
`two_shift_duties` and `single_shift_duties`, none of which
`app/ml/crew.py summarize()` returns. The assistant reported "Total Duties
Required: None" while the real figure, 15,636, sat under `duties`.
"""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from app.ai.tools.registry import tool_registry
from app.main import create_app
from app.services.crew_service import crew_plan_service
from app.services.blocking_service import blocking_plan_service


@pytest.fixture(scope="module")
def warmed_app():
    app = create_app()
    with TestClient(app) as client:
        yield app, client


def test_startup_warms_the_crew_plan(warmed_app) -> None:
    """Without this the first depot question pays ~13s inline.

    The warm-up is fire-and-forget, so it is still running when startup
    returns -- that is the point, it must not delay the app becoming ready.
    Polling here waits for it to land while giving the event loop time to run.
    """
    _, client = warmed_app
    deadline = time.monotonic() + 180
    while crew_plan_service._plan is None and time.monotonic() < deadline:
        client.get("/health")  # lets the background warm task make progress
        time.sleep(1)

    assert crew_plan_service._plan is not None, (
        "the crew plan was never warmed; the first crew question will "
        "recompute it inline"
    )


def test_startup_leaves_the_blocking_context_cached(warmed_app) -> None:
    """The crew warm-up runs after blocking so it reuses the built context."""
    assert blocking_plan_service._context is not None


def test_crew_tool_reports_the_real_duty_count(warmed_app) -> None:
    record = tool_registry.execute_tool("get_crew_plan")
    assert record.status == "success"
    output = record.output

    duties = output.get("total_duties_required")
    assert duties is not None, "total duties came back as None -- key mapping is wrong again"
    assert isinstance(duties, int) and duties > 0


def test_crew_tool_keys_match_what_summarize_returns(warmed_app) -> None:
    """Guards against reintroducing keys the crew summary does not produce."""
    record = tool_registry.execute_tool("get_crew_plan")
    output = record.output
    network = crew_plan_service._plan["network"]

    assert output["total_duties_required"] == network["duties"]
    assert output["crew_to_bus_ratio"] == network["crew_to_bus_ratio"]
    assert output["blocks_staffed"] == network["blocks"]


def test_crew_ratio_is_consistent_with_duties_and_blocks(warmed_app) -> None:
    record = tool_registry.execute_tool("get_crew_plan")
    output = record.output
    expected = round(output["total_duties_required"] / output["blocks_staffed"], 2)
    assert output["crew_to_bus_ratio"] == pytest.approx(expected, abs=0.01)


def test_a_warmed_crew_question_is_fast(warmed_app) -> None:
    """With the plan warm the tool is a dictionary read, not a computation."""
    record = tool_registry.execute_tool("get_crew_plan")
    assert record.execution_time_ms < 500, (
        f"crew tool took {record.execution_time_ms}ms; it should be reading a "
        "warmed plan, not recomputing"
    )
