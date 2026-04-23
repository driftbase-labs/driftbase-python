# EMD Latency Distribution Detection

## Overview

Earth Mover's Distance (EMD), also known as Wasserstein distance, catches **distribution shape changes** that percentile-based metrics miss. Instead of comparing p95 latency alone, EMD compares the **full latency distribution**.

## Problem Statement

p95-based latency drift can miss important behavioral changes when:
- Half the runs get slower (bimodal distribution forms)
- Latency variance increases without p95 changing much
- Distribution shape changes (long tail develops)

**Example:**
- Baseline: all runs ~1000ms (tight distribution)
- Current: half runs ~1000ms, half ~2000ms (bimodal)
- p95 result: current p95 might be ~1900ms (only ~90% increase)
- EMD result: detects the full distribution shift (~1000ms EMD, high signal)

## How It Works

### Earth Mover's Distance

EMD measures the "cost" of transforming one distribution into another:
- Imagine distributions as piles of dirt
- EMD = minimum work to move one pile to match the other
- Units: same as the underlying metric (milliseconds for latency)

### Normalization to [0, 1]

Raw EMD is in milliseconds (unbounded). We normalize using sigmoid:
```
signal = 1 / (1 + exp(-k * (emd - c)))
```

Parameters (calibrated for typical latency ranges 100-5000ms):
- `k = 0.002` (steepness)
- `c = 500` (inflection point)

Result:
- EMD 500ms → ~0.37 signal
- EMD 1000ms → ~0.73 signal
- EMD 2000ms → ~0.95 signal

### Blending with p95

**Option B (chosen for Phase 5):** Blend 50/50 with existing sigmoid
```python
sigma_latency_p95 = sigmoid(latency_delta_p95)
emd_signal = compute_latency_emd_signal(baseline_runs, current_runs)
sigma_latency = 0.5 * sigma_latency_p95 + 0.5 * emd_signal
```

Why blend instead of replace?
- Preserves existing sensitivity to p95 shifts
- Adds new sensitivity to distribution shape changes
- Smooth transition (no regression on existing scenarios)

## Implementation

### Module: `src/driftbase/stats/emd.py`

Functions:
- `compute_latency_emd(baseline, current) -> float` - raw EMD in ms
- `compute_latency_emd_signal(baseline, current) -> float` - normalized signal [0, 1]

Uses `scipy.stats.wasserstein_distance` (existing dependency).

### Integration: `src/driftbase/local/diff.py`

```python
# Latency drift: blend p95 delta sigmoid with EMD distribution signal (50/50)
sigma_latency_p95 = _sigmoid_contribution(latency_delta_raw, k=2.0, c=1.0)
emd_signal = 0.0
if baseline_runs is not None and current_runs is not None:
    emd_signal = compute_latency_emd_signal(baseline_runs, current_runs)
sigma_latency = 0.5 * sigma_latency_p95 + 0.5 * emd_signal
```

No fingerprint field needed - computed directly from run-level latency_ms values.

## Detection Scenarios

### When EMD Catches What p95 Misses

**Scenario 1: Bimodal shift**
- Baseline: all runs 1000ms ± 100ms
- Current: 50% at 1000ms, 50% at 2000ms
- p95: baseline ~1150ms, current ~1950ms (69% increase)
- EMD: ~500ms distance (50% of runs moved 1000ms)
- **Better**: EMD gives clearer signal of the bimodal split

**Scenario 2: Increased variance**
- Baseline: tight distribution (1000ms ± 50ms)
- Current: same median but wider spread (1000ms ± 300ms)
- p95: both ~1150ms vs ~1400ms (22% increase)
- EMD: detects the shape change even if p95 is similar

**Scenario 3: Long tail develops**
- Baseline: normal distribution ~1000ms
- Current: 90% at ~1000ms, 10% timeout at 5000ms
- p95: ~1000ms → ~1100ms (small shift)
- EMD: captures the tail outliers

## Calibration Notes

Sigmoid parameters `k=0.002, c=500` chosen for typical web service latencies:
- Below 500ms EMD: low signal (noise)
- 500-1000ms EMD: moderate signal (investigate)
- Above 1000ms EMD: high signal (likely meaningful shift)

Adjust if your latency range differs:
- Real-time systems (target <100ms): use `c=100`
- Batch jobs (target >10s): use `c=5000`

## Testing

Fixture: `bimodal_latency_drift_pair(n=200, seed=11)`
- Baseline: all runs ~1000ms
- Current: 50% at ~1000ms, 50% at ~2000ms
- Expected: `emd > 200`, `signal > 0.3`

Tests in `tests/test_signal_gains.py`:
- `test_compute_latency_emd_identical()` - EMD ~0 for identical
- `test_compute_latency_emd_shifted()` - EMD >900 for 1000ms shift
- `test_compute_latency_emd_signal()` - signal normalization
- `test_emd_detects_bimodal_shift()` - integration test
- `test_bimodal_latency_detected_by_emd()` - end-to-end

## Alternative Integration Options

Not chosen for Phase 5, but documented for future consideration:

**Option A: Replace**
```python
sigma_latency = emd_signal  # Drop p95 entirely
```
Pros: Simpler, pure distribution comparison
Cons: Loses existing sensitivity calibration

**Option C: New Dimension**
```python
# Add latency_distribution_drift as 13th dimension
drift_score = (... + w_latency_dist * emd_signal)
```
Pros: Both signals available independently
Cons: More dimensions to calibrate, higher complexity

## See Also

- [12-Dimension Rationale](.claude/decisions/015-12-dimensions-rationale.md) - Why 12 dimensions
- [CLAUDE.md](../CLAUDE.md) - Scoring system architecture
