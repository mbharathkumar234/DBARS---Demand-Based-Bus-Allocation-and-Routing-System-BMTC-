"""AI Evaluation benchmarks, datasets, and verification runners."""

from app.ai.evaluation.dataset import (
    BENCHMARK_DATASET,
    EvaluationCategory,
    EvaluationItem,
    get_benchmark_dataset,
    get_dataset_by_category,
    get_category_counts,
)
from app.ai.evaluation.evaluator import (
    AIEvaluationRunner,
    BenchmarkSummary,
    CategorySummary,
    EvaluationResult,
    ai_evaluator,
)

__all__ = [
    "BENCHMARK_DATASET",
    "EvaluationCategory",
    "EvaluationItem",
    "get_benchmark_dataset",
    "get_dataset_by_category",
    "get_category_counts",
    "AIEvaluationRunner",
    "BenchmarkSummary",
    "CategorySummary",
    "EvaluationResult",
    "ai_evaluator",
]
