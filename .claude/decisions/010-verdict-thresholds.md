# 010 — Verdict Threshold Sigma Multipliers (2σ / 3σ / 4σ)

**Status:** Accepted
**Date:** 2026-03-30
**Files affected:** `local/baseline_calibrator.py`

---

## Decision

Statistical thresholds for MONITOR/REVIEW/BLOCK are derived from baseline
variance using sigma multipliers of 2, 3, and 4 respectively:

```
MONITOR = baseline_mean + 2σ  (t-distribution adjusted)
REVIEW  = baseline_mean + 3σ
BLOCK   = baseline_mean + 4σ
```

These multipliers come from statistical process control (SPC), specifically
Shewhart control charts used in manufacturing quality control since the 1920s.

## Why 2/3/4, not other values

**2σ for MONITOR:**
Under a normal distribution, 95.4% of observations fall within ±2σ of the
mean. A score above mean+2σ has only a 2.3% probability of occurring by
chance in a stable system. This is a sensitive threshold — it catches real
drift early while accepting ~2% false positive rate per dimension.

**3σ for REVIEW:**
99.7% of observations fall within ±3σ. A score above mean+3σ has only
0.13% probability of occurring by chance. This is the classic Western
Electric rule for "something has changed in this process." False positive
rate per dimension: ~0.13%.

**4σ for BLOCK:**
99.997% of observations fall within ±4σ. A score above mean+4σ has only
0.003% probability under the null hypothesis. This is reserved for the
most severe regressions — a genuine catastrophic change in behavior.

## Why these multipliers, not tighter or looser

**Tighter (e.g. 1.5σ / 2σ / 3σ):**
Would increase false positive rate significantly. At 1.5σ, ~7% of
observations in a stable system would trigger MONITOR. With 12 dimensions,
the probability of at least one false MONITOR trigger on any given diff
is very high. Developers would stop trusting the tool.

**Looser (e.g. 3σ / 4σ / 5σ):**
Would miss real regressions. The 5σ threshold corresponds to 1 in 3.5
million probability — appropriate for particle physics experiments, not
AI agent behavioral drift where the stakes are lower and real changes are
more frequent.

The 2/3/4 choice balances sensitivity (catching real regressions) against
specificity (not crying wolf). It is the consensus choice in quality control
literature for systems where:
- False positives are costly (wasted engineering time, erosion of trust)
- False negatives are also costly (shipping a broken agent)
- The system is non-deterministic with natural variance

AI agents fit this profile exactly.

## T-distribution adjustment for small samples

At n < 100, the normal distribution underestimates uncertainty — the
estimate of σ itself is noisy. We use `scipy.stats.t.ppf()` to derive
t-distribution multipliers at the same tail probabilities as the sigma
multipliers:

- 2σ → p = 0.9772 → t-multiplier at n=30: ≈ 2.045
- 3σ → p = 0.9987 → t-multiplier at n=30: ≈ 3.295
- 4σ → p = 0.99997 → t-multiplier at n=30: ≈ 4.878

At n=500+, t-distribution converges to normal and the difference is
negligible. The adjustment only matters — and is most protective — near
the minimum run threshold.

## Sensitivity parameter override

The `sensitivity` parameter scales all thresholds by a multiplier:
- `strict`:   0.75 (thresholds tighten — catches more, higher FP rate)
- `standard`: 1.00 (no change — default)
- `relaxed`:  1.35 (thresholds loosen — only flags clear regressions)

This is the one user-facing escape hatch. Financial/healthcare users
who know their use case demands tighter detection can use `strict`.
Creative agents with high natural variance can use `relaxed`.

## Alternative considered

**Fixed thresholds (e.g. MONITOR > 0.15, REVIEW > 0.28, BLOCK > 0.42).**
Used in early versions. Rejected because they are completely arbitrary and
context-blind — the same score means different things for a consistent
agent vs a noisy agent.

**Percentile-based thresholds (e.g. BLOCK when score > 99th percentile
of historical scores).**
Theoretically appealing. Rejected because it requires a long history of
drift scores across multiple version comparisons to estimate the percentile
accurately. Most agents don't have this history.
