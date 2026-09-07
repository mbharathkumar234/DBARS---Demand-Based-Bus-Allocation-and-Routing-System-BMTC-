"""CLI runner for the DBARS AI Evaluation Benchmark Suite."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

# Ensure backend root is in sys.path
backend_dir = Path(__file__).resolve().parent.parent.parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app.ai.evaluation.dataset import (
    BENCHMARK_DATASET,
    EvaluationCategory,
    get_benchmark_dataset,
    get_dataset_by_category,
)
from app.ai.evaluation.evaluator import AIEvaluationRunner


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run DBARS AI Intelligence Layer Empirical Benchmark Suite",
    )
    parser.add_argument(
        "--category",
        "-c",
        type=str,
        default=None,
        help="Run benchmark for a specific category (e.g. routing, hallucination_resistance)",
    )
    parser.add_argument(
        "--limit",
        "-l",
        type=int,
        default=None,
        help="Limit number of evaluation questions to run",
    )
    parser.add_argument(
        "--output-dir",
        "-o",
        type=str,
        default=None,
        help="Custom output directory for evaluation reports (defaults to backend/artifacts)",
    )
    parser.add_argument(
        "--min-accuracy",
        type=float,
        default=0.80,
        help="Minimum acceptable accuracy threshold (default: 0.80)",
    )
    return parser.parse_args()


async def main() -> int:
    args = parse_args()
    print("=" * 72)
    print("      DBARS AI Intelligence Layer — Empirical Benchmark Suite")
    print("=" * 72)

    if args.category:
        print(f"Filter Category : {args.category}")
        items = get_dataset_by_category(args.category)
        if not items:
            print(f"Error: Unknown or empty category '{args.category}'.")
            print(f"Available categories: {[c.value for c in EvaluationCategory]}")
            return 1
    else:
        print("Scope           : All 12 Benchmark Categories")
        items = get_benchmark_dataset()

    if args.limit and args.limit > 0:
        items = items[:args.limit]
        print(f"Limit           : Running first {len(items)} items")

    print(f"Total Questions : {len(items)}")
    print("-" * 72)

    evaluator = AIEvaluationRunner(output_dir=args.output_dir)
    summary = await evaluator.run_benchmark(items=items)

    print("\n" + "=" * 72)
    print("                       BENCHMARK RESULTS")
    print("=" * 72)
    print(f"Overall Accuracy         : {summary.overall_accuracy * 100:.1f}% ({summary.passed_questions}/{summary.total_questions} passed)")
    print(f"Answer Correctness       : {summary.overall_answer_correctness * 100:.1f}%")
    print(f"Retrieval Relevance      : {summary.overall_retrieval_relevance * 100:.1f}%")
    print(f"Source Correctness       : {summary.overall_source_correctness * 100:.1f}%")
    print(f"Hallucination Rate       : {summary.overall_hallucination_rate * 100:.2f}%")
    print(f"Tool-Calling Correctness : {summary.overall_tool_correctness * 100:.1f}%")
    print(f"Citation Precision       : {summary.overall_citation_precision * 100:.1f}%")
    print(f"Mean Latency             : {summary.avg_latency_ms:.1f} ms")
    print("-" * 72)

    print("\nCATEGORY BREAKDOWN:")
    for cat_name, cs in summary.category_summaries.items():
        print(
            f"  * {cat_name:<28} : {cs.accuracy * 100:5.1f}% acc | "
            f"{cs.passed_questions}/{cs.total_questions} pass | "
            f"{cs.hallucination_rate * 100:4.1f}% halluc | "
            f"{cs.avg_latency_ms:6.1f} ms"
        )

    print("\nArtifacts Exported:")
    print(f"  * JSON Report : {evaluator.output_dir / 'ai_benchmark_evaluation.json'}")
    print(f"  * Markdown    : {evaluator.output_dir / 'ai_benchmark_report.md'}")
    print("=" * 72)

    if summary.overall_accuracy >= args.min_accuracy:
        print(f"[PASS] BENCHMARK PASSED (Accuracy {summary.overall_accuracy*100:.1f}% >= {args.min_accuracy*100:.1f}%)\n")
        return 0
    else:
        print(f"[FAIL] BENCHMARK FAILED (Accuracy {summary.overall_accuracy*100:.1f}% < {args.min_accuracy*100:.1f}%)\n")
        return 1


if __name__ == "__main__":
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    sys.exit(asyncio.run(main()))

