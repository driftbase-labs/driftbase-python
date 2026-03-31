# 011 — Isolation Forest as Supplementary, Not Primary, Signal

**Status:** Accepted
**Date:** 2026-03-30
**Files affected:** `local/anomaly_detector.py`, `local/diff.py`, `verdict.py`

---

## Decision

The isolation forest anomaly score is a supplementary signal — it can only
escalate a verdict (SHIP→MONITOR, MONITOR→REVIEW), never trigger BLOCK,
and only acts when its level is CRITICAL. The weighted composite drift score
remains the primary signal for all verdicts.

## Why isolation forest is supplementary, not primary

**1. Interpretability.**
The composite drift score has a clear per-dimension breakdown. A developer
who gets REVIEW can see "decision_drift: 0.39, latency: 0.34" and understand
why. The isolation forest anomaly score has no per-dimension explanation —
it only says "this behavioral vector is unlike the baseline."

A product that can't explain its verdicts destroys trust. The composite
score explains. The anomaly score detects — those are different jobs.

**2. Complementarity.**
The composite score misses correlated multi-dimensional shifts where no
single dimension crosses its threshold but the combination is abnormal.
The isolation forest catches exactly this case.

They complement each other. The composite score is the primary signal
with per-dimension accountability. The anomaly score is the secondary
signal that catches what the primary misses.

**3. CRITICAL-only escalation.**
HIGH and ELEVATED anomaly levels are advisory — they add information but
don't change the action the developer should take. Only CRITICAL (score
≥ 0.75) escalates the verdict, because at that level the multivariate
signal is strong enough to override a low composite score.

## Why CRITICAL can escalate SHIP→MONITOR and MONITOR→REVIEW but not REVIEW→BLOCK

Escalating to BLOCK requires high confidence in a severe regression. The
isolation forest alone — without per-dimension accountability — is not
sufficient evidence for a BLOCK verdict. BLOCK means "do not ship under
any circumstances." That requires the weighted composite score to earn it.

MONITOR and REVIEW are softer verdicts that say "look at this more closely."
An anomaly signal is sufficient evidence for these because they don't
block shipping — they prompt investigation.

## Why 90th percentile aggregation, not mean

The anomaly score aggregates eval run scores using the 90th percentile,
not the mean. A deployment where 90% of runs are fine but 10% are
completely off-baseline is still a real regression. The problematic runs
may correspond to a specific subset of inputs (edge cases, boundary queries)
that reveal a real behavioral change.

Mean aggregation would hide this. The 90th percentile ensures that a
cluster of anomalous runs is detected even if the majority of runs are
within the normal range.

## Why contributing dimensions are identified by distribution shift, not forest internals

Isolation forest doesn't natively identify which features drove the anomaly
score for a specific sample. Some implementations use SHAP values for this,
but SHAP is computationally expensive and adds a dependency.

Instead, contributing dimensions are identified by measuring which dimensions
shifted most in mean value between baseline and eval (normalized by baseline
std). This is:
- Interpretable: "latency shifted by 2.3σ" is understandable
- Fast: O(n * d) computation
- Honest: it tells the developer what actually changed, not what the forest
  internally weighted

The contributing dimensions are an explanation of what changed, not a
decomposition of the anomaly score itself. This distinction matters —
they are different quantities serving different purposes.

## Minimum data requirements

- 30 baseline runs: minimum to fit a meaningful isolation forest model
- 5 eval runs: minimum to produce a reliable 90th percentile estimate

Below these thresholds, `compute_anomaly_signal()` returns None silently.

## Alternative considered

**One-class SVM.**
More theoretically principled for outlier detection. Rejected because it
requires kernel selection and hyperparameter tuning (C, gamma) that we
cannot optimize without labeled anomaly data. Isolation forest has no
hyperparameters that require tuning for this use case (n_estimators=100,
contamination=0.05 are standard defaults).

**Local Outlier Factor (LOF).**
Good for density-based anomaly detection. Rejected because it is a
transductive method — it requires all data (baseline + eval) at inference
time and cannot produce scores for new runs without refitting. Isolation
forest is inductive — fit on baseline, score eval.

**Autoencoder.**
Would provide per-dimension reconstruction error as explanation.
Rejected because it requires deep learning infrastructure (PyTorch/TF)
which violates the constraint of not adding heavy dependencies.
