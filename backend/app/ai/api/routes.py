from __future__ import annotations

import logging
from fastapi import APIRouter, Depends, HTTPException, status

from app.auth.auth import UserRole, get_current_user, require_role
from app.ai.security.authorization import AIPrincipal, reset_ai_principal, set_ai_principal

from app.ai.models import (
    AIChatRequest,
    AIChatResponse,
    AIHealthResponse,
    SessionClearRequest,
    SessionClearResponse,
    SessionHistoryResponse,
)
from app.ai.memory.session_memory import session_memory
from app.ai.services.ai_service import ai_service
from typing import Optional

logger = logging.getLogger("bmtc-ai")

router = APIRouter(prefix="/ai", tags=["AI Intelligence Layer"])


@router.get("/health", response_model=AIHealthResponse, summary="Check AI Subsystem Health")
async def ai_health() -> AIHealthResponse:
    """Returns operational status and index readiness of the AI layer."""
    try:
        return await ai_service.get_health()
    except Exception as e:
        logger.exception("Error checking AI health: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"AI subsystem health check failed: {str(e)}",
        )


@router.post("/chat", response_model=AIChatResponse, summary="Query the DBARS AI Assistant")
async def ai_chat(
    request: AIChatRequest,
    user: dict = Depends(get_current_user),
) -> AIChatResponse:
    """Submit a natural language question about the codebase, documentation, or transit queries.

    All responses are strictly grounded in retrieved source code, project documents,
    or live deterministic DBARS tool outputs.

    Requires authentication. The assistant reaches the same services the REST API
    does, so leaving it open made it a side door around `require_role()`: an
    anonymous caller could read depot fleet figures that GET /depot/blocking-plan
    refuses with 401. Identity and role are taken from the verified token; any
    `user_id` in the body is ignored, since a client could otherwise claim to be
    anyone and read another commuter's saved journey.
    """
    request.user_id = str(user.get("sub") or user.get("email") or "")
    principal = AIPrincipal(user_id=request.user_id, role=str(user.get("role", "")))
    token = set_ai_principal(principal)
    try:
        return await ai_service.process_chat(request)
    except Exception as e:
        logger.exception("Error processing AI chat query: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to process AI query: {str(e)}",
        )
    finally:
        reset_ai_principal(token)


@router.post("/session/clear", response_model=SessionClearResponse, summary="Clear conversational session memory")
async def clear_session(
    request: SessionClearRequest,
    user: dict = Depends(get_current_user),
) -> SessionClearResponse:
    """Explicitly resets and clears conversation history and journey context for a session.

    The owning user is taken from the token, so one caller cannot clear another
    caller's session by naming their user_id in the body.
    """
    owner_id = str(user.get("sub") or user.get("email") or "")
    cleared = session_memory.clear_session(request.session_id, user_id=owner_id)
    return SessionClearResponse(
        session_id=request.session_id,
        cleared=cleared,
        message="Session memory successfully cleared" if cleared else "Session was already empty or not found",
    )


@router.get("/session/{session_id}/history", response_model=SessionHistoryResponse, summary="Get session history and context")
async def get_session_history(
    session_id: str,
    user: dict = Depends(get_current_user),
) -> SessionHistoryResponse:
    """Inspects sanitized conversation history turns and active journey context for a session.

    Scoped to the authenticated caller. Previously both `session_id` and
    `user_id` came from the client, so anyone who supplied a matching pair read
    that user's conversation and journey context -- origin and destination
    included. Session memory is keyed `user_id::session_id`, so deriving the
    user from the token means a caller can only ever address their own sessions.
    """
    owner_id = str(user.get("sub") or user.get("email") or "")
    turns = session_memory.get_history(session_id, user_id=owner_id)
    journey_ctx = session_memory.get_journey_context(session_id, user_id=owner_id)
    return SessionHistoryResponse(
        session_id=session_id,
        user_id=owner_id,
        turns=turns,
        journey_context=journey_ctx,
    )


# ── Phase 14: AI Observability & Diagnostics Endpoints ──────────────────────
# Admin-only. Traces carry the text of other users' questions, the buffer
# reset is destructive, and a benchmark run is expensive enough to be a
# denial-of-service lever -- none of which should be reachable anonymously.

from app.ai.observability import ai_tracer, TraceMetrics


@router.get("/observability/traces", summary="Query AI Request Lifecycle Traces")
async def get_traces(
    limit: int = 50,
    offset: int = 0,
    status: Optional[str] = None,
    retrieval_mode: Optional[str] = None,
    min_latency_ms: Optional[float] = None,
    error_only: bool = False,
    _admin: dict = Depends(require_role(UserRole.ADMIN)),
) -> dict:
    """List recent AI lifecycle traces with filtering and pagination."""
    return ai_tracer.query_traces(
        limit=min(limit, 200),
        offset=offset,
        status=status,
        retrieval_mode=retrieval_mode,
        min_latency_ms=min_latency_ms,
        error_only=error_only,
    )


@router.get("/observability/traces/{request_id}", summary="Inspect a Single AI Request Trace")
async def get_trace_by_id(
    request_id: str,
    _admin: dict = Depends(require_role(UserRole.ADMIN)),
) -> dict:
    """Fetch complete stage-by-stage timing breakdown and metadata for a specific request ID."""
    trace = ai_tracer.get_trace(request_id)
    if not trace:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Trace with request_id '{request_id}' not found in observability buffer",
        )
    return trace.model_dump()


@router.get("/observability/metrics", response_model=TraceMetrics, summary="Fetch AI Operational Metrics")
async def get_ai_metrics(
    _admin: dict = Depends(require_role(UserRole.ADMIN)),
) -> TraceMetrics:
    """Returns aggregated latency percentiles (p50/p95/p99), success rates, and tool telemetry."""
    return ai_tracer.get_metrics()


@router.delete("/observability/traces", summary="Clear Observability Trace Buffer")
async def clear_traces(
    _admin: dict = Depends(require_role(UserRole.ADMIN)),
) -> dict:
    """Resets the in-memory trace ring buffer (used for diagnostic resets or testing)."""
    ai_tracer.clear_traces()
    return {"status": "success", "message": "Observability trace buffer cleared"}


# ── Phase 15: AI Evaluation Framework Endpoints ─────────────────────────────

from app.ai.evaluation import ai_evaluator, get_category_counts


@router.post("/evaluation/run", summary="Trigger AI Benchmark Evaluation Run")
async def run_ai_evaluation(
    category: Optional[str] = None,
    limit: Optional[int] = None,
    _admin: dict = Depends(require_role(UserRole.ADMIN)),
) -> dict:
    """Executes the AI evaluation benchmark and exports JSON/Markdown reports."""
    from app.ai.evaluation.dataset import get_benchmark_dataset, get_dataset_by_category

    if category:
        items = get_dataset_by_category(category)
        if not items:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown or empty evaluation category '{category}'",
            )
    else:
        items = get_benchmark_dataset()

    if limit and limit > 0:
        items = items[:limit]

    summary = await ai_evaluator.run_benchmark(items=items)
    return summary.to_dict()


@router.get("/evaluation/latest", summary="Fetch Latest AI Benchmark Summary")
async def get_latest_evaluation(
    _admin: dict = Depends(require_role(UserRole.ADMIN)),
) -> dict:
    """Returns the latest in-memory or persisted benchmark summary."""
    if ai_evaluator.latest_summary:
        return ai_evaluator.latest_summary.to_dict()

    # Attempt to load from persisted artifacts
    json_path = ai_evaluator.output_dir / "ai_benchmark_evaluation.json"
    if json_path.exists():
        import json
        with open(json_path, "r", encoding="utf-8") as f:
            return json.load(f)

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="No evaluation benchmark has been run yet",
    )


@router.get("/evaluation/categories", summary="List Evaluation Categories and Counts")
async def get_evaluation_categories() -> dict:
    """Returns the list of 12 benchmark categories and item counts."""
    return {"categories": get_category_counts()}

