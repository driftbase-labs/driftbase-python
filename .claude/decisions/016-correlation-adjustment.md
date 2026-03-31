# 016 — Dimension Correlation Adjustment

**Status:** Accepted
**Date:** 2026-03-30
**Files affected:** `local/baseline_calibrator.py`

---

## Decision

After applying reliability multipliers, dimension weights are adjusted to
reduce double-counting from correlated dimensions. When two dimensions have
Spearman correlation > 0.70, the less important dimension (lower weight)
has its weight reduced by up to 50%.

## Why correlation adjustment is necessary

Some drift dimensions measure overlapping aspects of agent behavior:
- Latency and retry_rate: timeouts cause retries → both go up together
- Loop depth and error_rate: loops often end in errors → correlated
- Loop depth and retry_rate: retry loops increase depth → correlated
- Output_length and verbosity_ratio: longer output → higher ratio

When these dimensions are both weighted, a single underlying event (e.g.
a new retry loop pattern) inflates the composite score through multiple
channels. This artificially inflates drift scores and increases false
positive rate.

Correlation adjustment suppresses the redundant signal without eliminating
it entirely.

## Why Spearman correlation, not Pearson

Drift scores are bounded to [0, 1] and skewed — not normally distributed.
Pearson correlation assumes bivariate normality. Spearman ranks the values
before correlating, making it robust to the actual distribution shape and
to outliers in individual runs.

## Why 0.70 as the threshold

Below 0.70, correlation is considered moderate — the dimensions are
measuring related but meaningfully different things. A reduction would
suppress genuine independent signal.

Above 0.70, correlation is strong enough that the two dimensions are
largely measuring the same underlying event. Reduction is warranted.

0.70 is the standard threshold in social science and psychometrics for
"strong correlation requiring attention." It is not arbitrary — it is
the conventional cutoff below which shared variance (r²=0.49) is
considered insufficient to warrant action.

## Why maximum 50% reduction

Never fully zeroing a dimension due to correlation is critical for two
reasons:

1. **Correlation can decouple during regressions.** A model update might
   cause latency to spike without affecting retry_rate. If retry_rate was
   zeroed, this signal would be lost exactly when it's most informative —
   when latency and retry_rate are no longer moving together.

2. **The correlation estimate is noisy at small n.** At 30-50 baseline
   runs, correlation estimates have high variance. A true correlation of
   0.65 might be measured as 0.75, triggering a reduction that isn't
   warranted. The 50% cap limits the damage from noisy estimates.

## Why only positive correlations are adjusted

Negative correlations (dimensions moving in opposite directions) are not
double-counting. If latency goes up and output_length goes down, these are
independent regression signals pointing at different problems. Adjusting
for negative correlation would suppress genuinely independent signals.

## Why the less important dimension is reduced, not averaged

The more important dimension (higher weight) was assigned that weight because
the use case inference determined it matters more for this agent type. A
FINANCIAL agent's decision_drift weight of 0.28 reflects a deliberate judgment
that decision outcomes are critical.

Reducing the more important dimension to split the difference would override
the use case judgment. Reducing the less important dimension preserves the
judgment while eliminating the redundancy.

## Minimum data requirement

30 baseline runs required before correlation adjustment activates. Below
this, correlations cannot be estimated reliably and the function returns
all 1.0 adjustment factors (no adjustment).

## Alternative considered

**Principal component analysis to remove correlated dimensions.**
PCA would produce orthogonal components with no correlation. Rejected because
PCA components are linear combinations of dimensions that have no intuitive
interpretation. A developer cannot understand "PC2 spiked" the way they
understand "latency spiked."

**Variance inflation factor (VIF) from regression.**
Standard approach for multicollinearity in regression. Rejected because it
requires choosing a response variable — there is no single response variable
in the drift score computation. VIF is appropriate for regression, not for
unsupervised distance computation.
