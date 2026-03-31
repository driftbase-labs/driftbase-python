# 008 — JSD vs KL Divergence for Distribution Comparison

**Status:** Accepted
**Date:** 2026-03-30
**Files affected:** `local/diff.py`

---

## Decision

Jensen-Shannon Divergence (JSD) is used for all distribution-based drift
dimensions (decision_drift, tool_distribution, semantic_drift,
tool_sequence_transitions). KL divergence is not used.

## Why JSD, not KL divergence

**1. Symmetry.**
KL divergence is asymmetric: KL(P||Q) ≠ KL(Q||P). The direction matters —
comparing baseline→eval gives a different number than eval→baseline.
For drift detection, there is no "correct" direction. v1.0 vs v2.0 should
give the same score as v2.0 vs v1.0. JSD is symmetric by definition.

**2. Bounded output.**
KL divergence is unbounded — it can be infinite when Q has zero probability
mass where P has non-zero mass. This happens naturally in behavioral data:
v2.0 might call a tool that v1.0 never called, giving that tool zero
probability in the baseline distribution.

JSD is bounded to [0, 1] (or [0, log(2)] depending on the base). This
makes it directly usable as a drift score component without normalization.

**3. Zero probability handling.**
KL divergence is undefined when any probability is exactly zero. This
requires smoothing — adding a small epsilon to all probabilities — which
introduces an arbitrary parameter and changes the score based on the
smoothing value chosen.

JSD handles zero probabilities gracefully because it uses the mixture
distribution (P+Q)/2, which is always non-zero where either P or Q is
non-zero.

**4. Interpretability.**
JSD = 0 means identical distributions. JSD = 1 means maximally different.
The score has a clear meaning. KL divergence has no natural upper bound,
making "how much drift is too much" harder to reason about.

## What JSD measures

For two distributions P (baseline) and Q (eval):

```
M = (P + Q) / 2
JSD(P||Q) = 0.5 * KL(P||M) + 0.5 * KL(Q||M)
```

This measures the average information gain from knowing which distribution
a sample came from, relative to the mixture. It is the square of the
JS distance, which is a true metric.

## When JSD is NOT used

Value-based dimensions (latency, error_rate, retry_rate, loop_depth,
verbosity_ratio, output_length, time_to_first_tool) use sigmoid-normalized
deltas rather than JSD, because these dimensions produce scalar values
(means, percentiles) not probability distributions.

The sigmoid normalization maps any delta to [0, 1]:
```python
sigmoid_drift = 1 / (1 + exp(-k * (delta - threshold)))
```

Where k controls sensitivity and threshold is the calibrated baseline.

## Alternative considered

**Wasserstein distance (Earth Mover's Distance).**
More theoretically sound for comparing distributions — it accounts for
the geometry of the output space. Rejected because it requires solving
an optimal transport problem, which is computationally expensive for
the run counts we work with (30-500 runs). JSD is O(n) and fast.

**Kolmogorov-Smirnov test statistic.**
Used in some observability tools. Rejected because it only measures the
maximum difference between CDFs (sensitive to the tails) and ignores
the overall shape of the distribution. JSD uses all probability mass.
KS is kept as a supplementary statistical test but not as the primary
drift score component.

**Chi-squared statistic.**
Rejects the null hypothesis of identical distributions. Rejected because
it is a hypothesis test, not a distance metric — it gives a p-value, not
a score that can be compared across different pairs of versions.
