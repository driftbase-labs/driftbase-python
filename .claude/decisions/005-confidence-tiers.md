# ADR-005: Adaptive Confidence Tiers (TIER1/TIER2/TIER3)

**Status:** Accepted

**Date:** 2025-01

**Context:**

Drift scores are statistical estimates. With n=5 runs, scores are noise. With n=500 runs, scores are reliable. Should we show the same output regardless of sample size?

**Decision:**

Three **adaptive confidence tiers** based on statistical power:

- **TIER1** (n < 15): No scores, progress bars only
- **TIER2** (15 ≤ n < min_runs_needed): Directional signals (↑↓→), no verdict
- **TIER3** (n ≥ min_runs_needed): Full scores, verdict, confidence intervals

**min_runs_needed** is computed per-agent using power analysis (not fixed at 50).

**Rationale:**

**Why TIER1 shows nothing:**

Below 15 runs, even directional signals are unreliable. Showing "↑ latency" when it's random variance trains users to ignore signals.

**Why TIER2 shows directions not scores:**

Between 15-50 runs (typical), we can detect **large shifts** (>20%) but not small ones (<10%). Directional signals communicate this:
- ↑ = metric increased >10%
- ↓ = metric decreased >10%
- → = metric changed 5-10%
- (absent) = metric stable <5%

No verdict because we can't reliably classify severity (MONITOR vs REVIEW).

**Why TIER3 is adaptive:**

Different agents have different variance. Power analysis formula:
```
min_runs = 2 * ((z_alpha + z_beta) * sigma / delta)^2
```

- Low-variance agent (sigma=0.05) needs 30 runs
- High-variance agent (sigma=0.25) needs 120 runs

Fixed thresholds (30/50/100) would be wrong for both.

**Consequences:**

- Early users see "Not enough data" (TIER1)
- Medium users see directional hints (TIER2)
- Mature users see full analysis (TIER3)
- False positive rate is lower (conservative)

**Alternatives Considered:**

1. **Always show scores, add "low confidence" warning**
   - Rejected: Users ignore warnings, trust the number

2. **Fixed tiers (10/30/100)**
   - Rejected: Blind to agent variance (low-variance agents stuck in TIER2 unnecessarily)

3. **Single tier (show scores when n ≥ 50)**
   - Rejected: No feedback during ramp-up (frustrating UX)

4. **Probabilistic scores with error bars**
   - Rejected: Too technical, users misinterpret error bars

**Partial TIER3 override:**

If 8+ dimensions are "reliable" (per-dimension n ≥ min_runs) and overall n ≥ 80% of min_runs_needed, promote to TIER3.

Example: Agent with min_runs=50, current n=45, 10/12 dimensions reliable → TIER3 (most dimensions have sufficient data, only 2 are noisy).

**References:**

- Power analysis formula: `compute_min_runs_needed()` in baseline_calibrator.py:305
- Tier classification: `get_confidence_tier()` in diff.py:153
- Partial TIER3 logic: diff.py:489-495
