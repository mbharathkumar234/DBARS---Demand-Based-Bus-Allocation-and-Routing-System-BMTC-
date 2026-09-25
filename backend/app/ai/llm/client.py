from __future__ import annotations

import logging
import time
from typing import Any, List, Optional
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from app.ai.config import ai_settings

logger = logging.getLogger("bmtc-ai-llm")

OFFLINE_MODEL_NAME = "dbars-grounded-deterministic"


def _result(text: str, model_name: str) -> ChatResult:
    message = AIMessage(content=text, response_metadata={"model_name": model_name})
    return ChatResult(generations=[ChatGeneration(message=message)])


class GroundedDeterministicChatModel(BaseChatModel):
    """LangChain-compliant ChatModel that deterministically synthesizes grounded answers.

    Used when running in offline, local development, or evaluation mode without external API keys.
    Extracts confirmed facts directly from retrieved context and tool outputs,
    strictly refusing to hallucinate unsupported claims.
    """

    # Always its own name. It was constructed with the configured Gemini model
    # name, so offline answers were labelled "gemini-3.6-flash".
    model_name: str = OFFLINE_MODEL_NAME

    @property
    def _llm_type(self) -> str:
        return "dbars_grounded_deterministic"

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        full_text = "\n".join([m.content for m in messages if isinstance(m.content, str)])
        user_msg = next((m.content for m in reversed(messages) if m.type == "human" and isinstance(m.content, str)), "")

        context_block = ""
        if "Retrieved Evidence:\n" in full_text:
            context_block = full_text.split("Retrieved Evidence:\n")[1].split("\n\nTool Executions:\n")[0]

        tool_block = ""
        if "\n\nTool Executions:\n" in full_text:
            tool_block = full_text.split("\n\nTool Executions:\n")[1].split("User Question:")[0]

        import re
        clean_user_msg = re.sub(r"^(User Question:\s*)+", "", user_msg, flags=re.I).strip()

        from app.ai.rag.text import tokenize
        query_terms = set(tokenize(clean_user_msg))
        evidence_terms = set(tokenize(context_block))
        overlap = query_terms.intersection(evidence_terms)

        foreign_words = {"nuclear", "mars", "alien", "missile", "weapon", "warfare", "crypto", "bitcoin"}
        has_foreign_words = any(w in query_terms for w in foreign_words)

        has_sufficient_evidence = bool(overlap) and not has_foreign_words and (
            (len(query_terms) <= 2 and len(overlap) >= 1) or
            (len(overlap) >= 2)
        )
        has_tool_output = bool(tool_block.strip() and "No tools executed" not in tool_block)

        answer_lines: List[str] = []
        if has_tool_output:
            answer_lines.append(f"### DBARS Deterministic Tool Results:\n{tool_block.strip()}\n")

        if context_block.strip() and "No evidence retrieved" not in context_block and has_sufficient_evidence:
            answer_lines.append(f"### Grounded Evidence:\n{context_block.strip()}\n")
        elif not has_tool_output:
            answer_lines.append(
                f"Information regarding '{clean_user_msg}' cannot be established from the repository or DBARS tools. "
                "In accordance with DBARS grounding rules, this information is UNKNOWN."
            )

        return _result("\n".join(answer_lines), self.model_name)


class GeminiChatModel(BaseChatModel):
    """LangChain ChatModel backed by the google-generativeai SDK.

    Written against the SDK directly rather than langchain-google-genai so the
    layer needs no dependency beyond the one already declared in
    requirements.txt.
    """

    model_name: str = "gemini-3.6-flash"
    temperature: float = 0.2
    max_tokens: int = 2048

    @property
    def _llm_type(self) -> str:
        return "dbars_gemini"

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        import google.generativeai as genai

        genai.configure(api_key=ai_settings.gemini_api_key)

        system_parts = [m.content for m in messages if m.type == "system" and isinstance(m.content, str)]
        turns = [m for m in messages if m.type in ("human", "ai") and isinstance(m.content, str)]

        model = genai.GenerativeModel(
            self.model_name,
            system_instruction="\n\n".join(system_parts) or None,
        )
        history = [
            {"role": "user" if m.type == "human" else "model", "parts": [m.content]}
            for m in turns[:-1]
        ]
        latest = turns[-1].content if turns else ""

        chat = model.start_chat(history=history)
        response = chat.send_message(
            latest,
            generation_config=genai.types.GenerationConfig(
                temperature=self.temperature,
                max_output_tokens=self.max_tokens,
            ),
        )
        # `.text` raises ValueError when the candidate has no text part at all
        # (every output token spent on reasoning); that propagates so the
        # resilient wrapper can answer from evidence instead.
        text = (response.text or "").strip()
        finish = getattr(getattr(response.candidates[0], "finish_reason", None), "name", "") if response.candidates else ""
        if finish == "MAX_TOKENS":
            # A cut-off answer used to be shown as if complete -- one ended
            # mid-heading at "**Exact Term" under a CONFIRMED badge.
            text += "\n\n_(Answer truncated at the output token limit.)_"
        return _result(text, self.model_name)


class ResilientChatModel(BaseChatModel):
    """Gemini first, the grounded model when Gemini fails -- per request.

    Gemini used to be probed once at import; if that one call failed (a 429
    during a quota spike, a network blip) the process ran offline until it was
    restarted, and a failure on a later request surfaced as an error message
    instead of an answer. Each request now tries Gemini and falls back on its
    own, and the answering model is recorded on the message.
    """

    primary: BaseChatModel
    fallback: BaseChatModel
    model_name: str = "gemini-3.6-flash"
    # After a failure, skip the primary for this long rather than paying its
    # latency to fail again on every request of a quota outage.
    cooldown_seconds: float = 60.0
    _skip_until: float = 0.0

    @property
    def _llm_type(self) -> str:
        return "dbars_resilient"

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        if time.monotonic() >= self._skip_until:
            try:
                return self.primary._generate(messages, stop=stop, **kwargs)
            except Exception as exc:
                self._skip_until = time.monotonic() + self.cooldown_seconds
                logger.warning(
                    "%s failed (%s: %s); answering from retrieved evidence with the grounded model "
                    "and skipping %s for %.0fs.",
                    self.model_name, type(exc).__name__, str(exc)[:200], self.model_name, self.cooldown_seconds,
                )
        return self.fallback._generate(messages, stop=stop, **kwargs)


def get_chat_model() -> BaseChatModel:
    """The chat model the orchestrator should use.

    Offline when configured so or when no Gemini key is set; otherwise Gemini
    with a per-request fallback to the grounded model.
    """
    offline = GroundedDeterministicChatModel()
    if ai_settings.llm_provider == "offline" or not ai_settings.gemini_api_key:
        return offline
    gemini = GeminiChatModel(
        model_name=ai_settings.model_name,
        temperature=ai_settings.temperature,
        max_tokens=ai_settings.max_tokens,
    )
    logger.info("Chat model: %s, falling back to %s per request", ai_settings.model_name, OFFLINE_MODEL_NAME)
    return ResilientChatModel(primary=gemini, fallback=offline, model_name=ai_settings.model_name)
