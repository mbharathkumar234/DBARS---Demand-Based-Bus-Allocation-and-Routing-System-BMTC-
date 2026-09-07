# DBARS AI — Evaluation

## 1. The benchmark

57 questions across 12 categories, defined in
`app/ai/evaluation/dataset.py`.

| Category | Questions |
|---|---:|
| code_understanding | 5 |
| architecture | 5 |
| api_understanding | 5 |
| debugging | 4 |
| data_flow | 4 |
| documentation | 4 |
| routing | 5 |
| operations | 5 |
| hallucination_resistance | 5 |
| tool_calling | 5 |
| security | 5 |
| multi_turn | 5 |

Run it:

```bash
cd backend
python -c "import asyncio; from app.ai.evaluation.evaluator import ai_evaluator; \
from app.ai.evaluation.dataset import get_benchmark_dataset; \
asyncio.run(ai_evaluator.run_benchmark(items=get_benchmark_dataset()))"
```

or `POST /ai/evaluation/run` as an admin. The harness binds an admin principal
for its own duration, because the suite includes depot-operations questions and
those tools are role-restricted; without it every operations item would score
as a denial.

## 2. How a question is scored

```python
passed = (
    not hallucination_detected
    and (answer_correctness >= 0.4 or (item.allowed_uncertainty and is_refusal))
    and (tool_correctness >= 0.8 if item.required_tool else True)
    and grounding_ok
)
```

`answer_correctness` is the fraction of the question's expected keywords that
appear in the answer.

## 3. Results

Measured on the full 57-question set:

| Metric | Value |
|---|---|
| Pass rate | **100%** (57/57) |
| **Mean answer correctness** | **81.5%** |
| Median answer correctness | 80.0% |
| Hallucination rate | 0.00% |
| Mean latency | 635 ms |

### Read the pass rate correctly

**A pass requires only 40% keyword coverage.** That is a floor, not a grade.
"100% pass rate" means every answer cleared the floor — not that every answer
was complete. Eight questions passed sitting exactly on it.

**Mean answer correctness (81.5%) is the headline number**, because it is the
one that can actually move. The distribution:

| Keyword coverage | Questions |
|---|---:|
| 0.4 – 0.6 | 8 |
| 0.6 – 0.8 | 15 |
| 0.8 – 1.0 | 7 |
| exactly 1.0 | 27 |

### Where the system is weakest

| Category | Mean answer correctness |
|---|---:|
| debugging | 0.500 |
| documentation | 0.662 |
| data_flow | 0.700 |
| code_understanding | 0.720 |
| routing | 0.800 |
| operations | 0.800 |
| architecture | 0.840 |
| api_understanding | 0.850 |
| tool_calling | 0.900 |
| multi_turn | 0.920 |
| security | 0.967 |
| hallucination_resistance | 1.000 |

Debugging is the weakest category and the honest ceiling on what this system
does well: it retrieves and grounds, it does not reason about a failure it has
not been shown.

### How much of this is the language model?

Measured with a live Gemini key configured and `gemini-3.6-flash` reachable:

| | |
|---|---|
| Benchmark questions | 57 |
| Questions that actually invoked the LLM | **1** |
| Share | **1.8%** |

`orchestrator.execute()` is an intent router. It dispatches to
`codebase_assistant`, `operations_assistant` or `travel_assistant`, which build
answers in Python from retrieved chunks and tool output. The LCEL chain is the
final `else` branch, reached only by queries no agent claims — and all 12
benchmark categories are designed around those agents.

Swapping models therefore changes almost nothing:

| Configuration | Mean answer correctness | Mean latency |
|---|---|---|
| Deterministic grounded model (offline) | 0.8150 | 635 ms |
| Live Gemini `gemini-3.6-flash` | 0.8146 | 632 ms |

These scores measure **retrieval and templating quality**, not model quality.
Reporting them as an LLM benchmark would be wrong.

### On the 0% hallucination rate

Most answers are assembled from retrieved evidence and tool output rather than
generated, so there is structurally nothing to hallucinate with. A 0%
hallucination rate is a property of the architecture, not evidence that a
generative model was tested and found truthful — and as measured above, only
1.8% of answers involve the model at all. The figure would need re-establishing
for any design that routes more traffic through the LLM.

## 4. Prior report

An earlier `ai_benchmark_report.md` claimed "Overall Accuracy 100.0%" with all
targets PASSED, while its own header recorded `Total Questions Evaluated: 2`
and its category table listed a single category. The prose alongside claimed
evaluation "across 12 distinct functional categories" and that "zero metrics
are fabricated". It had been generated with `limit=2`.

The generator now leads with mean answer correctness, labels the pass rate with
its 40% floor, and reports the question count actually evaluated.

## 5. Artifacts

| File | Contents |
|---|---|
| `backend/artifacts/ai_benchmark_evaluation.json` | Per-question results |
| `backend/artifacts/ai_benchmark_report.md` | Human-readable report |
| `backend/artifacts/codebase_qa_evaluation.json` | 26-question codebase QA run |
| `backend/artifacts/codebase_qa_report.md` | Retrieval-source comparison |

## 6. Test suite

278 backend tests pass, including 19 in `tests/test_ai_authorization.py`
covering authentication, role enforcement, fail-closed tool authorization and
session isolation.

```bash
cd backend && pytest tests
```
