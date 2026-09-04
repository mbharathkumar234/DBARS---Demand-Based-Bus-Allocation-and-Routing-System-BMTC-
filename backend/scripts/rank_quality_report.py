#!/usr/bin/env python3
"""Phase 2 — Rank-quality report.

Prints the rank-quality distribution from the latest metrics.json, showing
how often the search returns the *best* valid bus (fewest stops, then highest
frequency) and the overall percentile-rank distribution.

Usage:
    cd backend
    python scripts/rank_quality_report.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

METRICS_PATH = Path(__file__).resolve().parent.parent / "artifacts" / "metrics.json"


def main() -> int:
    if not METRICS_PATH.exists():
        print(f"ERROR: {METRICS_PATH} not found. Run train.py first.", file=sys.stderr)
        return 1

    data = json.loads(METRICS_PATH.read_text(encoding="utf-8"))
    metrics = data.get("metrics", {})
    rq = metrics.get("rank_quality", {})

    if not rq:
        print("ERROR: rank_quality block missing from metrics.json.", file=sys.stderr)
        print("Re-run train.py with force=True to regenerate.", file=sys.stderr)
        return 1

    print("=" * 66)
    print("DBARS — RANK QUALITY REPORT")
    print("=" * 66)
    print()
    print(f"  Definition of 'best':  {rq.get('definition', 'N/A')}")
    print(f"  Samples evaluated:     {rq.get('sample_count', 'N/A')}")
    print()
    print("  Metric                    Value")
    print("  " + "-" * 40)
    print(f"  best_option_rate          {rq.get('best_option_rate', 'N/A')}")
    print(f"  mean_percentile_rank      {rq.get('mean_percentile_rank', 'N/A')}")
    print(f"  within_2_stops_rate       {rq.get('within_2_stops_rate', 'N/A')}")
    print(f"  ndcg_at_5                 {rq.get('ndcg_at_5', 'N/A')}")
    print()

    # Show relevance-set vs strict comparison
    relevance = metrics.get("relevance_set_metrics", {})
    strict = metrics.get("exact_route_match", {})
    headline = metrics.get("headline_metric", "N/A")

    print("  Scoring comparison:")
    print("  " + "-" * 50)
    print(f"  {'Metric':<30} {'Relevance-set':>14} {'Strict':>10}")
    print(f"  {'top-1':.<30} {relevance.get('accuracy_top_1', 'N/A'):>14} {strict.get('accuracy_top_1', 'N/A'):>10}")
    print(f"  {'top-3':.<30} {relevance.get('accuracy_top_3', 'N/A'):>14} {strict.get('accuracy_top_3', 'N/A'):>10}")
    print(f"  {'top-5':.<30} {relevance.get('accuracy_top_5', 'N/A'):>14} {strict.get('accuracy_top_5', 'N/A'):>10}")
    print()
    print(f"  Headline metric: {headline}")
    print(f"  All models scored on n={metrics.get('test_samples', 'N/A')} (live={metrics.get('live_test_samples', 'N/A')})")
    print()
    print("=" * 66)
    return 0


if __name__ == "__main__":
    sys.exit(main())
