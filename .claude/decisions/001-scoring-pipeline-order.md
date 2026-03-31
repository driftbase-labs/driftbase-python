# ADR-001: Scoring Pipeline Order

**Status:** Accepted

**Date:** 2025-01

**Context:**

The scoring pipeline has multiple stages: use case inference, blending, calibration, learned weights, power analysis, confidence tiers, drift computation, and verdict. The order of these stages is critical—wrong order leads to incorrect weights or meaningless thresholds.

**Decision:**

Pipeline order is fixed:

```
1. Use Case Inference (keyword + behavioral) → preset weights
2. Blending (resolve conflicts, proportional merge) → blended weights
3. Baseline Calibration (reliability, correlation) → calibrated weights
4. Learned Weights (blend with calibrated) → final weights
5. Power Analysis (compute min runs) → min_runs_needed
6. Confidence Tiers (TIER1/2/3 classification) → tier
7. Drift Computation (weighted composite) → drift_score
8. Verdict (threshold comparison) → SHIP/MONITOR/REVIEW/BLOCK
```

**Rationale:**

- **Inference first** — Must infer use case before applying preset weights
- **Blending second** — Must resolve conflicts before statistical adjustment
- **Calibration third** — Reliability multipliers require blended baseline
- **Learned fourth** — Must blend with calibrated (not preset) weights
- **Power fifth** — Requires calibrated baseline to compute variance
- **Tiers sixth** — Depends on power analysis result
- **Drift seventh** — Uses final weights from learned stage
- **Verdict last** — Depends on drift score and thresholds

**Consequences:**

- Bypassing any stage produces incorrect results
- Each stage assumes previous stages completed
- Testing must respect pipeline order (can't test verdict without drift)

**Alternatives Considered:**

1. **Power analysis before calibration** — Rejected because power analysis needs calibrated baseline variance
2. **Learned weights first** — Rejected because learned weights need statistical baseline to blend with
3. **Verdict before tiers** — Rejected because verdict should respect confidence tier (no verdict in TIER1/2)
