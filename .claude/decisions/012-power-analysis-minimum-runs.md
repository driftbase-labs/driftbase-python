# 012 — Power Analysis for Minimum Run Thresholds

**Status:** Accepted
**Date:** 2026-03-30
**Files affected:** `local/baseline_calibrator.py`, `local/diff.py`

---

## Decision

The minimum number of runs required for a statistically reliable verdict is
derived from the agent's own baseline variance and use case risk profile via
statistical power analysis, not a fixed global threshold.

The formula:
```python
n = 2 * ((z_alpha + z_beta) * sigma / effect_size) ** 2

# Where:
# z_alpha = scipy.stats.norm.ppf(0.975) = 1.96  (two-tailed, alpha=0.05)
# z_beta  = scipy.stats.norm.ppf(0.80)  = 0.84  (power=0.80)
# sigma   = per-dimension std from baseline runs
# effect_size = minimum drift worth detecting (varies by use case)
```

Overall minimum = max(per-dimension minimums), clamped to [30, 200].

## Why agent-specific minimum, not fixed threshold

A fixed threshold of 50 runs is wrong for two reasons:

**Too strict for consistent agents.**
An agent with near-zero natural variance in its key dimensions can produce
a reliable drift signal at 25-30 runs. Forcing it to wait for 50 runs
delays a genuine signal and frustrates the developer.

**Too loose for noisy agents.**
An agent with high natural variance (sigma=0.25) needs 97+ runs before a
drift score is statistically reliable at GENERAL effect size (0.10).
Showing a verdict at 50 runs would be presenting false precision.

The power analysis formula derives the correct threshold for each agent
from its own data.

## Why effect_size is use-case specific

The effect size (minimum shift worth detecting) varies by the stakes of
the use case:

- FINANCIAL/HEALTHCARE: 0.05 — detect 5% shifts, high stakes
- CUSTOMER_SUPPORT/CODE_GENERATION: 0.10 — standard detection
- CONTENT_GENERATION/RESEARCH_RAG: 0.15 — only large shifts matter

A smaller effect size (FINANCIAL) means you want to detect smaller changes,
which requires more samples. A larger effect size (CONTENT_GENERATION) means
you only care about substantial changes, requiring fewer samples.

This makes the minimum run threshold risk-aware: high-stakes agents
automatically require more runs before their verdict is trusted.

## Why the formula uses absolute effect size, not relative (sigma fraction)

The formula uses:
```python
delta = effect_size  # absolute shift in drift score units (0.0–1.0)
```

NOT:
```python
delta = effect_size * sigma  # WRONG for drift scores
```

Drift scores are normalized 0–1. The effect_size (e.g. 0.05 for FINANCIAL)
means "detect a 0.05 absolute shift in the drift score" — a shift from
0.10 to 0.15. It does not mean "detect a 5% of the standard deviation
shift."

Using `delta = effect_size * sigma` would make the minimum n proportional
to (sigma / (effect_size * sigma))² = 1/effect_size², which is independent
of sigma — wrong. The correct formula makes n proportional to
(sigma / effect_size)², scaling correctly with both variance and stakes.

## Differentiation only appears for high-variance agents

With typical drift score standard deviations:
- sigma=0.02 (consistent): n ≈ 1 → clamped to floor 30
- sigma=0.10 (moderate):   n ≈ 16 → clamped to floor 30
- sigma=0.25 (noisy):      n ≈ 97 → 97 (above floor)

Differentiation only kicks in for truly high-variance agents. This is
correct and honest — consistent agents are fine at 30 runs.

## Floor of 30, not 15

The calibration system (reliability multipliers, t-distribution thresholds)
requires a minimum of 30 baseline runs to produce reliable estimates. Showing
a full verdict before calibration has activated would mean the scoring system
is using uncalibrated weights.

The power analysis floor is set to match the calibration minimum: 30.

Per-dimension floor is 10 — individual dimensions can reach significance
before the composite score is reliable.

## Cap of 200

Beyond 200 runs per version, the marginal benefit of additional samples
is minimal and the required wait time becomes impractical. At n=200, the
bootstrap CI is narrow enough that additional samples don't meaningfully
change the confidence interval.

## Persistence in SQLite

Significance thresholds are cached in the `significance_thresholds` table.
Cache is invalidated when baseline run count grows by >20%. This prevents
re-running power analysis on every diff while ensuring the threshold
updates as more baseline data is collected.

## Alternative considered

**Fixed global threshold of 50.**
Simple but wrong — treats a consistent financial agent the same as a
noisy content generation agent. Rejected.

**User-specified minimum.**
Rejected — violates the zero-configuration principle. Users should not
need to understand power analysis to use Driftbase.

**Bayesian sample size determination.**
More theoretically correct. Rejected because it requires specifying a
prior over effect sizes, which is arbitrary and would need tuning.
Frequentist power analysis is well-understood and produces defensible
results without priors.
