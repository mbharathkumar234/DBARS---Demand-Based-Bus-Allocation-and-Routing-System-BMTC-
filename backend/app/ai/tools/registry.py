from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from app.ai.models import ToolExecutionRecord
from app.ai.tools.base import BaseDBARSTool
from app.ai.tools.operations_tools import (
    GetBusETATool,
    GetCrewPlanTool,
    GetCrowdingInfoTool,
    GetFleetPlanTool,
    GetMetroInfoTool,
    GetServiceAlertsTool,
)
from app.ai.tools.routing_tools import GetRouteDetailsTool, SearchBusRouteTool

logger = logging.getLogger("bmtc-ai-tools-registry")


class ToolRegistry:
    """Registry managing all authorized, read-only DBARS tools."""

    def __init__(self) -> None:
        self._tools: Dict[str, BaseDBARSTool] = {}
        self._register_default_tools()

    def _register_default_tools(self) -> None:
        defaults: List[BaseDBARSTool] = [
            SearchBusRouteTool(),
            GetRouteDetailsTool(),
            GetFleetPlanTool(),
            GetCrewPlanTool(),
            GetCrowdingInfoTool(),
            GetServiceAlertsTool(),
            GetMetroInfoTool(),
            GetBusETATool(),
        ]
        for tool in defaults:
            self._tools[tool.name] = tool
        if "get_metro_information" in self._tools:
            self._tools["get_metro_info"] = self._tools["get_metro_information"]
        if "get_crowding_information" in self._tools:
            self._tools["get_crowding_info"] = self._tools["get_crowding_information"]
        logger.info("Registered %s read-only DBARS tools", len(self._tools))

    def get_tool(self, name: str) -> Optional[BaseDBARSTool]:
        return self._tools.get(name)

    def list_tools(self) -> List[BaseDBARSTool]:
        return list(self._tools.values())

    def execute_tool(self, name: str, **kwargs: Any) -> ToolExecutionRecord:
        """Executes a registered tool and logs a structured ToolExecutionRecord."""
        tool = self.get_tool(name)
        if not tool:
            return ToolExecutionRecord(
                tool_name=name,
                arguments=kwargs,
                output=f"Tool '{name}' is not recognized or not authorized.",
                execution_time_ms=0.0,
                status="error",
            )

        # Imported here, not at module scope: app/ai/security/__init__.py loads
        # grounding_verifier, which imports this registry back.
        from app.ai.security.authorization import is_tool_authorized

        # Authorization chokepoint. Every agent and the orchestrator reach tools
        # through here, so a restricted tool cannot be invoked by a call path
        # that forgot to check. Fails closed when no principal is bound.
        allowed, denial_reason = is_tool_authorized(name)
        if not allowed:
            return ToolExecutionRecord(
                tool_name=name,
                arguments=kwargs,
                output={"error": "access_denied", "message": denial_reason},
                execution_time_ms=0.0,
                status="error",
            )

        start_time = time.perf_counter()
        raw_output = tool._run(**kwargs)
        duration_ms = (time.perf_counter() - start_time) * 1000.0

        status = raw_output.get("status", "success") if isinstance(raw_output, dict) else "success"
        result_payload = raw_output.get("result", raw_output) if isinstance(raw_output, dict) else raw_output

        return ToolExecutionRecord(
            tool_name=name,
            arguments=kwargs,
            output=result_payload,
            execution_time_ms=round(duration_ms, 2),
            status=status,
        )


tool_registry = ToolRegistry()
