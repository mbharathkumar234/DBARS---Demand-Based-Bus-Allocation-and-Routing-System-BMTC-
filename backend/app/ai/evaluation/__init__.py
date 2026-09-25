"""AI Evaluation benchmarks, datasets, and verification runners.

The evaluator is loaded lazily: it imports the orchestrator, which builds the
chat model and pings Gemini. Running the retrieval benchmark -- which never
generates an answer -- used to spend a Gemini request on that import.
"""

from app.ai.evaluation.dataset import (
    BENCHMARK_DATASET,
    EvaluationCategory,
    EvaluationItem,
    get_benchmark_dataset,
    get_dataset_by_category,
    get_category_counts,
)

_EVALUATOR_EXPORTS = {
    "AIEvaluationRunner",
    "BenchmarkSummary",
    "CategorySummary",
    "EvaluationResult",
    "ai_evaluator",
}


def __getattr__(name: str):
    if name in _EVALUATOR_EXPORTS:
        from app.ai.evaluation import evaluator
        return getattr(evaluator, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "BENCHMARK_DATASET",
    "EvaluationCategory",
    "EvaluationItem",
    "get_benchmark_dataset",
    "get_dataset_by_category",
    "get_category_counts",
    *sorted(_EVALUATOR_EXPORTS),
]
