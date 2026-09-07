from __future__ import annotations

import logging
from typing import Optional

from app.ai.agents.orchestrator import orchestrator
from app.ai.config import ai_settings
from app.ai.models import (
    AIChatRequest,
    AIChatResponse,
    AIHealthResponse,
)

logger = logging.getLogger("bmtc-ai")


class AIService:
    """Isolated service coordinating the AI Intelligence Layer via LangChain.

    Accesses DBARS solely through read-only tools and public interfaces.
    Contains zero modifications to DBARS deterministic algorithms.
    """

    def __init__(self) -> None:
        self.settings = ai_settings
        self.orchestrator = orchestrator
        logger.info("AIService initialized with LangChain orchestration (enabled=%s)", self.settings.enabled)

    async def get_health(self) -> AIHealthResponse:
        """Returns health status of the AI Intelligence Layer."""
        code_ready = self.orchestrator.retriever.code_retriever.is_available()
        doc_ready = self.orchestrator.retriever.doc_retriever.is_available()

        from app.ai.tools.registry import tool_registry
        return AIHealthResponse(
            status="ok" if self.settings.enabled else "disabled",
            version="1.0.0",
            enabled=self.settings.enabled,
            provider=self.settings.llm_provider,
            model=self.settings.model_name,
            code_index_ready=code_ready,
            doc_index_ready=doc_ready,
            dbars_tools_registered=len(tool_registry.list_tools()),
        )

    async def process_chat(self, request: AIChatRequest) -> AIChatResponse:
        """Processes a natural language query through LangChain orchestration."""
        return await self.orchestrator.execute(request)


ai_service = AIService()
