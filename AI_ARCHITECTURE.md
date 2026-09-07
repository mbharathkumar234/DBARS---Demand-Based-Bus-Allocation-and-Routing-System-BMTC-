# DBARS AI Intelligence Layer — Architecture

The AI layer answers natural-language questions about the DBARS codebase, its
documentation, and live transit state. It is an **additive** subsystem: the
deterministic routing engine does not import it, does not call it, and does not
depend on it in any way.

## 1. Position in the system

```
                 ┌──────────────────────────────────────────┐
  HTTP  ────────▶│  app/ai/api/routes.py     (/ai/*)        │
                 │  authentication + role checks            │
                 └────────────────────┬─────────────────────┘
                                      │  AIPrincipal bound per request
                 ┌────────────────────▼─────────────────────┐
                 │  app/ai/services/ai_service.py           │
                 │  app/ai/agents/orchestrator.py  (LCEL)   │
                 └───┬──────────────┬───────────────┬───────┘
                     │              │               │
        ┌────────────▼───┐  ┌───────▼────────┐  ┌───▼─────────────────┐
        │ RAG retrieval  │  │ Domain agents  │  │ Tool registry       │
        │ code + docs    │  │ codebase       │  │ 8 read-only tools   │
        │ hybrid (RRF)   │  │ operations     │  │ AUTHORIZATION       │
        │                │  │ travel         │  │ CHOKEPOINT          │
        └────────────────┘  └────────────────┘  └───┬─────────────────┘
                                                     │ read-only calls
                 ┌───────────────────────────────────▼─────────────────┐
                 │  DETERMINISTIC DBARS CORE — unmodified, read-only   │
                 │  app/ml, app/gtfs, app/tracking, app/services       │
                 └─────────────────────────────────────────────────────┘
```

The arrow into the deterministic core points one way. Nothing in `app/ai/`
writes to it, and no AI tool mutates a database record.

## 2. The dependency rule

`app/main.py` imports the AI router inside a `try/except`:

```python
try:
    from app.ai.api.routes import router as ai_router
except Exception as _ai_import_error:
    ai_router = None
```

This is deliberate and load-bearing. The AI layer pulls in `langchain`,
`faiss-cpu` and `sentence-transformers`. Before this guard existed, a missing
optional package raised at module scope and took the **entire backend** down
with it — route prediction, ticketing and GTFS included. The guard applies the
same principle the codebase already uses for `init_db()`: an optional subsystem
may fail, but it may never prevent DBARS from starting.

If the import fails the app logs a warning, registers 82 routes instead of 93,
and every deterministic feature behaves exactly as before.

## 3. Request lifecycle

1. **Authenticate.** `Depends(get_current_user)` validates the bearer token.
   Identity and role come from the token; any `user_id` in the body is ignored.
2. **Bind a principal.** `set_ai_principal(AIPrincipal(user_id, role))` stores
   the caller in a `ContextVar` for the duration of the request, and resets it
   in a `finally` block.
3. **Guardrails.** `SecurityGuardrails.scan_query()` rejects prompt injection,
   jailbreaks and credential probes before any retrieval happens.
4. **Route the query.** `QueryRouter` picks a retrieval mode (code,
   documentation, operations, travel, hybrid) from the query text, unless the
   caller specified one.
5. **Retrieve.** Hybrid retrieval over the code and documentation indices —
   see `AI_RAG_ARCHITECTURE.md`.
6. **Call tools.** Any DBARS read-only tool the query needs, through the
   registry, which enforces role restrictions.
7. **Generate.** A LangChain LCEL chain assembles evidence, tool output and
   history into a prompt for the chat model.
8. **Verify grounding.** `grounding_verifier` labels the answer CONFIRMED,
   INFERRED or UNKNOWN and strips claims the evidence does not support.
9. **Record.** `ai_tracer` stores a stage-by-stage trace with scrubbed text.

## 4. Language model

`app/ai/llm/client.py` exposes `get_chat_model()`, returning a LangChain
`BaseChatModel`.

- With `GEMINI_API_KEY` set, it returns a Gemini chat model.
- Otherwise it returns `GroundedDeterministicChatModel`, which composes answers
  strictly from retrieved evidence and tool output, and says UNKNOWN when the
  evidence does not cover the question.

**The language model is a fallback branch, not the main path.** Measured with
Gemini live and reachable: **1 of 57 benchmark questions actually invoked the
model (1.8%)**. `orchestrator.execute()` is an intent router — it dispatches to
`codebase_assistant`, `operations_assistant` or `travel_assistant`, each of
which formats an answer from retrieved chunks and tool output in Python. The
LCEL chain runs only in the final `else`, for queries no agent claims.

Two consequences worth stating plainly:

- The 0% hallucination rate is architectural. Most answers are assembled from
  evidence, so there is nothing to hallucinate with.
- Which model you configure barely matters. Swapping the deterministic model
  for live Gemini moved mean answer correctness from 0.8150 to 0.8146.

This is a defensible design — it is why grounding is reliable — but describing
the system as "LLM-powered" would substantially overstate the model's role. It
is retrieval and templating, with an LLM available for the long tail.

## 5. Module map

| Path | Responsibility |
|---|---|
| `app/ai/api/routes.py` | HTTP surface, authentication, role gates |
| `app/ai/config.py` | Environment-driven settings |
| `app/ai/models.py` | Pydantic request/response contracts |
| `app/ai/agents/orchestrator.py` | LCEL chain, intent dispatch, tool invocation |
| `app/ai/agents/codebase_agent.py` | Source-code questions |
| `app/ai/agents/operations_agent.py` | Depot/fleet/crew questions |
| `app/ai/agents/travel_agent.py` | Journey planning questions |
| `app/ai/ingestion/` | Repository walk, AST chunking, doc chunking |
| `app/ai/rag/` | Embeddings, FAISS store, BM25, hybrid fusion |
| `app/ai/tools/` | Read-only DBARS tools + authorization chokepoint |
| `app/ai/security/` | Guardrails, grounding, secret filter, authorization |
| `app/ai/memory/session_memory.py` | Per-user conversation and journey context |
| `app/ai/observability/` | Stage tracing, PII scrubbing, metrics |
| `app/ai/evaluation/` | 57-question benchmark and report generation |

## 6. What the AI layer may not do

Enforced, not merely documented:

- No database writes. Every tool reads.
- No shell, Python `eval`, filesystem writes, or outbound HTTP from the model.
- No access to `predictor.py` internals beyond calling its public search.
- No role escalation: the assistant applies the same role checks as the REST
  API, so it cannot be used to read data the caller could not read directly.

See `AI_SECURITY.md`.
