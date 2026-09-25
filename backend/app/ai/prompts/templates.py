from __future__ import annotations

from langchain_core.prompts import ChatPromptTemplate, SystemMessagePromptTemplate, HumanMessagePromptTemplate

# Answer first, then evidence. The previous instruction ("clearly distinguish
# CONFIRMED facts, INFERRED deductions and UNKNOWN facts") produced answers
# organised as status reports -- "1. Codebase & Documentation Status" -- that
# never said what the thing asked about actually was.
DBARS_SYSTEM_INSTRUCTION = """You are the DBARS AI Assistant. DBARS (Demand Based Bus Allocation & Routing System) is a BMTC transit platform: a journey planner, depot fleet and crew planning, ticketing, and a GTFS feed.

Answer the user's question using ONLY the retrieved evidence and tool results below.

How to answer:
1. Start with a direct answer to the question in one to three sentences. Do not begin with a heading, a status, or a restatement of the question.
2. Then give the supporting details the question needs, citing each fact with its evidence number and location, e.g. [1] `frontend/src/components/AIAssistantModal.tsx` lines 72-97.
3. If the evidence answers only part of the question, answer that part and state plainly what the evidence does not show.
4. If the evidence does not answer the question at all, say that it cannot be established from the repository, and nothing else.

Never invent bus routes, stop names, API endpoints, file paths, function names or numbers that do not appear in the evidence. Keep the answer concise.
"""

QA_PROMPT = ChatPromptTemplate.from_messages(
    [
        SystemMessagePromptTemplate.from_template(
            DBARS_SYSTEM_INSTRUCTION
            + "\n\nRetrieved Evidence:\n{context}\n\nTool Executions:\n{tools_context}"
        ),
        HumanMessagePromptTemplate.from_template("User Question: {query}"),
    ]
)

INTENT_ROUTING_PROMPT = ChatPromptTemplate.from_messages(
    [
        SystemMessagePromptTemplate.from_template(
            "Classify the following query into exactly one of: 'code', 'documentation', 'operations', 'travel', or 'hybrid'. Return ONLY the classification label."
        ),
        HumanMessagePromptTemplate.from_template("{query}"),
    ]
)
