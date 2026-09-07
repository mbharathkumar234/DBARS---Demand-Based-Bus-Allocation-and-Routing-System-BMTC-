from __future__ import annotations

from collections import deque
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import logging
import math
import threading
import time
import uuid
from typing import Any, Dict, Generator, List, Optional, Union

from app.ai.models import Citation, ToolExecutionRecord
from app.ai.observability.models import (
    AITraceRecord,
    AITraceStage,
    StageTiming,
    ToolTrace,
    TraceMetrics,
)
from app.ai.observability.scrubber import trace_scrubber

logger = logging.getLogger("bmtc-ai-tracer")
telemetry_logger = logging.getLogger("bmtc-ai-telemetry")


class TraceContext:
    """Manages active request execution lifecycle, stage timings, and telemetry capture."""

    def __init__(
        self,
        manager: "AIObservabilityManager",
        request_id: Optional[str] = None,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        query: str = "",
        retrieval_mode: str = "auto",
        client_ip: Optional[str] = None,
    ) -> None:
        self.manager = manager
        self.request_id = request_id or f"req_{uuid.uuid4().hex[:12]}"
        self.session_id = session_id or f"sess_{uuid.uuid4().hex[:12]}"
        self.user_id = trace_scrubber.scrub_text(user_id) if user_id else None
        self.raw_query = query
        self.query = trace_scrubber.scrub_text(query)
        self.retrieval_mode = retrieval_mode
        self.client_ip = client_ip

        self.start_wall_time = time.perf_counter()
        self.timestamp = datetime.now(timezone.utc).isoformat()

        self.stages: List[StageTiming] = []
        self.tools: List[ToolTrace] = []
        self.sources: List[str] = []
        self.status = "success"
        self.error: Optional[str] = None
        self.error_stage: Optional[str] = None
        self.grounding_confidence = "CONFIRMED"
        self.model_used = "default"
        self._finalized = False

    @contextmanager
    def time_stage(
        self,
        stage: Union[AITraceStage, str],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Generator[None, None, None]:
        """Context manager measuring execution duration and capturing errors for a single stage."""
        stage_name = stage.value if isinstance(stage, AITraceStage) else str(stage)
        stage_start = time.perf_counter()
        stage_status = "success"
        stage_err: Optional[str] = None

        try:
            yield
        except Exception as e:
            stage_status = "error"
            stage_err = trace_scrubber.scrub_text(str(e))
            self.record_error(stage_name, stage_err)
            raise
        finally:
            stage_duration = (time.perf_counter() - stage_start) * 1000.0
            timing = StageTiming(
                stage=stage_name,
                start_time_ms=round((stage_start - self.start_wall_time) * 1000.0, 2),
                duration_ms=round(stage_duration, 2),
                status=stage_status,
                error=stage_err,
                metadata=trace_scrubber.scrub_dict(metadata or {}),
            )
            self.stages.append(timing)

    def record_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        duration_ms: float = 0.0,
        status: str = "success",
        summary: Optional[str] = None,
        error: Optional[str] = None,
    ) -> None:
        """Appends a sanitized DBARS tool execution trace."""
        trace = ToolTrace(
            tool_name=tool_name,
            arguments=trace_scrubber.scrub_dict(arguments or {}),
            duration_ms=round(duration_ms, 2),
            status=status,
            summary=trace_scrubber.scrub_text(summary) if summary else None,
            error=trace_scrubber.scrub_text(error) if error else None,
        )
        self.tools.append(trace)

    def record_tool_record(self, record: ToolExecutionRecord) -> None:
        """Adapts an existing ToolExecutionRecord into a ToolTrace."""
        summary = str(record.output)[:200] if record.output is not None else None
        self.record_tool(
            tool_name=record.tool_name,
            arguments=record.arguments,
            duration_ms=record.execution_time_ms,
            status=record.status,
            summary=summary,
        )

    def record_sources(self, citations: List[Citation]) -> None:
        """Extracts and records paths of retrieved code/documentation sources."""
        paths = []
        for c in citations:
            p = c.path or c.title
            if p and p not in paths:
                paths.append(p)
        self.sources = paths

    def record_error(self, stage: Union[AITraceStage, str], error_msg: str) -> None:
        """Flags the trace with an error state and records the originating stage."""
        stage_name = stage.value if isinstance(stage, AITraceStage) else str(stage)
        self.status = "error"
        self.error = trace_scrubber.scrub_text(error_msg)
        if not self.error_stage:
            self.error_stage = stage_name

    def record_blocked(self, reason: str) -> None:
        """Flags the trace as blocked by security guardrails."""
        self.status = "blocked"
        self.error = trace_scrubber.scrub_text(reason)
        self.error_stage = AITraceStage.GUARDRAILS.value

    def finalize(
        self,
        status: Optional[str] = None,
        confidence: Optional[str] = None,
        model: Optional[str] = None,
    ) -> AITraceRecord:
        """Assembles the final trace record, emits structured JSON telemetry, and stores in manager."""
        if self._finalized:
            return self.manager.get_trace(self.request_id)  # type: ignore

        if status:
            self.status = status
        if confidence:
            self.grounding_confidence = confidence
        if model:
            self.model_used = model

        total_latency = (time.perf_counter() - self.start_wall_time) * 1000.0
        stage_latencies = {s.stage: s.duration_ms for s in self.stages}

        record = AITraceRecord(
            request_id=self.request_id,
            session_id=self.session_id,
            user_id=self.user_id,
            timestamp=self.timestamp,
            query=self.query,
            retrieval_mode=self.retrieval_mode,
            status=self.status,
            error=self.error,
            error_stage=self.error_stage,
            sources_count=len(self.sources),
            source_paths=self.sources,
            tools_called=self.tools,
            stages=self.stages,
            stage_latencies_ms=stage_latencies,
            total_latency_ms=round(total_latency, 2),
            grounding_confidence=self.grounding_confidence,
            model_used=self.model_used,
            client_ip=self.client_ip,
        )

        # Emit structured JSON log for external aggregators (ELK / CloudWatch / Datadog)
        try:
            telemetry_logger.info("AI_REQUEST_TRACE %s", record.model_dump_json())
        except Exception:
            pass

        self.manager.record_trace(record)
        self._finalized = True
        return record


class AIObservabilityManager:
    """Thread-safe ring buffer and telemetry analytics store for AI requests."""

    def __init__(self, max_buffer_size: int = 1000) -> None:
        self.max_buffer_size = max_buffer_size
        self._traces: deque[AITraceRecord] = deque(maxlen=max_buffer_size)
        self._trace_map: Dict[str, AITraceRecord] = {}
        self._lock = threading.Lock()

    def start_trace(
        self,
        request_id: Optional[str] = None,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        query: str = "",
        retrieval_mode: str = "auto",
        client_ip: Optional[str] = None,
    ) -> TraceContext:
        """Initializes a new request tracing context."""
        return TraceContext(
            manager=self,
            request_id=request_id,
            session_id=session_id,
            user_id=user_id,
            query=query,
            retrieval_mode=retrieval_mode,
            client_ip=client_ip,
        )

    def record_trace(self, trace: AITraceRecord) -> None:
        """Appends a trace record to the ring buffer and maintains the lookup index."""
        with self._lock:
            # If buffer is full, remove evicted key from index
            if len(self._traces) >= self.max_buffer_size:
                evicted = self._traces[0]
                self._trace_map.pop(evicted.request_id, None)

            self._traces.append(trace)
            self._trace_map[trace.request_id] = trace

    def get_trace(self, request_id: str) -> Optional[AITraceRecord]:
        """Retrieves a single trace record by unique request ID."""
        with self._lock:
            return self._trace_map.get(request_id)

    def query_traces(
        self,
        limit: int = 50,
        offset: int = 0,
        status: Optional[str] = None,
        retrieval_mode: Optional[str] = None,
        min_latency_ms: Optional[float] = None,
        error_only: bool = False,
    ) -> Dict[str, Any]:
        """Filters and returns traces in reverse chronological order with pagination."""
        with self._lock:
            filtered = list(self._traces)

        if error_only:
            filtered = [t for t in filtered if t.status in ["error", "blocked"]]
        elif status:
            filtered = [t for t in filtered if t.status.lower() == status.lower()]

        if retrieval_mode:
            filtered = [t for t in filtered if t.retrieval_mode.lower() == retrieval_mode.lower()]

        if min_latency_ms is not None:
            filtered = [t for t in filtered if t.total_latency_ms >= min_latency_ms]

        # Reverse chronological
        filtered.reverse()
        total = len(filtered)
        paginated = filtered[offset : offset + limit]

        return {
            "total": total,
            "limit": limit,
            "offset": offset,
            "traces": [t.model_dump() for t in paginated],
        }

    def get_metrics(self) -> TraceMetrics:
        """Computes aggregated operational metrics, latency percentiles, and error distributions."""
        with self._lock:
            traces = list(self._traces)

        total = len(traces)
        if total == 0:
            return TraceMetrics()

        successful = sum(1 for t in traces if t.status == "success")
        failed = sum(1 for t in traces if t.status == "error")
        blocked = sum(1 for t in traces if t.status == "blocked")
        success_rate = (successful / total) * 100.0

        latencies = sorted([t.total_latency_ms for t in traces])
        avg_latency = sum(latencies) / total

        def calc_percentile(data: List[float], p: float) -> float:
            if not data:
                return 0.0
            k = (len(data) - 1) * p
            f = math.floor(k)
            c = math.ceil(k)
            if f == c:
                return data[int(k)]
            d0 = data[int(f)] * (c - k)
            d1 = data[int(c)] * (k - f)
            return d0 + d1

        p50 = calc_percentile(latencies, 0.50)
        p95 = calc_percentile(latencies, 0.95)
        p99 = calc_percentile(latencies, 0.99)

        # Stage latency averages
        stage_totals: Dict[str, float] = {}
        stage_counts: Dict[str, int] = {}
        for t in traces:
            for st_name, ms in t.stage_latencies_ms.items():
                stage_totals[st_name] = stage_totals.get(st_name, 0.0) + ms
                stage_counts[st_name] = stage_counts.get(st_name, 0) + 1

        avg_stages = {
            st: round(stage_totals[st] / stage_counts[st], 2)
            for st in stage_totals
        }

        # Grounding distribution
        grounding_dist: Dict[str, int] = {}
        for t in traces:
            g = t.grounding_confidence or "UNKNOWN"
            grounding_dist[g] = grounding_dist.get(g, 0) + 1

        # Tool counts & errors
        tool_counts: Dict[str, int] = {}
        tool_errors: Dict[str, int] = {}
        for t in traces:
            for tool in t.tools_called:
                tool_counts[tool.tool_name] = tool_counts.get(tool.tool_name, 0) + 1
                if tool.status == "error":
                    tool_errors[tool.tool_name] = tool_errors.get(tool.tool_name, 0) + 1

        # Error stage counts
        err_stages: Dict[str, int] = {}
        for t in traces:
            if t.error_stage:
                err_stages[t.error_stage] = err_stages.get(t.error_stage, 0) + 1

        return TraceMetrics(
            total_requests=total,
            successful_requests=successful,
            failed_requests=failed,
            blocked_requests=blocked,
            success_rate_percent=round(success_rate, 2),
            avg_total_latency_ms=round(avg_latency, 2),
            p50_latency_ms=round(p50, 2),
            p95_latency_ms=round(p95, 2),
            p99_latency_ms=round(p99, 2),
            avg_stage_latencies_ms=avg_stages,
            grounding_distribution=grounding_dist,
            tool_usage_counts=tool_counts,
            tool_error_counts=tool_errors,
            error_stage_counts=err_stages,
        )

    def clear_traces(self) -> None:
        """Resets the trace ring buffer and index."""
        with self._lock:
            self._traces.clear()
            self._trace_map.clear()


ai_tracer = AIObservabilityManager()
