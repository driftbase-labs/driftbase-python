# 009 — Bootstrap vs Parametric Confidence Intervals

**Status:** Accepted
**Date:** 2026-03-30
**Files affected:** `local/diff.py`, `local/baseline_calibrator.py`

---

## Decision

Bootstrap resampling (95% CI) is used for confidence intervals on the
composite drift score. Parametric confidence intervals (e.g. normal
approximation) are not used.

## Why bootstrap, not parametric CI

**1. Drift scores are not normally distributed.**
Parametric CI assumes the underlying statistic follows a known distribution
(usually normal). Composite drift scores are weighted sums of JSD values and
sigmoid-normalized deltas. Their distribution is complex, bounded to [0, 1],
and skewed — especially at small sample sizes. The normal approximation is
unreliable.

**2. No closed-form variance formula.**
The composite drift score is computed across 12 dimensions with adaptive
weights that depend on the data themselves (calibration uses baseline
variance). There is no simple analytical formula for the variance of this
statistic. Bootstrap makes no distributional assumption — it empirically
estimates the sampling distribution.

**3. Works well at small n.**
Parametric methods degrade at n < 30. Bootstrap is reliable down to n ≈ 20
with the right resampling count (we use 1000 bootstrap samples). Since agents
frequently operate near the minimum run threshold, bootstrap is safer.

**4. Consistent with JSD.**
Bootstrap CI for JSD is well-established in the information theory literature.
Using bootstrap for the composite score keeps the statistical methodology
consistent across all components.

## Bootstrap implementation

```python
n_bootstrap = 1000
bootstrap_scores = []

for _ in range(n_bootstrap):
    # Resample baseline and eval runs with replacement
    resampled_baseline = resample(baseline_runs)
    resampled_eval = resample(eval_runs)
    # Compute drift score on resampled data
    score = compute_drift_score(resampled_baseline, resampled_eval)
    bootstrap_scores.append(score)

ci_lower = np.percentile(bootstrap_scores, 2.5)
ci_upper = np.percentile(bootstrap_scores, 97.5)
```

The percentile method (not the BCa method) is used because it is simpler,
fast, and sufficient at our sample sizes. BCa correction would be more
accurate for very small n or heavily skewed distributions but adds
complexity with minimal practical benefit.

## What CI means in the output

```
Overall drift   0.28  [0.24–0.31, 95% CI]
```

This means: if we repeated the measurement many times by sampling different
runs from the same underlying behavioral distributions, 95% of the time the
true drift score would fall between 0.24 and 0.31.

A wide CI (e.g. [0.12–0.44]) means low confidence — the score is unstable
and more runs are needed. A narrow CI (e.g. [0.27–0.29]) means high
confidence — the score is stable and reliable.

## CI is informational, not used in verdict gating

The verdict (SHIP/MONITOR/REVIEW/BLOCK) is based on the point estimate
of the drift score, not the CI bounds. The CI is shown for transparency.

This is intentional. Using the upper CI bound for verdict gating would
increase false positives (triggering REVIEW when the true score is MONITOR).
Using the lower CI bound would increase false negatives. The point estimate
is the best single estimate of the true drift.

## Alternative considered

**Wilson score interval (for proportion-based dimensions).**
Appropriate for error_rate and escalation_rate specifically (they are
proportions). Rejected in favor of bootstrap for consistency — using
different CI methods for different dimensions would make the output
harder to interpret and maintain.

**Bayesian credible intervals.**
Theoretically more principled than frequentist CI. Rejected because it
requires specifying a prior over drift scores, which is arbitrary and
would need tuning per use case.
