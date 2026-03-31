# ADR-004: 12 Drift Dimensions (Not More, Not Fewer)

**Status:** Accepted

**Date:** 2025-01

**Context:**

Drift detection requires measuring multiple behavioral dimensions. Too few = blind to failure modes. Too many = overfitting and noise. How many dimensions should we track?

**Decision:**

Exactly **12 dimensions**:

1. decision_drift (tool sequence distribution)
2. tool_sequence (order-aware sequence)
3. latency (P95)
4. tool_distribution (usage patterns)
5. error_rate (failure count)
6. loop_depth (reasoning complexity)
7. verbosity_ratio (output/input tokens)
8. retry_rate (retry attempts)
9. output_length (response size)
10. time_to_first_tool (planning latency)
11. semantic_drift (outcome clustering)
12. tool_sequence_transitions (state machine changes)

**Rationale:**

**Why not fewer (e.g., 5 dimensions)?**

Missing critical failure modes:
- Without retry_rate → miss retry storms
- Without time_to_first_tool → miss planning latency regressions
- Without semantic_drift → miss outcome quality shifts

Example: Agent with low error_rate but high retry_rate (failing silently, retrying until success). 5-dimension system misses this.

**Why not more (e.g., 20 dimensions)?**

1. **Weight dilution** — With 20 dimensions, each gets ~5% weight. Individual dimensions become meaningless.

2. **Overfitting** — More dimensions = more noise. False positive rate increases.

3. **Correlation** — Many dimensions are correlated (e.g., latency ↔ retry_rate). Adding more correlated dimensions double-counts issues.

4. **Interpretability** — Developers can reason about 12 dimensions. 20+ is a black box.

**Coverage analysis:**

12 dimensions cover:
- **Decisions** (what): decision_drift, tool_sequence, tool_distribution
- **Performance** (speed): latency, time_to_first_tool
- **Reliability** (errors): error_rate, retry_rate
- **Reasoning** (logic): loop_depth, tool_sequence_transitions
- **Output** (content): output_length, verbosity_ratio
- **Outcomes** (quality): semantic_drift

**Consequences:**

- All `USE_CASE_WEIGHTS` tables have exactly 12 entries
- All weights must sum to 1.0 after calibration
- Adding a 13th dimension is a breaking change (requires migration)

**Alternatives Considered:**

1. **5 dimensions (minimal)** — decision_drift, latency, error_rate, output_length, semantic_drift
   - Rejected: Misses retry storms, planning latency, reasoning depth

2. **20 dimensions (maximal)** — Add: token_per_tool, tool_concurrency, memory_usage, cache_hit_rate, etc.
   - Rejected: Weight per dimension drops to 5%, overfitting, correlation issues

3. **Variable dimensions per use case** — e.g., FINANCIAL uses 8, CONTENT_GENERATION uses 6
   - Rejected: Makes blending impossible, complicates calibration

**Future evolution:**

If we add dimensions, do it carefully:
1. Validate they measure **orthogonal** signal (not correlated with existing)
2. Validate they improve detection on production data
3. Rebalance all USE_CASE_WEIGHTS tables
4. Write schema migration

**References:**

- Correlation analysis (baseline_calibrator.py:141-227) shows latency/retry_rate, loop_depth/error_rate are correlated
- More dimensions without correlation adjustment → double-counting
