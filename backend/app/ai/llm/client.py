from __future__ import annotations

import logging
from typing import Any, List, Optional
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from app.ai.config import ai_settings

logger = logging.getLogger("bmtc-ai-llm")


class GroundedDeterministicChatModel(BaseChatModel):
    """LangChain-compliant ChatModel that deterministically synthesizes grounded answers.

    Used when running in offline, local development, or evaluation mode without external API keys.
    Extracts confirmed facts directly from retrieved context and tool outputs,
    strictly refusing to hallucinate unsupported claims.
    """

    model_name: str = "dbars-grounded-deterministic"

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

        # Extract context block from prompt
        context_block = ""
        if "Retrieved Evidence:\n" in full_text:
            context_block = full_text.split("Retrieved Evidence:\n")[1].split("\n\nTool Executions:\n")[0]

        tool_block = ""
        if "\n\nTool Executions:\n" in full_text:
            tool_block = full_text.split("\n\nTool Executions:\n")[1].split("User Question:")[0]

        import re
        clean_user_msg = re.sub(r"^(User Question:\s*)+", "", user_msg, flags=re.I).strip()

        from app.ai.rag.lexical_search import LexicalIndex
        query_terms = set(LexicalIndex._tokenize(clean_user_msg, filter_stops=True))
        evidence_terms = set(LexicalIndex._tokenize(context_block, filter_stops=True))
        overlap = query_terms.intersection(evidence_terms)

        # Detect clear out-of-domain words that have no transit or software presence
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

        output_text = "\n".join(answer_lines)
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=output_text))])


class GeminiChatModel(BaseChatModel):
    """LangChain ChatModel backed by the google-generativeai SDK.

    Written against the SDK directly rather than langchain-google-genai so the
    layer needs no dependency beyond the one already declared in
    requirements.txt. The previous implementation imported
    ChatGoogleGenerativeAI from langchain_community, where it does not exist --
    that raised ImportError on every call, was swallowed by a broad except, and
    silently fell back to the offline model. Gemini was therefore never
    reachable even with a valid API key.
    """

    model_name: str = "gemini-3.6-flash"
    temperature: float = 0.2
    max_tokens: int = 1024

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
        text = (getattr(response, "text", "") or "").strip()
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=text))])


def get_chat_model() -> BaseChatModel:
    """Factory returning a LangChain BaseChatModel based on environment configuration.

    Falls back to the grounded deterministic model whenever Gemini is
    unavailable -- no key, no network, an SDK problem, or a model name the API
    no longer serves. The fallback is logged at WARNING so a silently offline
    deployment is visible rather than mistaken for a working LLM.
    """
    if ai_settings.llm_provider == "offline":
        return GroundedDeterministicChatModel(model_name=ai_settings.model_name)

    if ai_settings.gemini_api_key:
        try:
            model = GeminiChatModel(
                model_name=ai_settings.model_name,
                temperature=ai_settings.temperature,
                max_tokens=ai_settings.max_tokens,
            )
            # Prove the model is actually reachable now, rather than failing on
            # the user's first real question.
            model.invoke([HumanMessage(content="ping")])
            logger.info("Gemini chat model ready: %s", ai_settings.model_name)
            return model
        except Exception as e:
            logger.warning(
                "Gemini unavailable (%s: %s); falling back to the grounded deterministic model. "
                "Answers will be assembled from retrieved evidence rather than generated.",
                type(e).__name__, str(e)[:200],
            )

    return GroundedDeterministicChatModel(model_name=ai_settings.model_name)
