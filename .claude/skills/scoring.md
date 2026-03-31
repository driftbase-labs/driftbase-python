# Scoring Pipeline Skill

**Read this skill before touching any scoring, calibration, or inference code.**

## The Intelligence Pipeline (Order Matters)

```
Tool Names + Runs
    ↓
1. Use Case Inference (keyword + behavioral)
    ↓
2. Blending (resolve conflicts, proportional merge)
    ↓
3. Baseline Calibration (reliability multipliers, correlation adjustment)
    ↓
4. Learned Weights (blend with calibrated if available)
    ↓
5. Power Analysis (compute min runs needed per dimension)
    ↓
6. Confidence Tiers (TIER1/2/3 based on sample size + power)
    ↓
7. Drift Computation (weighted composite of 12 dimensions)
    ↓
8. Verdict (SHIP/MONITOR/REVIEW/BLOCK from thresholds)
```

**Never bypass this pipeline. Never hardcode weights or thresholds.**

## Core Modules

- `use_case_inference.py` — keyword + behavioral classifiers → preset weights
- `baseline_calibrator.py` — statistical calibration → reliability-adjusted weights
- `diff.py` — drift computation using calibrated weights
- `verdict.py` — DriftReport → exit codes

## Sacred Invariants

### 1. Weights Always Sum to 1.0

Every weight dict at every pipeline stage must sum to exactly 1.0 (within 0.01 tolerance).

After any weight transformation:
```python
total = sum(weights.values())
assert abs(total - 1.0) < 0.01, f"Weights sum to {total}"
weights = {k: v / total for k, v in weights.items()}  # Renormalize
```

### 2. Never Hardcode Weights

❌ **Wrong:**
```python
drift_score = 0.4 * decision_drift + 0.2 * latency_drift + ...
```

✅ **Right:**
```python
calibration = calibrate(baseline_version, eval_version, use_case)
w_decision = calibration.calibrated_weights["decision_drift"]
drift_score = w_decision * decision_drift + ...
```

All weights flow through `calibrate()`. No exceptions.

### 3. Never Hardcode Thresholds

❌ **Wrong:**
```python
if drift_score > 0.30:
    verdict = "REVIEW"
```

✅ **Right:**
```python
if drift_score > calibration.composite_thresholds["REVIEW"]:
    verdict = "REVIEW"
```

Thresholds are statistically derived from baseline variance + use case + sensitivity + volume multipliers.

### 4. Never Raise from Scoring Code

All scoring functions must degrade gracefully on error:

```python
def infer_use_case(tool_names: list[str]) -> dict:
    try:
        # ... classification logic
        return result
    except Exception as e:
        logger.debug(f"Use case inference failed: {e}")
        return {"use_case": "GENERAL", "confidence": 0.0, ...}
```

Return safe fallback, never raise. False positives destroy trust.

## The 12 Drift Dimensions

1. **decision_drift** — JSD of tool sequence distribution (what the agent does)
2. **tool_sequence** — JSD of tool call sequence (order matters)
3. **latency** — P95 latency delta, sigmoid-normalized
4. **tool_distribution** — Tool usage patterns (currently uses decision_drift)
5. **error_rate** — Absolute error count delta
6. **loop_depth** — P95 loop count delta
7. **verbosity_ratio** — Output tokens / input tokens delta
8. **retry_rate** — Avg retry count delta
9. **output_length** — Avg output length delta
10. **time_to_first_tool** — Planning latency before first tool call
11. **semantic_drift** — JSD of semantic cluster distribution (outcomes)
12. **tool_sequence_transitions** — Transition matrix divergence (future)

Dimensions 11-12 are **conditional** (may be unavailable). Use `_redistribute_weights()` to zero them out and redistribute proportionally if missing.

## Use Case Inference

Two classifiers run in parallel:

### Keyword Classifier (`infer_use_case`)
- Decomposes tool names into component words
- Matches against 14 use case keyword tables
- High-signal keywords score 2.0, medium score 1.0
- Returns use case + confidence + matched keywords

### Behavioral Classifier (`infer_use_case_from_behavior`)
- Extracts behavioral signals from runs (escalation_rate, latency_p95, loop_depth, etc.)
- Evaluates rule tables for each use case
- Requires ≥5 runs, returns GENERAL otherwise
- Returns use case + confidence + behavioral_signals

### Blending (`blend_inferences`)
- If both agree: increase confidence (floor to 0.5)
- If incompatible: winner takes all, blend with GENERAL
- If compatible: proportional blend by confidence
- Returns blended_weights that sum to 1.0

**Never call `USE_CASE_WEIGHTS` directly. Always use blended weights from `blend_inferences()`.**

## Baseline Calibration

`calibrate()` takes blended weights and adjusts them statistically:

1. **Reliability multipliers** — Reduce weight of noisy dimensions (high CV)
2. **Correlation adjustment** — Reduce weight of correlated dimensions to avoid double-counting
3. **Redistribution** — Zero out unavailable dimensions (semantic_drift, tool_sequence_transitions)
4. **Learned weights** — Blend with learned weights from labeled outcomes if available
5. **Threshold derivation** — Per-dimension thresholds using t-distribution for small samples
6. **Volume multipliers** — Tighten thresholds for higher run counts
7. **Sensitivity multipliers** — Apply strict/standard/relaxed scaling

Returns `CalibrationResult` with `calibrated_weights`, `thresholds`, and `composite_thresholds`.

## Power Analysis

`compute_min_runs_needed()` uses two-sample test formula:

```
n = 2 * ((z_alpha/2 + z_beta) * sigma / delta)^2
```

Where:
- `sigma` = per-dimension standard deviation from baseline
- `delta` = effect_size (use case-specific, 0.05-0.15)
- `alpha` = false positive rate (0.05)
- `power` = detection probability (0.80)

Returns `overall` (max across dimensions), `per_dimension`, and `limiting_dimension`.

**Floor: 30 overall, 10 per-dimension. Cap: 200.**

## Confidence Tiers

Sample size determines reliability level:

- **TIER1** (n < 15): No scores, progress bars only
- **TIER2** (15 ≤ n < min_runs_needed): Directional signals (↑/↓/→), no verdict
- **TIER3** (n ≥ min_runs_needed): Full scores, verdict, CI

Special case: **Partial TIER3** if 8+ dimensions are "reliable" and n ≥ 80% of min_runs_needed.

Per-dimension significance:
- **reliable**: n ≥ min_runs for this dimension
- **indicative**: 15 ≤ n < min_runs
- **insufficient**: n < 15

## Drift Computation

`compute_drift()` orchestrates the full pipeline:

1. Extract tool names from runs
2. Run keyword + behavioral inference
3. Blend inferences
4. Calibrate weights + thresholds
5. Compute power analysis (cache + 20% recompute logic)
6. Determine confidence tier
7. If TIER1: return minimal report
8. If TIER2: compute indicative_signal, return directional report
9. If TIER3: compute full drift score + verdict + CI

Drift score is a **weighted sum** of 12 dimension scores:

```python
drift_score = sum(calibrated_weights[dim] * dimension_score[dim] for dim in DIMENSION_KEYS)
```

Clamped to [0, 1]. If `decision_drift > 0.30`, floor at 0.15 (major behavioral shift).

## Bootstrap Confidence Intervals

If `baseline_runs` and `current_runs` provided:
- Resample with replacement (500 iterations)
- Cap at 200 runs per side for performance
- Compute drift score per bootstrap sample
- Return 95% CI (2.5th, 97.5th percentiles)

## False Positive Rate Priority

**This is the most important product constraint.**

A drift score that moves on cosmetic changes is worthless. When in doubt:

- Be **conservative** with weights (lower is safer)
- Be **conservative** with thresholds (higher is safer)
- Err on the side of "no signal" over "false alarm"

The scoring system exists to catch **real regressions**, not to flag every minor variation.

## Common Mistakes

1. **Bypassing calibration** — Never compute drift_score without calling `calibrate()` first
2. **Modifying weights mid-pipeline** — All weight transforms must renormalize to 1.0
3. **Skipping redistribution** — Always check `semantic_available` and `transitions_available`
4. **Hardcoding min_runs** — Use power analysis result, not a fixed number
5. **Ignoring confidence tiers** — Return appropriate report type for sample size

## Adding a New Dimension

If you need to add a 13th dimension:

1. Add to `DIMENSION_KEYS` in `baseline_calibrator.py`
2. Add to all `USE_CASE_WEIGHTS` tables in `use_case_inference.py` (ensure all sum to 1.0)
3. Add extraction logic in `_extract_dimension_scores()`
4. Add computation logic in `compute_drift()`
5. Add to `AgentRunLocal` schema if new raw metric needed
6. Write migration in `sqlite.py:_migrate_schema()`
7. Update tests to validate weight sum invariant

**Never add a dimension without a migration plan.**

## Debugging Scoring Issues

If drift scores are unstable or surprising:

1. Check weight sums: `sum(calibrated_weights.values())` should be ~1.0
2. Check use case inference: `blend_result["use_case"]` and confidence
3. Check calibration: `calibration.calibration_method` (preset_only vs statistical vs learned)
4. Check sample sizes: `baseline_n`, `eval_n`, tier
5. Check power analysis: `min_runs_needed`, `limiting_dimension`
6. Check dimension significance: `dimension_significance` dict

All of this is in the `DriftReport` object. Print it.

## Summary

- Weights always sum to 1.0
- Never hardcode weights or thresholds
- Never raise from scoring code
- Flow: inference → blending → calibration → learned → power → tier → drift → verdict
- False positive rate is everything — be conservative
