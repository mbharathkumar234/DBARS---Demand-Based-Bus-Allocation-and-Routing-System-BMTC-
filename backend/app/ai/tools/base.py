from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, Type
from pydantic import BaseModel
from langchain_core.tools import BaseTool

from app.ai.models import ToolExecutionRecord

logger = logging.getLogger("bmtc-ai-tools")


class BaseDBARSTool(BaseTool, ABC):
    """Base class for all DBARS AI tools.

    MANDATORY SAFETY CONSTRAINTS:
    1. STRICTLY READ-ONLY: Must never perform database mutations, deletions, or writes.
    2. DETERMINISTIC ENGINE WRAPPER: Must delegate calculation to existing DBARS services.
    3. AUDITABLE: Logs all calls with execution latency and arguments.
    """

    is_read_only: bool = True

    @abstractmethod
    def _run_tool(self, **kwargs: Any) -> Any:
        """Execute the real read-only DBARS service."""
        pass

    def _run(self, *args: Any, **kwargs: Any) -> Any:
        start_time = time.perf_counter()
        logger.info("Executing tool '%s' with args: %s", self.name, kwargs)
        try:
            output = self._run_tool(**kwargs)
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            return {
                "status": "success",
                "tool": self.name,
                "result": output,
                "duration_ms": round(duration_ms, 2),
            }
        except Exception as e:
            logger.exception("Error executing tool '%s': %s", self.name, e)
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            return {
                "status": "error",
                "tool": self.name,
                "error": str(e),
                "duration_ms": round(duration_ms, 2),
            }

    async def _arun(self, *args: Any, **kwargs: Any) -> Any:
        # Fallback to sync run for synchronous wrappers
        return self._run(*args, **kwargs)
