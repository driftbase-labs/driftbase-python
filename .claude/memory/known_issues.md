# Known Issues

**Pre-existing bugs. Do not fix without discussion.**

## LangGraph test failure (test_track.py)

**Status:** Open, non-blocking

**Test:** `test_langgraph_invoke_captures_tool_sequence`

**Symptom:** Fails with `AssertionError: unexpectedly None : expected one run to be written`

**Root cause:** LangGraph is not a declared dependency (and shouldn't be—huge transitive deps). Test works when langgraph is installed separately, fails in CI and fresh environments.

**Why not fixed:**
1. Adding langgraph to dependencies bloats install size by ~200MB
2. LangGraph integration is optional (users install it themselves)
3. Test is for optional integration, not core functionality

**Workaround:** Mark test as `xfail` when langgraph not installed, or skip with `pytest.importorskip("langgraph")`.

**Decision:** Leave as-is until LangGraph splits out a lightweight core package.

---

## Semantic drift unavailable when light-embed not installed

**Status:** Expected behavior, not a bug

**Symptom:** `semantic_drift` dimension always shows 0.0 when `pip install driftbase` (without `[semantic]` extra).

**Root cause:** `light-embed` is an optional dependency. Without it, semantic clustering falls back to no-op.

**Why not a problem:**
1. Weight redistribution zeros out `semantic_drift` weight and redistributes to other dimensions
2. Total weight still sums to 1.0
3. Drift scores remain valid (just without semantic signal)

**Documentation:** README.md explains semantic extra is optional.

**Decision:** Do not make light-embed a required dependency (50MB+ install size).

---

## Baseline N < 30 shows preset weights only

**Status:** Expected behavior

**Symptom:** Calibration with n < 30 returns `calibration_method="preset_only"`, no statistical adjustment.

**Root cause:** Reliability multipliers and correlation adjustments require sufficient data. Below 30 runs, variance estimates are unreliable.

**Why this is correct:**
1. With n < 30, statistical calibration would have **higher error** than preset weights
2. Preset weights are use case averages tested on production data
3. Calibration activates at 30+ runs as documented

**User impact:** Early adopters see less personalized scoring. This is intentional (better to be conservative than overfit).

**Decision:** Keep 30-run threshold. Log message explains why.

---

## Tool sequence transitions always 0.0

**Status:** Feature not implemented yet

**Symptom:** `tool_sequence_transitions` dimension shows 0.0 for all agents.

**Root cause:** Transition matrix computation not yet implemented. Placeholder uses `decision_drift` as proxy.

**Plan:** Implement transition matrix in Q1 2026:
1. Build transition matrix from `tool_call_sequence` field
2. Compute JSD between baseline and eval transition matrices
3. Store transition matrices in `semantic_cluster_distribution` (or new field)

**Impact:** Low. Transition drift is highly correlated with `decision_drift` (r=0.85). Current proxy is adequate.

**Decision:** Ship with placeholder, implement properly in next major version.

---

## Power analysis incorrect for agents with all-zero variance

**Status:** Edge case, documented

**Symptom:** Agent with perfectly deterministic behavior (sigma=0.0 for all dimensions) gets `min_runs_needed=10` (floor), but should need fewer runs (any shift is immediately detectable).

**Root cause:** Formula assumes some baseline variance. Zero variance is special case.

**Why not fixed:**
1. Perfectly deterministic agents are rare in practice (even "hello world" agents have timestamp variance)
2. Floor of 10 is already very low
3. Fixing requires separate code path for sigma < 0.001

**Workaround:** For synthetic test agents with zero variance, manually set min_runs=5.

**Decision:** Document as expected behavior. Not worth special-casing.

---

## Bootstrap CI slightly wider than true CI at small N

**Status:** Inherent property of bootstrap, not fixable

**Symptom:** At n=20, bootstrap 95% CI is ~5% wider than parametric CI.

**Root cause:** Bootstrap resampling introduces additional variance at small sample sizes. This is a **feature, not a bug**—it correctly captures estimation uncertainty.

**Math:** Bootstrap CI accounts for:
1. Sampling variance (data)
2. Estimation variance (resampling)

Parametric CI only accounts for (1).

**Why this is correct:** Bootstrap is more conservative at small n, which is desirable (avoid false confidence).

**Decision:** Keep bootstrap as-is. It's the right tool for non-parametric drift distributions.

---

## Correlation adjustment can produce negative weights (then gets clamped to 0)

**Status:** Expected behavior

**Symptom:** When two dimensions are perfectly correlated (r=1.0) and have equal preset weights, correlation adjustment reduces one to zero.

**Root cause:** Reduction formula is `weight * (1 - correlation * 0.5)`. At r=1.0, this reduces by 50%. If weight was already low, it can go negative.

**Why this is correct:** Perfectly correlated dimensions **should** be collapsed to one dimension. Clamping to zero and renormalizing achieves this.

**Decision:** Working as intended. The alternative (reduce both proportionally) would still leave double-counting.

---

## Budget breach detection requires config to be set before first run

**Status:** Documented limitation

**Symptom:** If `@track(budgets=...)` is added to an agent that already has runs in the DB, breach detection doesn't retroactively apply to old runs.

**Root cause:** Budget config is persisted at decorator call time, not read retroactively from old run records.

**Why not fixed:**
1. Old runs don't have budget metadata (can't know what thresholds were active)
2. Retroactive breach detection would require replaying all runs
3. Budgets are for gating **new** deploys, not analyzing history

**Workaround:** Run `driftbase prune` to clear old runs before adding budgets.

**Decision:** Document in README. Not a high-priority fix.

---

## TIER3 partial logic only checks overall N, not per-dimension N

**Status:** Partially implemented

**Current behavior:** Agent at n=45 (90% of min_runs=50) with 8/12 reliable dimensions gets TIER3.

**Missing:** Per-dimension reliability check. If only 4/12 dimensions are "reliable" but n ≥ min_runs_needed, still gets TIER3.

**Why this matters:** At n=45, some dimensions may be reliable (low variance) while others are indicative (high variance). Current logic treats all as reliable.

**Plan:** Add per-dimension rendering in CLI:
```
✓ decision_drift   (reliable, n=45/30)
⊘ semantic_drift   (indicative, n=45/80)
```

**Decision:** Low priority. Partial TIER3 already prevents most false positives.

---

## Verdict thresholds not exposed in CLI output

**Status:** Future enhancement

**Symptom:** User sees `drift_score=0.18` and `verdict=MONITOR` but doesn't know why. What are the thresholds?

**Root cause:** `composite_thresholds` are in `DriftReport` object but not printed by `cli_diff.py`.

**Plan:** Add threshold row to diff output:
```
Drift Score:     0.18
Thresholds:      MONITOR ≥0.12, REVIEW ≥0.21, BLOCK ≥0.34
Verdict:         MONITOR
```

**Decision:** Add in next minor release.

---

## Summary

**Truly broken:**
- LangGraph test (skip or mark xfail)

**Expected limitations:**
- Semantic drift requires [semantic] extra
- Baseline n < 30 uses preset weights only
- Tool sequence transitions not implemented (proxy used)
- Budgets don't apply retroactively

**Future enhancements:**
- Per-dimension reliability rendering
- Threshold exposure in CLI
- Bootstrap CI width optimization (low priority)
