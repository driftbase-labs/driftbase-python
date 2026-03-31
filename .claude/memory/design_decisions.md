# Design Decisions

**Why things are the way they are.**

## Why weights always sum to exactly 1.0

The drift score is a **weighted average**, not a weighted sum. If weights summed to 0.8, drift scores would be systematically low. If they summed to 1.2, systematically high.

```python
drift_score = sum(weight[dim] * dimension_score[dim] for dim in dimensions)
```

To keep drift_score in [0, 1] range, weights must sum to 1.0 exactly.

**Consequence:** Every weight transformation (reliability multipliers, correlation adjustment, redistribution) must renormalize.

**Alternative considered:** Use weighted sum with arbitrary total, then normalize final score. Rejected because it makes per-dimension thresholds meaningless.

---

## Why verdicts only show at TIER3

Showing SHIP/MONITOR/REVIEW/BLOCK at n=12 implies false precision. The statistical machinery (JSD, bootstrap CI, t-distribution thresholds) is **not reliable** below 30-50 runs depending on variance.

**Decision:** No verdict below the power-analysis-derived minimum.
- TIER1 (n < 15): Progress bars only
- TIER2 (15 ≤ n < min_runs): Directional signals (↑↓→)
- TIER3 (n ≥ min_runs): Full verdict

**Alternative considered:** Show verdict always, add "low confidence" warning. Rejected because users ignore warnings and trust the verdict.

---

## Why rollback suggestion requires BLOCK or REVIEW

A rollback suggestion at MONITOR sends the wrong signal. MONITOR means "watch but probably fine." Rollback implies urgency.

**Decision:** Rollback only suggested when:
1. Verdict is BLOCK or REVIEW
2. A stable prior version exists with 30+ runs
3. Drift score > 0.25

**Alternative considered:** Always suggest rollback if prior version available. Rejected because it trains users to ignore suggestions.

---

## Why watch/tail/status/push were removed from free SDK

These are **monitoring features**. The free SDK is pre-production analysis only. Monitoring = Pro tier.

Keeping monitoring commands in the free CLI creates positioning confusion and sets wrong user expectations ("why can't I watch my production agent?").

**Decision:** Cut monitoring commands entirely from free SDK.
- Removed: watch, tail, status, push, plugin, bookmark, explore
- Kept: diff, diagnose, compare, demo, inspect, chart, cost

**Alternative considered:** Keep commands but show "Pro only" error. Rejected because it's user-hostile (teaser features).

---

## Why sensitivity is strict/standard/relaxed not risk=high/medium/low

`risk` requires explanation. "high risk of what?" `sensitivity` is self-explanatory:
- **strict** = catch small shifts (0.75× thresholds)
- **standard** = balanced (1.0× thresholds)
- **relaxed** = catch large shifts only (1.35× thresholds)

A developer knows immediately what strict vs relaxed means.

**Alternative considered:** `tolerance=low/medium/high`. Rejected because "tolerance" is ambiguous (tolerance for what?).

---

## Why no async in SDK storage

SQLite is **synchronous only** via SQLModel/SQLAlchemy. Wrapping synchronous calls in `asyncio.to_thread()` adds complexity for zero benefit—the bottleneck is disk I/O, not Python overhead.

**Decision:** All storage is synchronous. No async/await in `backends/` or `local/`.

**Where async might be useful later:** HTTP push to Pro tier (in `sdk/push.py` only). Keep async contained to that one module.

**Alternative considered:** Use `aiosqlite`. Rejected because it's incompatible with SQLModel and requires rewriting all queries.

---

## Why SQLite only (no Postgres) in free SDK

The free SDK is **local-first**. Runs are stored on the developer's laptop, diffs run locally, no cloud required.

Postgres requires:
1. Running a database server
2. Network configuration
3. Connection string management
4. Schema migrations across versions

This destroys the "pip install, add decorator, it just works" experience.

**Decision:** SQLite only in `driftbase` package. Pro tier can have Postgres (separate codebase).

**Alternative considered:** Abstract backend supports both. Rejected because it leaks Postgres complexity into free tier (connection pooling, retries, transactions).

---

## Why [analyze] extra was collapsed into base dependencies

Original split:
- `pip install driftbase` → tracking only
- `pip install driftbase[analyze]` → numpy/scipy/rich for diffs

**Problem:** Every developer using the free SDK runs diffs on their laptop. They **all** need numpy/scipy/rich. The split created friction for zero benefit.

**Decision:** Collapse `[analyze]` into base dependencies. Keep `[semantic]` optional (light-embed is 50MB+).

**Result:**
```toml
dependencies = ["numpy", "scipy", "rich", ...]
[project.optional-dependencies]
semantic = ["light-embed>=1.0.0"]
```

---

## Why 12 dimensions (not more, not fewer)

**Too few dimensions** (e.g., 5) → blind to specific failure modes (e.g., retry storms, planning latency spikes).

**Too many dimensions** (e.g., 20) → overfitting, weight dilution (each dimension gets 5% weight), impossible to interpret.

**Decision:** 12 dimensions covering:
- **Decisions** (what the agent does): decision_drift, tool_sequence, tool_distribution
- **Performance** (how fast): latency, time_to_first_tool
- **Reliability** (how often it breaks): error_rate, retry_rate
- **Reasoning** (how it thinks): loop_depth, tool_sequence_transitions
- **Output** (what it produces): output_length, verbosity_ratio
- **Outcomes** (semantic results): semantic_drift

**Alternative considered:** 20 dimensions including token-level metrics. Rejected because weight per dimension drops to 5%, making individual dimensions meaningless.

---

## Why power analysis uses t-distribution not normal

For small samples (n < 100), the sample standard deviation **underestimates** the true population standard deviation. Using normal distribution produces thresholds that are **too tight**, leading to false positives.

**Decision:** Use t-distribution with n-1 degrees of freedom. For n=30, this widens thresholds by ~7%. For n=100, converges to normal.

**Formula:**
```python
t_multiplier = t_dist.ppf(probability, df=n-1)
threshold = mean + t_multiplier * std
```

**Alternative considered:** Always use normal. Rejected after seeing false positive rate spike at n < 50 in test data.

---

## Why confidence tiers are 15/min_runs not 10/30/100

**TIER1 floor (15 runs):** Below this, even directional signals are noise. 10 runs is too few to distinguish real trend from variance.

**TIER2/TIER3 split (min_runs from power analysis):** Different agents need different n. A low-variance agent (sigma=0.05) needs 30 runs. A high-variance agent (sigma=0.25) needs 120 runs. Fixed thresholds (30/50/100) would be wrong for both.

**Decision:** Adaptive split based on per-agent power analysis.

**Alternative considered:** Fixed tiers (10/30/100). Rejected because it's blind to agent variance.

---

## Why calibration uses reliability multipliers not just preset weights

Preset weights are **use case averages** (e.g., FINANCIAL agents weight decision_drift at 0.30). But individual agents vary:
- Some agents have noisy latency (high CV) → reduce latency weight
- Some agents have stable error rates (low CV) → increase error_rate weight

**Decision:** Multiply preset weights by reliability multipliers derived from baseline variance.

**Formula:**
```python
reliability = 1.0 / (1.0 + cv)  # cv = std / mean
calibrated_weight = preset_weight * reliability
# Then renormalize to sum=1.0
```

**Alternative considered:** Use preset weights as-is. Rejected after seeing agents with 1 noisy dimension dominate the score.

---

## Why correlation adjustment reduces less important dimension

When two dimensions are correlated (e.g., latency ↔ retry_rate), they measure the **same underlying issue**. Giving both full weight double-counts the problem.

**Decision:** For each correlated pair, reduce weight of the **less important** dimension by `correlation * 0.5` (max 50% reduction). More important dimension keeps full weight.

**Example:** latency (weight=0.12) and retry_rate (weight=0.04) are 0.8 correlated.
- Reduce retry_rate by 0.8 * 0.5 = 0.4 (40% reduction)
- Keep latency at full weight
- Renormalize both to sum=1.0

**Alternative considered:** Reduce both proportionally. Rejected because it punishes the important dimension.

---

## Why learned weights blend with calibrated (not replace)

Learned weights are trained on **deploy outcomes** (good/bad labels). They're powerful when n ≥ 10 labeled deploys, but noisy when n < 10.

**Decision:** Blend learned weights with calibrated weights using a `learned_factor`:
```python
final_weight = learned_factor * learned_weight + (1 - learned_factor) * calibrated_weight
```

`learned_factor` increases with n (0.3 at n=10, 0.7 at n=50).

**Alternative considered:** Switch fully to learned weights at n=10. Rejected because it causes discontinuities in drift scores.

---

## Why drift score has a floor of 0.15 when decision_drift > 0.30

If tool sequence distribution changes by >30%, that's a **major behavioral shift** even if other metrics look fine. The agent is doing fundamentally different things.

**Decision:** `if decision_drift > 0.30: drift_score = max(drift_score, 0.15)`

This ensures large behavioral shifts always trigger at least MONITOR verdict.

**Alternative considered:** No floor, let weighted sum determine score. Rejected after seeing agents with 40% decision drift but drift_score=0.08 (because other dimensions were stable).

---

## Summary

Most important decisions:
1. **Weights sum to 1.0** → drift score stays in [0, 1]
2. **Adaptive tiers from power analysis** → no false precision at low n
3. **Reliability multipliers** → per-agent calibration
4. **t-distribution thresholds** → correct for small samples
5. **Correlation adjustment** → avoid double-counting
6. **No async in storage** → simplicity over theoretical performance
7. **SQLite only** → local-first, zero config
