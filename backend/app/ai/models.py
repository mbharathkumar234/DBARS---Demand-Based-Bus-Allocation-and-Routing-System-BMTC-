from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class GroundingConfidence(str, Enum):
    CONFIRMED = "CONFIRMED"
    INFERRED = "INFERRED"
    UNKNOWN = "UNKNOWN"


class RetrievalMode(str, Enum):
    AUTO = "auto"
    CODE = "code"
    DOCUMENTATION = "documentation"
    OPERATIONS = "operations"
    TRAVEL = "travel"
    ROUTING = "routing"
    HYBRID = "hybrid"


class Citation(BaseModel):
    """Source citation indicating origin of retrieved facts."""
    source_type: str = Field(description="code | documentation | dbars_tool | system")
    title: str = Field(description="File name or document title")
    path: Optional[str] = Field(default=None, description="Relative file path in repository")
    symbol: Optional[str] = Field(default=None, description="Class or function name if applicable")
    start_line: Optional[int] = Field(default=None, description="Starting line number")
    end_line: Optional[int] = Field(default=None, description="Ending line number")
    section: Optional[str] = Field(default=None, description="Document section header")
    snippet: Optional[str] = Field(default=None, description="Excerpt of retrieved text")


class ToolExecutionRecord(BaseModel):
    """Record of a safe read-only DBARS tool invoked during reasoning."""
    tool_name: str
    arguments: Dict[str, Any] = Field(default_factory=dict)
    output: Any = None
    execution_time_ms: float = 0.0
    status: str = "success"  # success | error


class AIChatRequest(BaseModel):
    """Request payload for POST /ai/chat."""
    query: str = Field(..., min_length=1, max_length=2000, description="Natural language question or request")
    session_id: Optional[str] = Field(default=None, description="Optional conversation session ID")
    user_id: Optional[str] = Field(default=None, description="Optional authenticated user identifier")
    request_id: Optional[str] = Field(default=None, description="Optional caller-provided trace ID")
    retrieval_mode: RetrievalMode = Field(default=RetrievalMode.AUTO, description="Target retrieval domain")
    include_sources: bool = Field(default=True, description="Whether to include source citations in response")


class AIChatResponse(BaseModel):
    """Response payload returned by POST /ai/chat."""
    answer: str
    grounding: GroundingConfidence = GroundingConfidence.CONFIRMED
    sources: List[Citation] = Field(default_factory=list)
    tools_called: List[ToolExecutionRecord] = Field(default_factory=list)
    session_id: str
    model_used: str
    latency_ms: float
    request_id: Optional[str] = Field(default=None, description="Unique trace identifier for this request")


class AIHealthResponse(BaseModel):
    """Response payload for GET /ai/health."""
    status: str
    version: str
    enabled: bool
    provider: str
    model: str
    code_index_ready: bool
    doc_index_ready: bool
    dbars_tools_registered: int


class SessionClearRequest(BaseModel):
    """Payload to clear a conversational session."""
    session_id: str
    user_id: Optional[str] = None


class SessionClearResponse(BaseModel):
    """Response returned when clearing a session."""
    session_id: str
    cleared: bool
    message: str


class SessionHistoryResponse(BaseModel):
    """Response returned when inspecting session history."""
    session_id: str
    user_id: Optional[str] = None
    turns: List[Dict[str, str]] = Field(default_factory=list)
    journey_context: Dict[str, Any] = Field(default_factory=dict)
