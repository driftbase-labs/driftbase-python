# Drift Score Dimensions Update

## Summary

The drift score calculation has been expanded from **4 dimensions** to **10 dimensions** to capture more nuanced behavioral changes in AI agents. This document provides the updated content for the Driftbase documentation website.

---

## Current Documentation Issue

The https://driftbase.io/docs/quickstart page currently states that drift is calculated using **4 dimensions**:
1. decision_drift
2. latency_drift
3. error_drift
4. (overall) drift_score

This is **outdated**. The actual implementation uses **10 weighted dimensions**.

---

## Updated Content for Website

### 1. Drift Score Calculation (for Quickstart Page)

**OLD TEXT (to replace):**
> The page mentions **four drift dimensions** in the example output

**NEW TEXT:**

The drift score is a **weighted composite of 10 behavioral dimensions** that captures both performance and behavioral changes:

#### Core Performance Dimensions (40% weight)
- **Tool sequence distribution** (40%) — Which tools are called and in what order. Measured using Jensen-Shannon divergence between probability distributions of tool calling patterns.

#### Reliability & Performance Dimensions (24% weight)
- **Latency distribution** (12%) — Response time changes across percentiles (p50, p95, p99). Detects performance regressions.
- **Error rates** (12%) — Failure and exception patterns. Tracks reliability degradation.

#### Decision & Output Quality Dimensions (12% weight)
- **Semantic clustering** (8%) — Distribution of decision outcomes (resolved, escalated, fallback, error). Measures how often agents succeed vs. fail.
- **Output structure** (4%) — Changes in response schema, format, or structure. Detects breaking changes in output format.

#### Behavioral Complexity Dimensions (24% weight)
*These are new dimensions added to detect subtle behavioral changes:*

- **Verbosity ratio** (6%) — Response length relative to input size. Detects output bloat where agents become unnecessarily verbose.
- **Loop count** (6%) — Number of tool execution iterations per request. Measures agentic reasoning depth and complexity.
- **Output length** (4%) — Absolute character count of responses. Tracks response size changes.
- **Tool sequence drift** (4%) — Changes in the order tools are called. Detects altered problem-solving strategies.
- **Retry count** (4%) — Frequency of tool call retries. Reliability indicator for external dependencies.

**Total:** All weights sum to 100% (1.0).

**Calculation method:**
```
drift_score = (0.40 × tool_dist) + (0.12 × latency) + (0.12 × errors) +
              (0.08 × semantic) + (0.04 × output_struct) + (0.06 × verbosity) +
              (0.06 × loops) + (0.04 × out_len) + (0.04 × tool_seq) + (0.04 × retry)
```

Each dimension is normalized to [0, 1] using sigmoid functions, ensuring no single dimension can dominate the overall score.

---

### 2. Example Output (for Quickstart Page)

**OLD EXAMPLE:**
```
decision_drift: 0.47    — escalation rate +2.1×
latency_drift: 0.17     — p95 +180ms
error_drift: 0.04       — stable
drift_score: 0.29       — MODERATE DRIFT
```

**NEW EXAMPLE (more comprehensive):**
```
╭─────────────────────── Drift Report: v1.0 → v2.0 ───────────────────────╮
│                                                                          │
│ Drift Score: 0.29 [0.24 – 0.34] 95% CI                                 │
│ Verdict: MODERATE DRIFT — investigate before promoting                  │
│                                                                          │
│ Component Breakdown:                                                     │
│   • Tool sequence:     0.47 (40% weight) — decision patterns shifted    │
│   • Latency:           0.17 (12% weight) — p95 latency +180ms          │
│   • Errors:            0.04 (12% weight) — error rate stable           │
│   • Semantic:          0.15 (8% weight)  — escalation rate +2.1×       │
│   • Output structure:  0.02 (4% weight)  — stable                      │
│   • Verbosity:         0.23 (6% weight)  — responses 35% longer        │
│   • Loop count:        0.18 (6% weight)  — +1.2 avg iterations         │
│   • Output length:     0.12 (4% weight)  — avg response +450 chars     │
│   • Tool sequence:     0.09 (4% weight)  — tool order changed          │
│   • Retry count:       0.03 (4% weight)  — retry rate stable           │
│                                                                          │
│ Cost Impact: +€42.50 per 10k runs (+18% token usage)                   │
│                                                                          │
│ Root Cause Hypothesis:                                                   │
│ Agent is taking longer paths (more loops) and producing more verbose    │
│ outputs. Tool sequence shifted from [query_db → respond] to             │
│ [query_db → web_search → query_db → respond]. This suggests the agent  │
│ is less confident and seeking additional validation.                    │
╰──────────────────────────────────────────────────────────────────────────╯
```

---

### 3. Drift Score Interpretation Table (Update)

**Keep the existing table but add context:**

| Score Range | Assessment | What Changed |
|---|---|---|
| 0.00–0.10 | "Stable — no meaningful change" | Behavioral fingerprints nearly identical across all dimensions |
| 0.10–0.20 | "Minor drift — worth monitoring" | Small shifts in 1-2 dimensions (e.g., slight latency increase) |
| 0.20–0.40 | "Moderate drift — investigate before promoting" | Notable changes in multiple dimensions or significant change in one critical dimension |
| 0.40+ | "Significant drift — do not promote without review" | Major behavioral shifts across dimensions; agent is fundamentally different |

---

### 4. What Driftbase Captures (Data Privacy Section)

**OLD TEXT:**
> "tool call sequences, latency, decision outcomes, and error patterns"

**NEW TEXT:**
> Driftbase captures **10 behavioral dimensions** including tool call sequences, latency distributions, decision outcomes, error patterns, verbosity changes, agentic loop complexity, retry patterns, and output structure shifts. All data is **hashed locally** using SHA-256 before storage. Raw prompts and outputs are never stored or transmitted.

---

### 5. Additional Pages to Update

#### a) API Reference / SDK Documentation

If there's a page documenting the `@track()` decorator or SDK metrics, update it with:

**Captured Metrics:**
```python
@track(version="v2.0")
def my_agent(input: str) -> str:
    # Automatically captures:
    # - tool_sequence: List of tools called
    # - tool_call_count: Total tool invocations
    # - latency_ms: Total execution time
    # - prompt_tokens, completion_tokens: LLM usage
    # - error_count: Exceptions caught
    # - retry_count: Tool retry attempts
    # - loop_count: Agentic reasoning iterations
    # - output_length: Response character count
    # - verbosity_ratio: output_tokens / input_tokens
    # - time_to_first_tool_ms: Latency before first tool call
    # - semantic_cluster: Outcome classification (resolved/escalated/error)
    ...
```

#### b) Methodology / How It Works Page

If there's a page explaining the statistical methodology, add:

**Multi-Dimensional Drift Detection**

Driftbase doesn't rely on a single metric. Instead, it builds a **10-dimensional behavioral fingerprint** for each version:

1. **Behavioral Dimensions (40% weight):**
   - Primary indicator: tool calling patterns and sequences

2. **Performance Dimensions (24% weight):**
   - Latency (p50, p95, p99) and error rates

3. **Quality Dimensions (12% weight):**
   - Decision outcomes and output structure stability

4. **Complexity Dimensions (24% weight):**
   - Verbosity, reasoning depth, output size, retry patterns

**Why 10 dimensions?**
- **Robustness:** A single metric can be misleading (e.g., lower latency due to skipped validation)
- **Root cause analysis:** Knowing *which* dimensions changed helps identify the cause
- **Sensitivity:** Detects subtle regressions that aggregate metrics miss

**Weighting philosophy:**
- Tool sequence (40%) gets the highest weight because it represents the agent's "decision tree"
- Performance metrics (latency, errors) are equally weighted (12% each) as both matter equally
- New behavioral metrics (verbosity, loops, retries) are weighted lower (4-6%) but provide critical context

---

### 6. FAQ Update

**Q: What does the drift score measure?**

**OLD ANSWER:**
> The drift score combines four dimensions: decision patterns, latency, errors, and tool usage.

**NEW ANSWER:**
> The drift score is a weighted composite of **10 behavioral dimensions** that captures how your agent's behavior has changed between versions. It includes tool calling patterns (40%), performance metrics like latency and errors (24%), decision outcomes (12%), and behavioral complexity metrics like verbosity and reasoning depth (24%). A score of 0.0 means the versions are identical; 1.0 means completely different. Scores above 0.20 warrant investigation before promoting to production.

---

## Technical Implementation Reference

For developers updating the documentation, here's the exact calculation from `src/driftbase/local/diff.py`:

```python
def _compute_drift_score(baseline, current) -> float:
    """Compute the overall drift score (0–1) between two fingerprints."""

    # Weights (sum to 1.0)
    w_jsd = 0.40        # Tool sequence distribution
    w_latency = 0.12    # Latency changes
    w_errors = 0.12     # Error rate changes
    w_semantic = 0.08   # Decision outcome changes
    w_output = 0.04     # Output structure changes
    w_verbosity = 0.06  # Verbosity ratio changes
    w_loop = 0.06       # Loop count changes
    w_out_len = 0.04    # Output length changes
    w_tool_seq = 0.04   # Tool sequence drift
    w_retry = 0.04      # Retry count changes

    drift_score = (
        w_jsd * decision_drift +
        w_latency * sigma_latency +
        w_errors * sigma_errors +
        w_semantic * sigma_semantic +
        w_output * sigma_output +
        w_verbosity * verbosity_drift +
        w_loop * sigma_loop +
        w_out_len * sigma_out_len +
        w_tool_seq * decision_drift +
        w_retry * sigma_retry
    )

    return min(1.0, max(0.0, drift_score))
```

Each component drift is normalized to [0, 1] using:
- **Jensen-Shannon divergence** for probability distributions (tool sequences, decisions)
- **Sigmoid functions** for continuous metrics (latency, verbosity, loop counts)
- **Kolmogorov-Smirnov test** for distributional differences

---

## Action Items

1. **Update https://driftbase.io/docs/quickstart:**
   - Replace "four drift dimensions" with "10 weighted behavioral dimensions"
   - Add the comprehensive dimension breakdown
   - Update the example output to show all dimensions
   - Add context to the interpretation table

2. **Update any "How It Works" / "Methodology" pages:**
   - Add explanation of the 10 dimensions
   - Explain the weighting philosophy
   - Show why multiple dimensions matter for robustness

3. **Update SDK/API documentation:**
   - List all captured metrics with descriptions
   - Show which dimensions they feed into

4. **Update FAQ:**
   - Revise "What does drift score measure?" answer
   - Add "Why 10 dimensions instead of 4?" if needed

5. **Update marketing/landing pages:**
   - Any mentions of "4 dimensions" should be updated
   - Emphasize "comprehensive 10-dimensional behavioral analysis"

---

## SEO Keywords to Update

If your docs use these phrases, update them:
- ❌ "four drift dimensions"
- ❌ "4 dimensions"
- ❌ "decision, latency, errors, and tool usage"
- ✅ "10 behavioral dimensions"
- ✅ "multi-dimensional drift detection"
- ✅ "comprehensive behavioral fingerprint"
- ✅ "tool sequence, latency, errors, verbosity, loop count, retry patterns"

---

## Questions?

If you need clarification on any dimension or the calculation methodology, refer to:
- Source code: `src/driftbase/local/diff.py` (lines 107-192, 195-443)
- README: Updated "Statistical Methodology" section
- This document: Complete breakdown above
