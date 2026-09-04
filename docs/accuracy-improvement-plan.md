# DBARS — Route Prediction Accuracy: Diagnosis and Phased Improvement Plan

> **Read the diagnosis before the plan.** The headline finding changes what
> "improving accuracy" means for this project. Measurements below were taken by
> running the real predictor against the real dataset; every number is
> reproducible with the scripts named in each phase.

---

## Phase 0 — Diagnosis (COMPLETE)

### 0.1 What the reported numbers actually measure

`metrics.json` reports the shipped model (`LiveTransferSearch`) at:

| Metric | Reported |
|---|---|
| top-1 | 0.2000 |
| top-3 | 0.2667 |
| top-5 | 0.3333 |
| cross-validated top-5 | 0.4312 |

The evaluation builds each test sample in `_evaluate_models()` like this:

```python
start = random.randint(0, max(0, len(route.stops) - 3))
dest  = random.randint(start + 1, len(route.stops) - 1)
samples.append((route.route_number, route.stops[start], route.stops[dest]))
```

So a sample is `(the route it was drawn from, stop_A, stop_B)`, and scoring
counts a prediction correct **only if it names that exact route number**.

### 0.2 The problem with that

Many buses legitimately serve the same ordered stop pair. Measured across the
120 test samples:

| Distinct buses serving the sampled pair | Value |
|---|---|
| minimum | 1 |
| **median** | **22** |
| mean | 47.8 |
| p90 | 116 |
| maximum | 521 |
| pairs served by exactly one bus | 8 of 120 (7%) |
| pairs served by five or more | 93 of 120 (78%) |

A system that **always** returns a correct bus, picking uniformly among the
valid ones, would score top-1 of only **0.16**. The reported 0.20 is already
*above* that ceiling.

**The metric is not measuring whether the answer is right. It is measuring
whether the system guessed which one of a median 22 correct answers the sample
generator happened to pick.**

### 0.3 What the real accuracy is

Same searches, same samples, scored two ways:

| Scoring | 15 live samples | 60 live samples |
|---|---|---|
| **STRICT** — must name the exact sampled route (current metric) | 0.2000 | 0.1667 |
| **LENIENT** — any bus that genuinely serves the pair in order | **1.0000** | **1.0000** |
| Searches returning no result at all | 0 of 15 | 0 of 60 |

**60 out of 60 searches returned a bus that genuinely serves the requested
stop pair in the correct order. Zero failures.**

### 0.4 What *can* still be improved

Correctness is saturated, so the useful question becomes: when it returns a
valid bus, is it a *good* one? Measured over 60 live searches, comparing the
returned route against every valid route for that pair, ranked by the number of
intermediate stops:

| Measure | Value |
|---|---|
| Returned the fewest-stop option | **34 of 60 (57%)** |
| Within 2 stops of the fewest-stop option | 54 of 60 (90%) |
| Mean stops on returned route | 10.2 |
| Mean stops on the best available option | 9.1 |
| **Mean percentile rank** (0 = best, 1 = worst) | **0.14** |

### 0.5 A third defect: unequal comparison

`LiveTransferSearch` is scored on **15** samples; the other three models on
**120**. With 15 samples one hit moves top-1 by 6.7 points, and a 95%
confidence interval around 0.20 spans roughly 0.04–0.48. The four models are
not being compared on equal footing, so `best_candidate_model` is not a
meaningful selection.

### 0.6 Conclusion that drives the plan

| Claim | Verdict |
|---|---|
| The route prediction model is inaccurate | **FALSE** — 60/60 valid answers |
| The reported accuracy number is wrong | **TRUE** — it measures label-guessing |
| Nothing can be improved | **FALSE** — ranking quality is 57%, and movable |
| The benchmark is a fair comparison | **FALSE** — 15 samples vs 120 |

So this is **not** a modelling problem. Phases 1–2 fix measurement, Phase 3
improves the one thing that is genuinely improvable, and Phase 5 proves the
work was done.

---

## Addendum (post-implementation) — the coverage metric is near-circular

Implementing the plan exposed a flaw in the plan itself, recorded here rather
than quietly corrected.

`_valid_routes_for_pair()` builds the relevance set by reading
`stop_pair_to_segments[(A, B)]` — **the same index `_find_transfer_suggestions()`
uses to generate its candidates.** So the lenient metric asks "did the search
return a route from the index it searched?", which is close to tautological. It
cannot fall meaningfully below 1.0 without an outright bug.

Consequences, adopted in the implementation:

* The relevance-set number is reported as **coverage, not accuracy**. It proves
  the search never fails to find a valid route. It says nothing about quality.
* **`rank_quality` is the headline metric**, because it scores against an
  independent criterion (fewest stops, then frequency) that the ranker was not
  guaranteed to satisfy — and did not, at 0.57 before tuning. A metric you can
  fail is a metric that means something.
* `metrics.json` carries a `coverage_caveat` field stating this, and verifier
  criteria 1.7 and 1.8 fail the build if the headline is ever set back to a
  coverage metric or the caveat is removed.

**Never present this work as "accuracy improved from 20% to 100%."** Changing a
metric and reporting a higher number is indistinguishable from moving the
goalposts unless you can show the old metric could not discriminate (ceiling
0.16, measured) and that the new headline is one you can fail (0.57, measured).
Both are true here — but the burden of proof is entirely on the presenter.

---

## Phase 1 — Make the metric measure correctness

**Goal:** the reported accuracy reflects whether the answer is right.
**Effort:** ~1 day. **Risk:** low — no change to serving code.

### Work

1. Add `_valid_routes_for_pair(stop_a, stop_b) -> set[str]` to
   `ml/predictor.py`. It returns every route whose `stop_positions` contain
   both stops with `min(pos_a) < max(pos_b)`. Reuses existing indexes; measured
   cost 0.2 s for 120 pairs.
2. Change the sample tuple from a single expected route to a **relevance set**:
   `(valid_routes: set[str], stop_a, stop_b)`.
3. Rewrite `_score_samples()` and `_score_samples_live()` to score a hit when
   the returned bus is **in the relevance set**.
4. Redefine precision@5 honestly: `|returned ∩ valid| / 5` is misleading when
   only 5 of 22 valid routes can fit. Use
   `precision@k = |returned ∩ valid| / min(k, |valid|)`.
5. Score **all four models on the same sample set**. If `LiveTransferSearch` is
   too slow for 120 samples, reduce every model to the same N — never compare
   15 against 120.
6. Keep the old strict number as `exact_route_match` so the change is visible
   rather than silently flattering.

### Acceptance criteria (verified in Phase 5)

| # | Criterion | Threshold |
|---|---|---|
| 1.1 | `metrics.json` contains `relevance_set_metrics` | present |
| 1.2 | Lenient top-1 on ≥60 samples | **≥ 0.95** |
| 1.3 | Every model scored on an identical sample count | equal N |
| 1.4 | `exact_route_match` retained for comparison | present |
| 1.5 | `metrics.json` states which metric is headline | present |
| 1.6 | Full test suite still green | 161 pass |

> Threshold 1.2 is set at 0.95 against a measured 1.00 on 60 samples, leaving
> headroom for harder pairs in the full 120.

---

## Phase 2 — Add a ranking-quality metric that can discriminate

**Goal:** measure the one thing still improvable, so Phase 3 has a target.
**Effort:** ~1 day. **Risk:** low — instrumentation only.

### Work

1. Define "best" explicitly as a documented composite, not an opinion. Start
   with three components already available per route:
   - stop span (fewer intermediate stops)
   - trip frequency (`trip_count` — shorter expected wait)
   - route distance
2. Add to the evaluation:
   - `best_option_rate` — top result is the optimal valid route
   - `mean_percentile_rank` — 0 = best available, 1 = worst
   - `within_2_stops_rate`
   - `ndcg_at_5` using span-based graded relevance
3. Record the **baseline** in `metrics.json` so movement is provable.
4. Write `scripts/rank_quality_report.py` printing the distribution.

### Acceptance criteria

| # | Criterion | Threshold |
|---|---|---|
| 2.1 | `metrics.json` contains `rank_quality` | present |
| 2.2 | Baseline `best_option_rate` recorded | ≈ 0.57 |
| 2.3 | Baseline `mean_percentile_rank` recorded | ≈ 0.14 |
| 2.4 | "Best" definition documented in the module docstring | present |
| 2.5 | Report script runs and prints a distribution | exit 0 |

---

## Phase 3 — Improve ranking quality

**Goal:** more often return the *best* valid bus, not merely a valid one.
**Effort:** 3–4 days. **Risk:** medium — this is the only phase whose outcome
is not already demonstrated.

### Levers, in order of expected value

| # | Lever | Rationale |
|---|---|---|
| 3.1 | Weight stop span more heavily in `route_rank_score` | 43% of answers are not the fewest-stop option; span is the strongest single quality signal |
| 3.2 | Add a frequency term (`log1p(trip_count)`) | A 2-stop-longer bus running 4× as often is genuinely better; currently under-weighted |
| 3.3 | Penalise routes whose span is far above the minimum for the pair | Directly targets the 10% that are >2 stops worse |
| 3.4 | Break ties by distance, then frequency | Removes arbitrary ordering among equals |
| 3.5 | Re-tune the direct-vs-transfer penalty using the new metric | Currently hand-set with no measurement behind it |

### Method (mandatory — this is what makes it engineering)

For each lever, in isolation:
1. Record `best_option_rate` and `mean_percentile_rank` before.
2. Apply the change.
3. Re-run the Phase 2 report on the **same** sample set and seed.
4. **Keep only if it improves; revert immediately if not.** No lever is kept on
   the argument that it "should" help.
5. Confirm lenient top-1 has not fallen below 0.95 — never trade correctness
   for ranking.

### Acceptance criteria

| # | Criterion | Threshold |
|---|---|---|
| 3.1 | `best_option_rate` | **≥ 0.70** (from 0.57) |
| 3.2 | `mean_percentile_rank` | **≤ 0.10** (from 0.14) |
| 3.3 | `within_2_stops_rate` | ≥ 0.92 (from 0.90) |
| 3.4 | Lenient top-1 not regressed | ≥ 0.95 |
| 3.5 | p90 search latency not regressed | ≤ 1.6 s |
| 3.6 | Every kept lever has a recorded before/after | documented |

> **Stretch, not committed:** `best_option_rate` ≥ 0.75. Do not promise this —
> it is the only number in the plan not already measured or trivially derived.

---

## Phase 4 — Real ground truth (optional, stretch)

**Goal:** replace synthetic samples with evidence of what riders actually
choose. **Effort:** ongoing. **Risk:** high — depends on data that does not
exist yet.

### Options, honestly ranked

1. **Hand-label 100 pairs** (1 day). Pick 100 real OD pairs, have a human name
   the bus they would take, and score against that. Small but *real*.
2. **Mine `usage_events`** (needs traffic). `predict_query` events already log
   route and stop names with no personal data. With enough usage, the
   distribution of repeat queries indicates which corridors matter.
3. **Click-through signal** (needs a UI change). Log which alternative the user
   selects — the closest thing to ground truth available without BMTC data.

### Acceptance criteria

| # | Criterion | Threshold |
|---|---|---|
| 4.1 | A human-labelled set of ≥100 pairs exists | file committed |
| 4.2 | Model scored against it, reported separately | present |
| 4.3 | Its limitations documented (labeller bias, size) | present |

> **State plainly if this phase is skipped.** A synthetic benchmark is a valid
> academic result *as long as it is described as one*.

---

## Phase 5 — Verification: prove the plan was executed

**Goal:** an automated, repeatable check that every acceptance criterion above
is met — so "done" is a test result, not an opinion.
**Effort:** ~1 day.

### 5.1 The verification script

Create `backend/scripts/verify_accuracy_plan.py`. It must:

1. Load `artifacts/metrics.json`.
2. Check every acceptance criterion from Phases 1–3 (and 4 if attempted).
3. Re-run a live evaluation on a fixed seed rather than trusting stored numbers.
4. Print a PASS/FAIL table.
5. **Exit non-zero if any criterion fails**, so CI can gate on it.

Required output shape:

```
DBARS ACCURACY PLAN — VERIFICATION
==================================================================
PHASE 1 — metric measures correctness
  [PASS] 1.1 relevance_set_metrics present in metrics.json
  [PASS] 1.2 lenient top-1 = 1.000  (threshold >= 0.95, n=60)
  [PASS] 1.3 all models scored on n=60
  [PASS] 1.4 exact_route_match retained (0.167)
  [PASS] 1.5 headline metric declared
  [PASS] 1.6 pytest: 161 passed

PHASE 2 — rank quality instrumented
  [PASS] 2.1 rank_quality block present
  [PASS] 2.2 baseline best_option_rate recorded (0.57)
  ...

PHASE 3 — ranking improved
  [PASS] 3.1 best_option_rate  0.72   (threshold >= 0.70, baseline 0.57)
  [FAIL] 3.2 mean_percentile_rank 0.11 (threshold <= 0.10, baseline 0.14)
  ...

==================================================================
RESULT: 17 passed, 1 failed  ->  EXIT 1
```

### 5.2 Regression guards (permanent, in the test suite)

Add `backend/tests/test_accuracy_metrics.py`:

| Test | Asserts |
|---|---|
| `test_relevance_set_is_not_single_label` | A pair with multiple valid buses yields a set of size > 1 |
| `test_lenient_scoring_accepts_any_valid_bus` | A known-valid alternative scores as a hit |
| `test_models_compared_on_equal_samples` | All models report the same `n` |
| `test_lenient_top1_above_threshold` | ≥ 0.95 on a fixed seed |
| `test_rank_quality_not_regressed` | `best_option_rate` ≥ the recorded baseline |
| `test_metrics_json_declares_headline_metric` | The headline field exists and names a real metric |

### 5.3 Documentation sign-off

| # | Criterion |
|---|---|
| 5.1 | `verify_accuracy_plan.py` exits 0 |
| 5.2 | Six regression tests added and passing (total 167) |
| 5.3 | CI runs the verifier on every push |
| 5.4 | `README.md` accuracy section updated with the honest number |
| 5.5 | Defense document §16 updated — headline is no longer "20% top-1" |
| 5.6 | Resume entry updated if accuracy is mentioned |

### 5.4 What "executed perfectly" means

The plan is complete when **all** of the following hold:

- `python scripts/verify_accuracy_plan.py` exits **0**
- `pytest tests` reports **167 passed**
- `metrics.json` headline metric is the relevance-set number, not the strict one
- Every Phase 3 lever kept has a documented before/after
- Every document quoting accuracy has been updated

If any Phase 3 threshold is missed, that is a **partial pass**, not a failure —
record the achieved number and say so. Phases 1, 2 and 5 are all-or-nothing
because they are deterministic.

---

## Summary

| Phase | What it does | Effort | Outcome |
|---|---|---|---|
| 0 | Diagnosis | done | Metric is broken; model is not |
| 1 | Relevance-set scoring | 1 day | Reported top-1: 0.20 → **~1.00** |
| 2 | Rank-quality metrics | 1 day | Baseline 57% / 0.14 recorded |
| 3 | Improve ranking | 3–4 days | Target 70% / 0.10 |
| 4 | Real ground truth | optional | 100 human-labelled pairs |
| 5 | Verification | 1 day | Automated PASS/FAIL gate |

**Total committed work: 6–7 days** (Phases 1, 2, 3, 5).

### The one-sentence version

> The route search already returns a correct bus in 60 of 60 test searches; the
> reported 20% is an artifact of a single-label metric applied to a problem with
> a median of 22 correct answers — so the work is to fix the measurement first,
> then improve *which* correct bus is ranked first, which is currently right 57%
> of the time.

### How to describe this in a viva

Do not say "I improved accuracy from 20% to 100%". Say:

> "The benchmark was single-label — it required naming the exact route the
> sample was drawn from, on pairs where a median of 22 buses are all correct.
> I measured a ceiling of 0.16 for a perfect system under that metric. I
> replaced it with relevance-set scoring, which showed the search returns a
> valid bus in 60 of 60 searches, and added a rank-quality metric that
> measures whether the *best* valid bus is ranked first — which was 57% and is
> the number I then worked to improve."

That answer demonstrates measurement design, which is worth considerably more
than a large number with no methodology behind it.
