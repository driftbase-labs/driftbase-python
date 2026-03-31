# 013 — Behavioral Inference Classifier Design

**Status:** Accepted
**Date:** 2026-03-30
**Files affected:** `local/use_case_inference.py`

---

## Decision

Use case inference uses two independent classifiers in parallel — a keyword
classifier (tool names) and a behavioral classifier (observed metrics) —
whose results are blended proportionally by confidence. When the two
classifiers disagree on incompatible use cases, the higher-confidence
classifier wins and blends with GENERAL only (conflict resolution).

## Why two classifiers instead of one

**Keyword classifier alone:**
Fails when tool names are generic (`run_tool`, `call_api`, `process_data`).
Many real-world agents use generic naming conventions. The keyword classifier
returns GENERAL with 0.0 confidence for these agents, producing equal weights
that are meaningless.

**Behavioral classifier alone:**
Fails for new agents (fewer than 5 runs — insufficient behavioral signal)
and for well-behaved uniform agents (consistent behavior that doesn't trigger
distinctive rule patterns).

**Both together:**
The two classifiers are independent sources of evidence. When both agree,
confidence is high. When one fails (generic names, insufficient runs),
the other can still provide signal. The failure modes are largely complementary.

## Why confidence-weighted blending, not voting

Voting (take the majority) would require at least 3 classifiers to break
ties and gives no mechanism to express strength of evidence.

Confidence-weighted blending allows continuous expression of evidence strength.
A keyword classifier with confidence 0.81 has more say than one with 0.23.
A behavioral classifier with insufficient data (confidence 0.0) contributes
nothing without blocking the keyword signal.

The blending formula:
```python
gen_conf = max(0.0, 1.0 - kw_conf - beh_conf)
final_weights[dim] = (
    kw_conf  * kw_weights[dim]
    + beh_conf * beh_weights[dim]
    + gen_conf * GENERAL_weights[dim]
)
```

GENERAL weights act as a prior — they fill the gap when neither classifier
is confident.

## Why conflict detection is necessary

Without conflict detection, blending FINANCIAL weights (kw_conf=0.4) with
CODE_GENERATION weights (beh_conf=0.4) produces a weight table that doesn't
represent any real agent type. Financial agents weight decision_drift heavily;
code generation agents weight error_rate and loop_depth heavily. Averaging
them produces something that's wrong for both.

The COMPATIBLE_USE_CASE_PAIRS matrix defines which combinations make sense
to blend (AUTOMATION + DEVOPS_SRE, RESEARCH_RAG + DATA_ANALYSIS) vs which
are inherently contradictory (FINANCIAL + CODE_GENERATION).

On conflict: take the higher-confidence classifier's weights, blend with
GENERAL for the remainder, apply a small confidence penalty (×0.8) to
signal reduced certainty.

## Why GENERAL weights are not equal distribution

Equal weights (0.091 × 11 dimensions) treat decision_drift the same as
verbosity_ratio. This is wrong — decision outcomes are meaningful regression
signals for virtually any agent type, while verbosity is only meaningful
in specific use cases (content generation, RAG).

The GENERAL weights reflect empirical priority across all agent types:
decision_drift=0.22, error_rate=0.18, tool_sequence=0.16, latency=0.12.
These are opinionated but defensible — documented rather than arbitrary.

## Why behavioral rules are conservative

The BEHAVIORAL_RULES thresholds (e.g. escalation_rate > 0.10 for
CUSTOMER_SUPPORT) are set conservatively to avoid false positive use case
inference. An incorrectly inferred use case propagates through the entire
scoring pipeline — wrong preset weights → wrong calibration starting point
→ wrong verdicts.

False positive use case inference is more damaging than falling back to
GENERAL. GENERAL with good behavioral calibration is better than FINANCIAL
with wrong preset weights.

## Minimum 5 runs for behavioral inference

Below 5 runs, the behavioral signals (escalation_rate, avg_tool_count, etc.)
are estimated from too few samples to be reliable. A single unusual run
could dominate the estimates and produce misleading inference.

The keyword classifier has no minimum — it fires from run 0 because tool
names are metadata, not statistical estimates.

## Alternative considered

**Single classifier with feature fusion (tool names + behavioral metrics).**
Would require training a combined model. Rejected because it needs labeled
training data (use case labels per agent), which doesn't exist. The
rule-based approach requires no training data and is interpretable.

**Hierarchical classification (keyword first, behavioral as fallback).**
Simpler than blending. Rejected because it would discard behavioral signal
when keyword confidence is moderate — wasting available information.
Blending uses both signals proportionally regardless of which is stronger.
