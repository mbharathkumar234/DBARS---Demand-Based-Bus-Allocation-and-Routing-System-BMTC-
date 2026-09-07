from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class AITraceStage(str, Enum):
    GUARDRAILS = "guardrails"
    INTENT_ROUTING = "intent_routing"
    RETRIEVAL = "retrieval"
    TOOL_EXECUTION = "tool_execution"
    LLM_GENERATION = "llm_generation"
    GROUNDING_VERIFICATION = "grounding_verification"
    RESPONSE_DELIVERY = "response_delivery"


class StageTiming(BaseModel):
    """Detailed wall-clock performance timing for a single pipeline stage."""
    stage: str
    start_time_ms: float
    duration_ms: float
    status: str = "success"  # success | error | skipped | flagged
    error: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ToolTrace(BaseModel):
    """Audit record of a DBARS tool execution within an AI request."""
    tool_name: str
    arguments: Dict[str, Any] = Field(default_factory=dict)
    duration_ms: float = 0.0
    status: str = "success"  # success | error
    summary: Optional[str] = None
    error: Optional[str] = None


class AITraceRecord(BaseModel):
    """Lifecycle trace capturing every stage of an AI request."""
    request_id: str
    session_id: str
    user_id: Optional[str] = None
    timestamp: str
    query: str
    retrieval_mode: str
    status: str = "success"  # success | error | blocked
    error: Optional[str] = None
    error_stage: Optional[str] = None
    sources_count: int = 0
    source_paths: List[str] = Field(default_factory=list)
    tools_called: List[ToolTrace] = Field(default_factory=list)
    stages: List[StageTiming] = Field(default_factory=list)
    stage_latencies_ms: Dict[str, float] = Field(default_factory=dict)
    total_latency_ms: float = 0.0
    grounding_confidence: str = "CONFIRMED"
    model_used: str = "default"
    client_ip: Optional[str] = None


class TraceMetrics(BaseModel):
    """Aggregated operational telemetry and performance statistics."""
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    blocked_requests: int = 0
    success_rate_percent: float = 100.0
    avg_total_latency_ms: float = 0.0
    p50_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0
    p99_latency_ms: float = 0.0
    avg_stage_latencies_ms: Dict[str, float] = Field(default_factory=dict)
    grounding_distribution: Dict[str, int] = Field(default_factory=dict)
    tool_usage_counts: Dict[str, int] = Field(default_factory=dict)
    tool_error_counts: Dict[str, int] = Field(default_factory=dict)
    error_stage_counts: Dict[str, int] = Field(default_factory=dict)
