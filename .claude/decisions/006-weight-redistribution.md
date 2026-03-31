# 006 — Weight Redistribution for Unavailable Dimensions

**Status:** Accepted
**Date:** 2026-03-30
**Files affected:** `local/baseline_calibrator.py`, `local/use_case_inference.py`

---

## Decision

When a conditional dimension (`semantic_drift`, `tool_sequence_transitions`)
is unavailable, its weight is redistributed proportionally to all remaining
dimensions. The unavailable dimension's weight becomes 0.0 and all other
weights are scaled up so the total still sums to 1.0.

## Why proportional redistribution, not zeroing

Zeroing the weight without redistribution would cause weights to sum to less
than 1.0, making the composite drift score systematically lower than intended.
A score of 0.85 with 11 active dimensions is not comparable to a score of 0.85
with 12 active dimensions — the scale has shifted.

Proportional redistribution preserves the relative importance of all remaining
dimensions while keeping the composite score on the same 0.0–1.0 scale.

## Why not concentrate redistributed weight into the most important dimension

Concentrating the semantic_drift weight (e.g. 0.08 in FINANCIAL) entirely into
decision_drift would artificially inflate decision_drift's influence beyond what
was designed. The preset weight tables were calibrated as a system — the balance
between dimensions is intentional.

Proportional scaling preserves that balance. If semantic_drift had weight 0.08
and decision_drift had 0.30 of the remaining 0.92, after redistribution
decision_drift becomes 0.30 * (1.0 / 0.92) ≈ 0.326 — a small, proportional
increase rather than a large arbitrary jump.

## Which dimensions are conditional

**semantic_drift** — requires `[semantic]` extra (light-embed) to be installed
AND embedding data to exist for both versions being compared. If either version
has empty `semantic_cluster_distribution = {}`, semantic_available = False.

**tool_sequence_transitions** — requires transition matrix data in SQLite for
both versions. If either version has no tool call sequences recorded, this
dimension is unavailable.

## Implementation location

`baseline_calibrator.py` → `_redistribute_weights()` function.
Called after preset weights are loaded and before reliability multipliers
are applied.

## Alternative considered

**Skip redistribution, just use the remaining weights as-is.**
Rejected because weights would not sum to 1.0, making scores incomparable
across agents with different available dimensions.

**Use a fixed fallback weight table without conditional dimensions.**
Rejected because it would require maintaining a separate weight table per
use case for every combination of available dimensions — exponential complexity.

## False positive implication

Redistribution slightly increases the weight of all remaining dimensions.
For high-variance dimensions (latency, retry_rate), this marginally increases
false positive risk. Acceptable because the effect is small and proportional,
and the alternative (broken composite scores) is worse.
