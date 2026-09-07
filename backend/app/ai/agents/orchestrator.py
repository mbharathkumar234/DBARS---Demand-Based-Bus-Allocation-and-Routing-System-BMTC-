from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Dict, List, Optional

from langchain_core.messages import AIMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnableLambda, RunnablePassthrough

from app.ai.config import ai_settings
from app.ai.llm.client import get_chat_model
from app.ai.models import (
    AIChatRequest,
    AIChatResponse,
    Citation,
    GroundingConfidence,
    RetrievalMode,
    ToolExecutionRecord,
)
from app.ai.prompts.templates import QA_PROMPT
from app.ai.rag.hybrid_retriever import hybrid_retriever

logger = logging.getLogger("bmtc-ai-orchestrator")


class LangChainOrchestrator:
    """Orchestrates RAG, tool calling, context assembly, and LLM generation using LangChain."""

    def __init__(self) -> None:
        self.retriever = hybrid_retriever
        self.llm = get_chat_model()
        self.output_parser = StrOutputParser()
        self._build_pipeline()

    def _build_pipeline(self) -> None:
        """Construct the LangChain LCEL pipeline."""
        self.chain = (
            RunnablePassthrough.assign(
                context=lambda x: self._format_evidence(x["citations"]),
                tools_context=lambda x: self._format_tools(x["tool_records"]),
            )
            | QA_PROMPT
            | self.llm
            | self.output_parser
        )

    @staticmethod
    def _format_evidence(citations: List[Citation]) -> str:
        if not citations:
            return "No evidence retrieved."
        blocks = []
        for i, c in enumerate(citations, start=1):
            provenance = f"[{i}] {c.source_type.upper()}: {c.path}"
            if c.symbol:
                provenance += f" (symbol: {c.symbol}, lines {c.start_line}-{c.end_line})"
            elif c.section:
                provenance += f" (section: {c.section})"
            blocks.append(f"{provenance}\n{c.snippet}")
        return "\n\n".join(blocks)

    @staticmethod
    def _format_tools(tool_records: List[ToolExecutionRecord]) -> str:
        if not tool_records:
            return "No tools executed."
        lines = []
        for r in tool_records:
            lines.append(f"Tool `{r.tool_name}`: {r.output} (status={r.status})")
        return "\n".join(lines)

    async def execute(
        self,
        request: AIChatRequest,
        tool_records: Optional[List[ToolExecutionRecord]] = None,
    ) -> AIChatResponse:
        """Execute the complete LangChain orchestration pipeline with lifecycle telemetry."""
        start_time = time.perf_counter()
        request_id = request.request_id or f"req_{uuid.uuid4().hex[:12]}"
        session_id = request.session_id or f"session_{uuid.uuid4().hex[:12]}"
        user_id = request.user_id
        query = request.query.strip()
        q_lower = query.lower()
        tools = list(tool_records) if tool_records else []
        # Whether the language model actually produced this answer. Most
        # queries are answered by a domain agent formatting retrieved data, and
        # reporting the configured model name for those overstated the model's
        # role -- the UI badge read "gemini-3.6-flash" on answers Gemini never
        # saw.
        llm_invoked = False

        from app.ai.observability import ai_tracer, AITraceStage
        trace_ctx = ai_tracer.start_trace(
            request_id=request_id,
            session_id=session_id,
            user_id=user_id,
            query=query,
            retrieval_mode=request.retrieval_mode.value,
        )

        # Retrieve isolated session history & journey context
        from app.ai.memory.session_memory import session_memory
        history = session_memory.get_history(session_id, user_id=user_id)
        journey_context = session_memory.get_journey_context(session_id, user_id=user_id)

        # Step 0: Security Guardrails & Adversarial Grounding Scan
        from app.ai.models import Citation
        from app.ai.security import guardrails
        with trace_ctx.time_stage(AITraceStage.GUARDRAILS):
            scan = guardrails.scan_query(query)
            if not scan.is_safe:
                trace_ctx.record_blocked(scan.flagged_reason or "Blocked by safety guardrails")
                trace_ctx.finalize(
                    status="blocked",
                    confidence=GroundingConfidence.UNKNOWN.value,
                    model=getattr(self.llm, "model_name", ai_settings.model_name),
                )
                return AIChatResponse(
                    answer=f"Request blocked by DBARS AI Safety Guardrails: {scan.flagged_reason}",
                    grounding=GroundingConfidence.UNKNOWN,
                    sources=[],
                    tools_called=[],
                    session_id=session_id,
                    model_used=getattr(self.llm, "model_name", ai_settings.model_name),
                    latency_ms=round((time.perf_counter() - start_time) * 1000.0, 2),
                    request_id=request_id,
                )

            if scan.adversarial_grounding_eval:
                adv = scan.adversarial_grounding_eval
                citations = [
                    Citation(
                        source_type="system",
                        title="DBARS Grounding Verification Engine",
                        snippet=adv.rejection_reason or "Negative verification check",
                    )
                ] if adv.rejection_reason else []
                trace_ctx.record_blocked(adv.rejection_reason or "Adversarial check triggered")
                trace_ctx.record_sources(citations)
                trace_ctx.finalize(
                    status="blocked",
                    confidence=adv.confidence.value,
                    model=getattr(self.llm, "model_name", ai_settings.model_name),
                )
                return AIChatResponse(
                    answer=adv.sanitized_answer,
                    grounding=adv.confidence,
                    sources=citations if request.include_sources else [],
                    tools_called=[],
                    session_id=session_id,
                    model_used=getattr(self.llm, "model_name", ai_settings.model_name),
                    latency_ms=round((time.perf_counter() - start_time) * 1000.0, 2),
                    request_id=request_id,
                )

        # Auto tool invocation based on intent
        from app.ai.tools.registry import tool_registry
        import re

        with trace_ctx.time_stage(AITraceStage.TOOL_EXECUTION):
            if not tools:
                # Route Details Intent: "Look up the route details for bus Route 335-E"
                route_det_match = re.search(r"(?:route\s+details\s+for(?:\s+bus)?(?:\s+route)?|details\s+for(?:\s+bus)?(?:\s+route)?)\s+([0-9]+[a-zA-Z0-9\-_]*)", query, re.I)
                if not route_det_match and "details" in q_lower:
                    route_det_match = re.search(r"\b(?:route|bus)\s+([0-9]+[a-zA-Z0-9\-_]*)\b", query, re.I)

                if route_det_match:
                    r_num = route_det_match.group(1).strip()
                    t_rec = tool_registry.execute_tool("get_route_details", route_number=r_num)
                    tools.append(t_rec)

                # Route Search Intent
                route_match = re.search(r"(?:from|travel from|route from|go from|connect|between)\s+([a-zA-Z0-9\s]+?)\s+(?:to|towards|and)\s+([a-zA-Z0-9\s]+?)(?:\?|\.|$|along)", query, re.I)
                if route_match and not any(w in q_lower for w in ["dataset", "codebase", "api", "database", "ai agent", "csv"]):
                    orig = route_match.group(1).strip()
                    dest = route_match.group(2).strip()
                    t_rec = tool_registry.execute_tool("search_bus_route", current_stop=orig, destination=dest)
                    tools.append(t_rec)

                # Fleet Planning Intent
                elif any(k in q_lower for k in ["how many buses", "fleet plan", "fleet requirement", "blocking plan", "minimum fleet"]):
                    t_rec = tool_registry.execute_tool("get_fleet_plan")
                    tools.append(t_rec)

                # Crew Planning Intent
                elif any(k in q_lower for k in ["crew duties", "crew plan", "crew ratio", "how many crew", "crew-to-bus", "crew requirement", "duty count", "crew schedule", "16-hour", "continuous 16-hour"]):
                    t_rec = tool_registry.execute_tool("get_crew_plan")
                    tools.append(t_rec)

                # Service Alerts Intent
                elif any(k in q_lower for k in ["active alerts", "service alert", "disruptions", "road closure"]):
                    t_rec = tool_registry.execute_tool("get_service_alerts")
                    tools.append(t_rec)

                # Metro Station Intent
                elif "metro" in q_lower:
                    stop_m = re.search(r"(?:near|at|to|around)\s+([a-zA-Z0-9\s]+?)(?:\?|\.|$)", query, re.I)
                    stop_name = stop_m.group(1).strip() if stop_m else "Majestic"
                    t_rec = tool_registry.execute_tool("get_metro_info", stop_name=stop_name)
                    tools.append(t_rec)

        try:
            # Codebase Assistant Routing
            from app.ai.agents.codebase_agent import codebase_assistant
            from app.ai.agents.operations_agent import operations_assistant
            from app.ai.agents.travel_agent import travel_assistant

            with trace_ctx.time_stage(AITraceStage.INTENT_ROUTING):
                is_explicit_code = request.retrieval_mode == RetrievalMode.CODE
                is_explicit_doc = request.retrieval_mode == RetrievalMode.DOCUMENTATION
                is_explicit_ops = request.retrieval_mode == RetrievalMode.OPERATIONS
                is_explicit_travel = request.retrieval_mode in [RetrievalMode.TRAVEL, RetrievalMode.ROUTING]

                travel_params = travel_assistant.extract_parameters(
                    query,
                    history=history,
                    journey_context=journey_context,
                ) if not is_explicit_code and not is_explicit_doc and not is_explicit_ops else None

                is_travel_intent = is_explicit_travel or (
                    not is_explicit_code and not is_explicit_doc and not is_explicit_ops and travel_params and (
                        not any(w in q_lower for w in ["trace how", "multi-leg", "architecture", "query lifecycle"]) and (
                            travel_params.query_type in ["why_recommendation", "least_walking", "bus_availability", "transfer_query"] or
                            # `stops_from_query` matters: origin and destination
                            # are inherited from the active journey when a turn
                            # names none, so testing them alone was circular --
                            # the inheritance produced the very evidence that
                            # classified the turn as travel. "how crowded is
                            # 290-T SBS-HSH" was answered with the previous
                            # turn's journey plan for exactly this reason.
                            # Genuine follow-ups ("which option involves the
                            # least walking?") still route here through
                            # query_type above.
                            (travel_params.stops_from_query and not any(w in q_lower for w in ["dataset", "codebase", "api", "database", "ai agent", "csv"])) or
                            any(k in q_lower for k in [
                                "how do i travel", "how do i reach", "how to reach", "how to travel",
                                "need to go from", "which option involves", "which bus", "what buses are available",
                                "why did you recommend", "one transfer", "least walking", "bus to", "go from"
                            ])
                        )
                    )
                )

                is_code_intent = (
                    is_explicit_code or
                    (not is_travel_intent and not is_explicit_ops and (
                        is_explicit_doc or
                        any(k in q_lower for k in [
                            "where is", "where does", "explain", "how does", "implemented",
                            "predictor.py", "function", "class", "symbol", "module", "codebase",
                            "stop resolution", "ordered stop pair", "shakti", "offline ticket",
                            "require_role", "fare calculated", "blocking.py", "crew.py",
                            "create_app", "main.py", "trace the execution", "telemetry",
                            "session memory", "session/clear", "observability", "dataset", "read-only",
                            "trace how", "multi-leg", "passenger travel query", "generates multi-leg"
                        ])
                    ))
                )

                is_operations_intent = (
                    is_explicit_ops or
                    any(k in q_lower for k in [
                        "how many buses", "fleet plan", "fleet requirement", "blocking plan",
                        "minimum fleet", "why do we need that many buses", "crew duties",
                        "crew plan", "crew ratio", "how many crew", "crew-to-bus",
                        "service alert", "active alert", "disruptions", "frequent crowding",
                        # "how crowded is <route>" matched none of the original
                        # crowding phrasings, so it fell through to travel.
                        "crowding for", "how crowded", "how full", "crowd level",
                        "crowding on", "crowded is", "crowding level", "occupancy",
                        "passenger load", "change a planning", "headway for",
                        "depot allocation", "16-hour", "off-peak frequency", "duty count", "crew requirement"
                    ])
                )
            route_det_rec = next((t for t in tools if t.tool_name == "get_route_details" and t.status == "success"), None)
            metro_det_rec = next((t for t in tools if t.tool_name in ["get_metro_info", "get_metro_information"] and t.status == "success"), None)

            if route_det_rec and not (travel_params and travel_params.stops_from_query):
                out = route_det_rec.output if isinstance(route_det_rec.output, dict) else {}
                bus_n = out.get("bus_number", "Route")
                origin = out.get("origin_stop", "Origin")
                dest = out.get("destination_stop", "Destination")
                stops_cnt = out.get("stop_count", len(out.get("stop_sequence", [])))
                seq = out.get("stop_sequence", [])
                sample_stops = ", ".join(seq[:5]) + ("..." if len(seq) > 5 else "")
                raw_answer = (
                    f"### BMTC Route Details: `{bus_n}`\n\n"
                    f"- **Origin**: {origin}\n"
                    f"- **Destination**: {dest}\n"
                    f"- **Total Stops**: {stops_cnt}\n"
                    f"- **Key Stops**: {sample_stops}\n"
                    f"- **Full Route Name**: {out.get('full_name', f'{origin} -> {dest}')}\n\n"
                    f"Route `{bus_n}` is verified in the official BMTC network schedule."
                )
                grounding = GroundingConfidence.CONFIRMED
                from app.ai.models import Citation
                citations = [Citation(source_type="dbars_tool", title="get_route_details", snippet=f"Route details for {bus_n}")]

            elif metro_det_rec and not (travel_params and travel_params.stops_from_query):
                out = metro_det_rec.output if isinstance(metro_det_rec.output, dict) else {}
                stop_name = out.get("stop_name", "Bus Stop")
                stations = out.get("nearby_stations", [])
                st_lines = []
                for s in stations:
                    st_lines.append(f"- **{s.get('station_name')}** ({s.get('line', 'Namma Metro')}): ~{s.get('distance_km', 'N/A')} km ({s.get('walking_minutes', 'N/A')} min walk)")
                raw_answer = (
                    f"### Namma Metro Connectivity near `{stop_name}`\n\n"
                    f"Found {len(stations)} metro station(s) connected to this bus stop:\n\n"
                    + "\n".join(st_lines)
                )
                grounding = GroundingConfidence.CONFIRMED
                from app.ai.models import Citation
                citations = [Citation(source_type="dbars_tool", title="get_metro_info", snippet=f"Metro information for {stop_name}")]

            elif is_code_intent:
                with trace_ctx.time_stage(AITraceStage.RETRIEVAL):
                    code_ans = codebase_assistant.answer(query, top_k=4)
                raw_answer = code_ans.to_formatted_markdown()
                citations = code_ans.evidence
                grounding = code_ans.confidence
                if is_explicit_doc:
                    with trace_ctx.time_stage(AITraceStage.RETRIEVAL):
                        doc_cits = self.retriever.retrieve_citations(
                            query=query,
                            mode=RetrievalMode.DOCUMENTATION,
                            top_k=2,
                        )
                    if doc_cits:
                        citations = doc_cits + citations
            elif is_operations_intent:
                with trace_ctx.time_stage(AITraceStage.TOOL_EXECUTION):
                    ops_ans = operations_assistant.answer(query)
                raw_answer = ops_ans.to_formatted_markdown()
                tools = ops_ans.tool_records
                grounding = ops_ans.confidence
                with trace_ctx.time_stage(AITraceStage.RETRIEVAL):
                    citations = self.retriever.retrieve_citations(
                        query=query,
                        mode=RetrievalMode.DOCUMENTATION,
                        top_k=2,
                    )
            elif is_travel_intent:
                with trace_ctx.time_stage(AITraceStage.TOOL_EXECUTION):
                    travel_ans = travel_assistant.answer(
                        query,
                        history=history,
                        journey_context=journey_context,
                    )
                raw_answer = travel_ans.content
                tools = travel_ans.tool_records if travel_ans.tool_records else tools
                grounding = (
                    GroundingConfidence.CONFIRMED if travel_ans.confirmation_status == "CONFIRMED"
                    else GroundingConfidence.UNKNOWN
                )
                from app.ai.models import Citation
                citations = [
                    Citation(
                        source_type="dbars_tool",
                        title=s.get("tool", "search_bus_route"),
                        snippet=f"Grounded transit route from {s.get('origin', '')} to {s.get('destination', '')}",
                    )
                    for s in travel_ans.sources
                ]
                # Update journey context in memory if a route was found
                if travel_ans.route_found and travel_ans.best_route:
                    resolved_orig, _, _ = travel_assistant.resolve_stop(travel_params.origin)
                    resolved_dest, _, _ = travel_assistant.resolve_stop(travel_params.destination)
                    session_memory.update_journey_context(
                        session_id=session_id,
                        user_id=user_id,
                        origin=resolved_orig or travel_params.origin,
                        destination=resolved_dest or travel_params.destination,
                        bus_chain=travel_ans.best_route.get("bus_chain") or travel_ans.best_route.get("bus_number"),
                        bus_number=travel_ans.best_route.get("bus_number"),
                        transfers=travel_ans.transfers,
                        last_recommended_route=travel_ans.best_route,
                    )
            else:
                # 1. Retrieval
                with trace_ctx.time_stage(AITraceStage.RETRIEVAL):
                    citations = self.retriever.retrieve_citations(
                        query=query,
                        mode=request.retrieval_mode,
                        top_k=4,
                    )

                # 2. Context Assembly & LLM Generation via LangChain LCEL
                chain_input = {
                    "query": query,
                    "citations": citations,
                    "tool_records": tools,
                }

                with trace_ctx.time_stage(AITraceStage.LLM_GENERATION):
                    llm_invoked = True
                    raw_answer = await self.chain.ainvoke(chain_input)

                # 3. Grounding Confidence Assignment
                if "UNKNOWN" in raw_answer or "cannot be established" in raw_answer:
                    grounding = GroundingConfidence.UNKNOWN
                    citations = []
                elif citations or tools:
                    grounding = GroundingConfidence.CONFIRMED
                else:
                    grounding = GroundingConfidence.UNKNOWN

        except Exception as e:
            logger.exception("Error during LangChain orchestration: %s", e)
            trace_ctx.record_error(AITraceStage.LLM_GENERATION, str(e))
            raw_answer = (
                f"An error occurred while processing the request: {str(e)}. "
                "DBARS deterministic services remain healthy and unaffected."
            )
            grounding = GroundingConfidence.UNKNOWN
            citations = []

        # Phase 13: Grounding and Source Verification Engine
        with trace_ctx.time_stage(AITraceStage.GROUNDING_VERIFICATION):
            from app.ai.security.grounding_verifier import grounding_verifier
            claim_verif = grounding_verifier.verify_answer_claims(
                answer=raw_answer,
                citations=citations,
                tool_records=tools,
            )

        final_answer = claim_verif.sanitized_answer if not claim_verif.is_fully_grounded else raw_answer
        final_citations = claim_verif.verified_citations
        final_grounding = claim_verif.grounding_confidence if not claim_verif.is_fully_grounded else grounding

        # Record conversation turns in memory (PII auto-sanitized, sliding-window bounded)
        with trace_ctx.time_stage(AITraceStage.RESPONSE_DELIVERY):
            session_memory.add_turn(
                session_id=session_id,
                role="user",
                content=query,
                user_id=user_id,
                metadata={"grounding": final_grounding.value},
            )
            session_memory.add_turn(
                session_id=session_id,
                role="assistant",
                content=final_answer,
                user_id=user_id,
                metadata={"grounding": final_grounding.value},
            )

            trace_ctx.record_sources(final_citations)
            for t in tools:
                trace_ctx.record_tool_record(t)

        trace_ctx.finalize(
            status="success" if "An error occurred while processing" not in raw_answer else "error",
            confidence=final_grounding.value,
            model=getattr(self.llm, "model_name", ai_settings.model_name),
        )

        latency_ms = (time.perf_counter() - start_time) * 1000.0

        return AIChatResponse(
            answer=final_answer.strip(),
            grounding=final_grounding,
            sources=final_citations if request.include_sources else [],
            tools_called=tools,
            session_id=session_id,
            model_used=(
                getattr(self.llm, "model_name", ai_settings.model_name)
                if llm_invoked
                else "dbars-deterministic-agent"
            ),
            latency_ms=round(latency_ms, 2),
            request_id=request_id,
        )


orchestrator = LangChainOrchestrator()
