# driftbase explain

The `driftbase explain` command provides detailed breakdowns of drift verdicts with statistical evidence.

## Usage

```bash
# Explain the most recent verdict
driftbase explain

# Explain a specific verdict by ID
driftbase explain <VERDICT_ID>
```

## What it Shows

### Header Section

Displays the comparison context and overall verdict:

```
┌─────────────────────────────────────────────┐
│  Drift Report: v1.2.3 → v1.3.0              │
│  Verdict: REVIEW                            │
│  Composite Score: 0.305 (CI: 0.252–0.358)  │
│  Severity: significant │ Confidence: TIER3  │
└─────────────────────────────────────────────┘
```

- **Verdict**: SHIP, MONITOR, REVIEW, or BLOCK
- **Composite Score**: Overall drift magnitude with 95% confidence interval
- **Severity**: none, low, moderate, significant, critical
- **Confidence**: TIER3 (full analysis), TIER2 (directional), or TIER1 (insufficient data)

### Top Contributors

Shows the 3 dimensions contributing most to the drift score:

```
Top Contributors
────────────────────────────────────────────────

decision_drift: 0.412 (CI: 0.331–0.493) ■ significant
  → Tool path ['search', 'write'] went from 3% to 27%
  Contribution: 43.2% │ MDE: 0.080

latency: 0.183 (CI: 0.120–0.246) ■ significant
  → P95 latency increased from 1,240ms to 2,890ms (+133%)
  Contribution: 31.5% │ MDE: 0.050

error_rate: 0.095 (CI: 0.042–0.148)
  → Error rate increased from 2.1% to 8.4% (+6.3pp)
  Contribution: 18.7% │ MDE: 0.030
```

For each contributor:
- **Observed drift**: Point estimate with confidence interval
- **■ significant**: Marker appears when CI excludes zero
- **Evidence**: Human-readable description of what changed
- **Contribution**: Percentage of total drift score attributed to this dimension
- **MDE**: Minimum Detectable Effect—smallest change reliably detectable with current sample sizes

### Minimum Detectable Effects (MDEs)

Full table showing detectability status for all dimensions:

```
Minimum Detectable Effects (MDEs)
────────────────────────────────────────────────

| Dimension                  | Observed | MDE   | Status         |
|----------------------------|----------|-------|----------------|
| decision_drift             | 0.412    | 0.080 | ✓ Detectable   |
| latency                    | 0.183    | 0.050 | ✓ Detectable   |
| error_rate                 | 0.095    | 0.030 | ✓ Detectable   |
| semantic_drift             | 0.042    | 0.065 | ⚠ Below MDE    |
| verbosity_ratio            | 0.018    | 0.045 | ⚠ Below MDE    |
```

- **✓ Detectable**: Observed drift exceeds MDE—reliable signal
- **⚠ Below MDE**: Observed < MDE—may be noise, collect more runs

## Reading the Evidence

Evidence strings explain what changed in plain English:

### Decision Drift
```
Tool path ['search', 'write'] went from 3.2% to 27.1% of runs
New tool path ['search', 'edit', 'write'] appeared in 15.3% of runs
Tool path ['read'] dropped from 18.4% to near 0%
```

### Latency
```
P95 latency increased from 1,240ms to 2,890ms (+133%)
Median latency increased from 450ms to 890ms; P95 from 1,240ms to 2,890ms
```

### Error Rate
```
Error rate increased from 2.1% to 8.4% (+6.3pp)
```

### Semantic Drift
```
Semantic cluster 'error' grew from 5% to 18% of outcomes
```

### Other Dimensions
- **Verbosity**: `Verbosity ratio increased from 1.2 to 1.8 (+50%)`
- **Loop depth**: `Average loop depth increased from 2.1 to 3.5 iterations (+67%)`
- **Output length**: `Average output length increased from 240 to 890 chars (+271%)`

## When to Use explain

- **After a REVIEW or BLOCK verdict**: Understand what triggered the warning
- **Post-deployment**: Verify the system adapted as expected
- **Debugging false positives**: Check if drift is meaningful or cosmetic
- **Root cause analysis**: Trace behavioral changes to specific code changes

## Workflow Integration

1. **Pre-deploy**: `driftbase diff v1.2.3 v1.3.0` → get verdict
2. **If REVIEW/BLOCK**: `driftbase explain` → see detailed breakdown
3. **Investigate**: Cross-reference evidence with code changes
4. **Decide**: Ship, rollback, or collect more data

## Verdict History

All diff results are automatically saved to the verdict history. Use:

```bash
# Show recent verdicts
driftbase history --days 7

# Explain a past verdict
driftbase explain <VERDICT_ID>
```

Verdict IDs are returned by `driftbase diff --format=json` in CI/CD pipelines.

## Statistical Interpretation

### Confidence Intervals (CIs)

CIs show the range where the true drift score likely falls (95% confidence):

- **Narrow CI**: High precision—result is reliable
- **Wide CI**: High uncertainty—collect more runs
- **CI excludes zero**: Statistically significant change

### Significance Markers

The **■ significant** marker appears when:
- The 95% CI does not include zero
- p < 0.05 in statistical tests

Absence of the marker doesn't mean "no drift"—it may mean:
- Sample size is too small (increase runs)
- Change is real but subtle (check MDE)
- High variance in baseline data (normal for some dimensions)

### MDEs (Minimum Detectable Effects)

MDE tells you the smallest change you can reliably detect:

- **Small MDE** (0.03–0.05): High statistical power
- **Medium MDE** (0.05–0.10): Adequate for most use cases
- **Large MDE** (>0.10): Underpowered—need more runs

If observed drift < MDE: Consider it noise unless consistent across multiple deploys.

## Tips

- **Focus on contribution %**: A dimension can be significant but contribute little to overall drift
- **Trust the evidence**: Generic fallback messages mean data is missing or malformed
- **Check MDEs**: If most dimensions show "Below MDE", you need more runs
- **CI width matters**: Wide CIs mean low confidence—results may change with more data
