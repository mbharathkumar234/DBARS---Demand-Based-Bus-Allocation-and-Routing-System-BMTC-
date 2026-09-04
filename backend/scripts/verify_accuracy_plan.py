#!/usr/bin/env python3
"""Phase 5 — Verification script.

Checks every acceptance criterion from Phases 1-3 against the live
predictor and stored metrics.  Prints a PASS/FAIL table and exits
non-zero if any criterion fails.

Usage:
    cd backend
    python scripts/verify_accuracy_plan.py
"""
from __future__ import annotations

import json
import os
import random
import subprocess
import sys
import time
from pathlib import Path

# Ensure the backend package is importable
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

os.environ.setdefault("DATASET_PATH", str(backend_dir.parent / "dataset" / "routes_cleaned.csv"))
os.environ.setdefault("STOP_COORDINATES_PATH", str(backend_dir.parent / "dataset" / "stops_cleaned.csv"))
os.environ.setdefault("METRO_DATASET_PATH", str(backend_dir.parent / "dataset" / "bengaluru_metro_network.csv"))
os.environ.setdefault("FARES_DATASET_PATH", str(backend_dir.parent / "dataset" / "fares.json"))
os.environ.setdefault("ARTIFACT_DIR", str(backend_dir / "artifacts"))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

METRICS_PATH = backend_dir / "artifacts" / "metrics.json"

# ── Criterion definitions ────────────────────────────────────────────────

class Criterion:
    def __init__(self, phase: str, number: str, description: str):
        self.phase = phase
        self.number = number
        self.description = description
        self.passed = False
        self.detail = ""

    def check(self, condition: bool, detail: str = "") -> bool:
        self.passed = condition
        self.detail = detail
        return condition


def main() -> int:
    criteria: list[Criterion] = []

    # Load metrics
    if not METRICS_PATH.exists():
        print(f"FATAL: {METRICS_PATH} not found. Run train.py first.")
        return 1

    data = json.loads(METRICS_PATH.read_text(encoding="utf-8"))
    metrics = data.get("metrics", {})

    # ── PHASE 1 ──────────────────────────────────────────────────────────

    c = Criterion("1", "1.1", "relevance_set_metrics present in metrics.json")
    c.check("relevance_set_metrics" in metrics, str(bool("relevance_set_metrics" in metrics)))
    criteria.append(c)

    rsm = metrics.get("relevance_set_metrics", {})
    lenient_top1 = rsm.get("accuracy_top_1", 0)
    sample_count = metrics.get("live_test_samples", 0)
    c = Criterion("1", "1.2", f"COVERAGE (not accuracy): valid-route rate = {lenient_top1}  (threshold >= 0.95, n={sample_count})")
    c.check(lenient_top1 >= 0.95)
    criteria.append(c)

    # All models scored on identical sample count
    candidate_models = metrics.get("candidate_models", {})
    test_n = metrics.get("test_samples", 0)
    live_n = metrics.get("live_test_samples", 0)
    c = Criterion("1", "1.3", f"all models scored on n={test_n} (live={live_n})")
    c.check(test_n == live_n and test_n >= 60, f"test={test_n}, live={live_n}")
    criteria.append(c)

    c = Criterion("1", "1.4", f"exact_route_match retained ({metrics.get('exact_route_match', {}).get('accuracy_top_1', 'missing')})")
    c.check("exact_route_match" in metrics)
    criteria.append(c)

    headline = metrics.get("headline_metric", "missing")
    c = Criterion("1", "1.5", f"headline metric declared ({headline})")
    c.check("headline_metric" in metrics and headline in metrics)
    criteria.append(c)

    # The headline must be a metric the system can actually FAIL.
    # coverage/relevance_set is near-tautological (its relevance set comes
    # from the same index the search uses), so it must not be the headline.
    c = Criterion("1", "1.7", f"headline is a discriminating metric, not coverage ({headline})")
    c.check(headline == "rank_quality")
    criteria.append(c)

    c = Criterion("1", "1.8", "coverage_caveat documents the near-circularity")
    caveat = metrics.get("coverage_caveat", "")
    c.check(bool(caveat) and "same index" in caveat.lower())
    criteria.append(c)

    # Determine python executable (prefer local backend .venv if available)
    py_exe = sys.executable
    venv_py = backend_dir / ".venv" / "Scripts" / "python.exe"
    if not venv_py.exists():
        venv_py = backend_dir / ".venv" / "bin" / "python"
    if venv_py.exists():
        py_exe = str(venv_py)

    # Run pytest and count passes
    c = Criterion("1", "1.6", "pytest: tests pass")
    try:
        result = subprocess.run(
            [py_exe, "-m", "pytest", "tests", "-q", "--tb=no"],
            capture_output=True, text=True, cwd=str(backend_dir), timeout=300,
        )
        # Parse "N passed" from output
        output = result.stdout + result.stderr
        import re
        match = re.search(r"(\d+) passed", output)
        passed_count = int(match.group(1)) if match else 0
        c.check(result.returncode == 0, f"{passed_count} passed, exit={result.returncode}")
    except Exception as e:
        c.check(False, str(e))
    criteria.append(c)

    # ── PHASE 2 ──────────────────────────────────────────────────────────

    rq = metrics.get("rank_quality", {})

    c = Criterion("2", "2.1", "rank_quality block present")
    c.check(bool(rq))
    criteria.append(c)

    bor = rq.get("best_option_rate", -1)
    c = Criterion("2", "2.2", f"baseline best_option_rate recorded ({bor})")
    c.check(bor >= 0)
    criteria.append(c)

    mpr = rq.get("mean_percentile_rank", -1)
    c = Criterion("2", "2.3", f"baseline mean_percentile_rank recorded ({mpr})")
    c.check(mpr >= 0)
    criteria.append(c)

    c = Criterion("2", "2.4", "\"Best\" definition documented in rank_quality")
    c.check("definition" in rq, rq.get("definition", "missing"))
    criteria.append(c)

    c = Criterion("2", "2.5", "rank_quality_report.py runs")
    try:
        result = subprocess.run(
            [py_exe, "scripts/rank_quality_report.py"],
            capture_output=True, text=True, cwd=str(backend_dir), timeout=30,
        )
        c.check(result.returncode == 0, f"exit={result.returncode}")
    except Exception as e:
        c.check(False, str(e))
    criteria.append(c)

    # ── PHASE 3 ──────────────────────────────────────────────────────────

    c = Criterion("3", "3.1", f"best_option_rate {bor}  (threshold >= 0.70, baseline 0.57)")
    c.check(bor >= 0.70 if bor >= 0 else False)
    criteria.append(c)

    c = Criterion("3", "3.2", f"mean_percentile_rank {mpr}  (threshold <= 0.10, baseline 0.14)")
    c.check(mpr <= 0.10 if mpr >= 0 else False)
    criteria.append(c)

    w2r = rq.get("within_2_stops_rate", -1)
    c = Criterion("3", "3.3", f"within_2_stops_rate {w2r}  (threshold >= 0.92, baseline 0.90)")
    c.check(w2r >= 0.92 if w2r >= 0 else False)
    criteria.append(c)

    c = Criterion("3", "3.4", f"lenient top-1 not regressed ({lenient_top1} >= 0.95)")
    c.check(lenient_top1 >= 0.95)
    criteria.append(c)

    # ── PHASE 3 (live) ───────────────────────────────────────
    #
    # The checks above read artifacts/metrics.json.  That file is generated
    # by the very code under test, so on its own it proves only that the
    # numbers were WRITTEN, not that they are still TRUE.  A stale or
    # hand-edited metrics.json would sail through.
    #
    # These last checks therefore re-run a real evaluation on a fixed seed
    # and compare the outcome against the stored figures.  This is the
    # difference between verifying a claim and re-deriving it.

    print("  (re-running live evaluation on a fixed seed — takes ~60s)",
          file=sys.stderr)

    from app.core.config import settings
    from app.ml.predictor import BMTCBusPredictor

    predictor = BMTCBusPredictor(settings.dataset_path, settings.artifact_dir)
    predictor.train()

    random.seed(42)
    evaluable = [r for r in predictor.routes if len(r.stops) >= 4]
    raw = []
    for route in evaluable:
        start = random.randint(0, max(0, len(route.stops) - 3))
        dest = random.randint(start + 1, len(route.stops) - 1)
        raw.append((route.route_number, route.stops[start], route.stops[dest]))
    random.shuffle(raw)
    live_n = 40
    live_raw = raw[:live_n]

    live_samples = []
    for expected, a, b in live_raw:
        valid = predictor._valid_routes_for_pair(a, b) or {expected}
        live_samples.append((valid, a, b))

    live_hits = 0
    for valid, a, b in live_samples:
        try:
            suggestions = predictor._find_transfer_suggestions(a, b, limit=5)
        except Exception:
            suggestions = []
        if suggestions:
            first = {leg.get("bus_number") for leg in suggestions[0].get("legs", [])}
            live_hits += int(bool(first & valid))
    live_top1 = live_hits / max(len(live_samples), 1)

    c = Criterion("3L", "3.7", f"LIVE lenient top-1 re-derived = {live_top1:.4f} on n={len(live_samples)} (>= 0.95)")
    c.check(live_top1 >= 0.95)
    criteria.append(c)

    live_rq = predictor._compute_rank_quality(live_samples)
    live_bor = live_rq.get("best_option_rate", -1)
    c = Criterion("3L", "3.8", f"LIVE best_option_rate re-derived = {live_bor} (>= 0.70)")
    c.check(live_bor >= 0.70 if live_bor >= 0 else False)
    criteria.append(c)

    # Stored vs re-derived must agree, or metrics.json is stale.
    drift = abs(live_bor - bor) if (live_bor >= 0 and bor >= 0) else 1.0
    c = Criterion("3L", "3.9", f"stored vs live best_option_rate agree (stored {bor}, live {live_bor}, drift {drift:.3f} <= 0.15)")
    c.check(drift <= 0.15)
    criteria.append(c)

    # Criterion 3.5 from the plan: latency must not have regressed.
    latency_pairs = [
        ("Majestic", "Marathahalli"), ("Banashankari", "Hebbal"),
        ("Shivajinagar", "Kengeri"), ("Hebbal", "Silk Board"),
        ("KR Market", "Jayanagar"), ("Majestic", "Whitefield"),
        ("Yelahanka", "Electronic City"), ("Peenya", "HSR Layout"),
        ("Whitefield", "Kengeri"), ("Marathahalli", "Peenya"),
    ]
    timings = []
    for a, b in latency_pairs:
        t0 = time.perf_counter()
        try:
            predictor.predict(a, b, 5)
        except Exception:
            pass
        timings.append(time.perf_counter() - t0)
    timings.sort()
    p90 = timings[int(len(timings) * 0.9)]
    c = Criterion("3L", "3.5", f"p90 search latency {p90:.2f}s (threshold <= 1.6s)")
    c.check(p90 <= 1.6)
    criteria.append(c)

    # ── Print results ────────────────────────────────────────────────────

    print()
    print("DBARS ACCURACY PLAN — VERIFICATION")
    print("=" * 66)

    current_phase = ""
    passed_count = 0
    failed_count = 0

    for c in criteria:
        if c.phase != current_phase:
            current_phase = c.phase
            phase_names = {
                "1": "metric measures correctness",
                "2": "rank quality instrumented",
                "3": "ranking improved (stored metrics)",
                "3L": "ranking improved (RE-DERIVED LIVE)",
            }
            print(f"\nPHASE {current_phase} — {phase_names.get(current_phase, '')}")

        status = "PASS" if c.passed else "FAIL"
        if c.passed:
            passed_count += 1
        else:
            failed_count += 1
        print(f"  [{status}] {c.number} {c.description}")

    print()
    print("=" * 66)
    result_str = f"RESULT: {passed_count} passed, {failed_count} failed"
    if failed_count > 0:
        print(f"{result_str}  ->  EXIT 1")
    else:
        print(f"{result_str}  ->  EXIT 0")
    print()

    return 1 if failed_count > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
