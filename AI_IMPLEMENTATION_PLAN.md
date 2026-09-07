# DBARS AI Intelligence Layer — Implementation Plan and Status

Phases 0–17 as specified, with what is in the tree today. Status is
evidence-based: "Complete" means verified by a passing test, a live request, or
a produced artifact.

| # | Phase | Status | Evidence |
|---|---|---|---|
| 0 | Protect the deterministic core | **Complete** | `AI_PROTECTED_FILES.md`; `git status` shows no protected file modified; 259 pre-existing tests pass |
| 1 | Subsystem scaffold | **Complete** | `backend/app/ai/`, 47 modules, 7,833 lines |
| 2 | Codebase ingestion | **Complete** | 183 files, 1,078 AST chunks, `code_ingestion_report.json` |
| 3 | Documentation ingestion | **Complete** | 23 files, 326 chunks, `doc_ingestion_report.json` |
| 4 | Vector store | **Complete** | FAISS `IndexFlatIP`, 3.3 MB code index, 1.3 MB doc index |
| 5 | Hybrid retrieval | **Complete** | BM25 (`k1=1.5`, `b=0.75`) fused with vectors by RRF (`k=60`) |
| 6 | LangChain orchestration | **Complete** | LCEL chain in `agents/orchestrator.py`; `langchain-core` 0.3.29 |
| 7 | LLM integration | **Complete after remediation** | Was non-functional: imported `ChatGoogleGenerativeAI` from `langchain_community`, which does not define it. Rewritten over the `google-generativeai` SDK and verified live on `gemini-3.6-flash`. **Only 1.8% of answers reach it** — see below |
| 8 | Read-only tool layer | **Complete** | 8 tools; no write path; `AI_TOOL_REFERENCE.md` |
| 9 | Codebase assistant | **Complete** | `codebase_qa_report.md`: 25/26 source-retrieval questions correct |
| 10 | Operations assistant | **Complete** | `tests/test_operations_assistant.py`; live fleet/crew answers |
| 11 | Travel assistant | **Complete** | `tests/test_travel_assistant.py`; live journey planning |
| 12 | Grounding & hallucination control | **Complete** | `security/grounding_verifier.py`; 0 hallucinations over 57 questions; adversarial routes answered UNKNOWN |
| 13 | Conversational memory | **Complete** | `memory/session_memory.py`; multi-turn + PII redaction tests |
| 14 | Frontend UI | **Complete** | `AIAssistantModal.tsx`, `AIFloatingTrigger.tsx`, `AIContext.tsx`, `aiService.ts`; production build clean |
| 15 | Security & guardrails | **Complete after remediation** | See below |
| 16 | Observability | **Complete** | Stage tracer, PII scrubber, p50/p95/p99 metrics, admin-gated endpoints |
| 17 | Evaluation framework | **Complete after remediation** | 57 questions, 12 categories; `AI_EVALUATION.md` |

## Phases that required remediation

Both were delivered in a state that passed their own tests while being wrong.

### Phase 15 — Security

The layer shipped with **no authentication on any endpoint**. Every
`require_role` occurrence in `app/ai/` was a string inside a prompt or a regex,
not an enforced check. Consequences, all confirmed against a running server:

1. `POST /ai/chat` returned depot fleet data anonymously that
   `GET /depot/blocking-plan` refuses with 401.
2. `GET /ai/session/{id}/history` leaked any user's conversation and journey
   context to anyone supplying the id pair.
3. `DELETE /ai/observability/traces` was an anonymous destructive call.
4. `GET /ai/observability/traces` exposed all users' question text.
5. `POST /ai/evaluation/run` let anyone trigger an expensive benchmark.

`session_memory.verify_isolation()` existed but was never called — dead
security code.

Remediation: token-derived identity and role, a `ContextVar` principal, a
role check at the tool-registry chokepoint, admin gates on observability and
evaluation, and 19 regression tests.

### Phase 17 — Evaluation

The published report claimed "Overall Accuracy 100.0%", "all targets PASSED"
and "zero metrics are fabricated", over **2 questions in 1 category**, while
57 questions across 12 categories were defined. Remediated in
`AI_EVALUATION.md`.

### Phase 7 — LLM integration

The binding never worked. `client.py` imported `ChatGoogleGenerativeAI` from
`langchain_community.chat_models`, which does not define it; the resulting
ImportError was caught by a broad `except` and logged as a fallback, so the
layer quietly ran offline no matter what key was configured. Three further
faults sat behind it: `app/ai/config.py` never loaded `.env`, the configured
`gemini-1.5-flash` no longer exists on the API, and `gemini-2.5-flash` is
closed to new keys.

With all four fixed and Gemini verified live, the measurement that matters:
**1 of 57 benchmark questions actually invoked the model (1.8%)**. The
orchestrator is an intent router into hand-written agents; the LCEL chain is
the fallback for queries no agent claims. Mean answer correctness moved from
0.8150 (offline) to 0.8146 (live Gemini).

## Defects found and fixed outside the phase list

| Defect | Severity | Fix |
|---|---|---|
| AI dependencies undeclared in `requirements.txt` while imported at module scope — a fresh `pip install` produced a backend that could not start at all | **Critical** | Dependencies declared; AI router import guarded so the deterministic core survives AI failure |
| Tool denial crashed the operations agent with a type error | Medium | Structured denial record + explicit handling |
| Circular import introduced by the authorization module | Medium | Deferred function-level import |
| Frontend session calls sent no bearer token | Medium | Shared `authHeaders()` helper |
| AI trigger offered to signed-out visitors, who would hit 401 | Low | Gated on `isAuthenticated` |
| Embedding provider ignored configuration; `all-MiniLM-L6-v2` configured but never used | Medium | Provider made selectable and documented; index records which built it |
| `backend/scratch/` debug scripts untracked and uncommitted | Low | Added to `.gitignore` |

## Configuration

```bash
AI_ENABLED=true
LLM_PROVIDER=auto                      # auto | gemini | openai | offline
AI_MODEL_NAME=gemini-1.5-flash
GEMINI_API_KEY=                        # unset -> deterministic grounded model
AI_EMBEDDING_PROVIDER=deterministic    # or sentence-transformers
AI_EMBEDDING_MODEL=all-MiniLM-L6-v2
AI_MAX_QUERY_LENGTH=1000
AI_MAX_CONTEXT_LENGTH=8000
AI_SESSION_HISTORY_LIMIT=10
AI_ENABLE_PROMPT_GUARDRAILS=true
```

Switching `AI_EMBEDDING_PROVIDER` requires rebuilding both indices.
