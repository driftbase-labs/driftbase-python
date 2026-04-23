# Task Clustering for Per-Task Drift Analysis

## Overview

Task clustering groups runs by **task type** to detect drift in specific workflows. Instead of treating all runs as homogeneous, it identifies sub-populations and computes drift scores per cluster.

## Problem Statement

Global drift scores can miss important behavioral changes when:
- One task type regresses while others improve (cancels out in aggregate)
- Different task types have different drift sensitivities
- You want to identify which workflow changed, not just that something changed

**Example:**
- Baseline: search tasks (100ms), write tasks (500ms) both stable
- Current: search tasks (100ms) still fast, write tasks (2000ms) regressed
- Global p95: baseline ~500ms, current ~1800ms (260% increase)
- Per-cluster: search cluster 0% drift, write cluster 300% drift
- **Better**: Clustering pinpoints which task type regressed

## How It Works

### Clustering Key

Group runs by `(first_tool, input_length_bucket)`:
- **first_tool**: First tool in `tool_sequence` (workflow entry point)
- **input_length_bucket**: Binned `raw_prompt` length
  - `0-100` chars (short)
  - `100-500` chars (medium)
  - `500-2000` chars (long)
  - `2000+` chars (very long)

Example cluster IDs:
- `search:0-100` - short search queries
- `write:500-2000` - long-form writing tasks

### Cluster Selection

- Max 5 clusters by default (keeps top N by size)
- Requires >= 10 runs per cluster per version for analysis
- Only analyzes clusters present in both baseline and current

### Drift Computation Per Cluster

Simplified 3-dimension scoring:
1. **Latency drift** (p95): `abs(current_p95 - baseline_p95) / baseline_p95`
2. **Error rate drift**: `abs(current_error_rate - baseline_error_rate) * 2.0`
3. **Tool sequence variance**: unique sequences / total runs (detects logic fragmentation)

Weighted composite:
```
drift_score = 0.4 * latency + 0.4 * error + 0.2 * variance
```

### Top Contributors

For each cluster, report top 3 dimensions by delta magnitude:
- Example: `[("latency_p95", 0.85), ("error_rate", 0.12), ("tool_variance", 0.03)]`

## Implementation

### Module: `src/driftbase/local/task_clustering.py`

Functions:
- `cluster_runs_by_task(runs, max_clusters=5) -> dict[str, list[dict]]`
- `compute_per_cluster_drift(baseline, current, max_clusters=5) -> list[ClusterDriftResult]`

Dataclass:
```python
@dataclass
class ClusterDriftResult:
    cluster_id: str           # "search:0-100"
    cluster_label: str        # "search (0-100 chars)"
    baseline_n: int           # Sample size baseline
    current_n: int            # Sample size current
    drift_score: float        # [0, 1]
    top_contributors: list[tuple[str, float]]  # Top 3 dimensions
```

### Integration: `src/driftbase/local/diff.py`

```python
# Compute per-cluster drift analysis
cluster_analysis = None
if baseline_runs is not None and current_runs is not None:
    cluster_results = compute_per_cluster_drift(
        baseline_runs=baseline_runs, current_runs=current_runs, max_clusters=5
    )
    cluster_analysis = cluster_results if cluster_results else None
```

Attached to `DriftReport.cluster_analysis: list[ClusterDriftResult] | None`

## Why "Cheap" Clustering?

No ML models, no embeddings - just `O(n)` string operations:
- First tool: `json.loads(tool_sequence)[0]`
- Input length: `len(raw_prompt)`
- Bucket lookup: constant time

Fast enough to run on every drift computation with negligible overhead.

## Detection Scenarios

### When Clustering Reveals Hidden Drift

**Scenario 1: Task-specific regression**
- Global drift: 0.15 (MONITOR)
- Cluster analysis:
  - `search:0-100`: 0.02 (no drift)
  - `write:500-2000`: 0.68 (BLOCK)
  - `read:100-500`: 0.05 (no drift)
- **Action**: Block deployment due to write task regression, even though global score looks acceptable

**Scenario 2: Offsetting changes**
- search tasks 50% faster (good)
- write tasks 50% slower (bad)
- Global drift: 0.10 (looks fine, changes cancel out)
- Cluster analysis: both clusters show 0.50 drift
- **Action**: Investigate both improvements and regressions

**Scenario 3: Input length sensitivity**
- Short prompts (0-100): stable
- Long prompts (500-2000): 3x slower
- Global p95: moderate increase (dominated by short prompts)
- Cluster analysis: clearly shows long-prompt regression

## Output Format (Future: CLI/JSON)

*Planned for Task 5.7 completion:*

Markdown table:
```
Cluster Analysis:
| Cluster           | Baseline | Current | Drift | Top Contributor     |
|-------------------|----------|---------|-------|---------------------|
| search (0-100)    | 120      | 125     | 0.68  | latency_p95 (0.85)  |
| write (500-2000)  | 80       | 82      | 0.05  | error_rate (0.03)   |
```

JSON payload (`verdict_payload.py`):
```json
{
  "cluster_analysis": [
    {
      "cluster_id": "search:0-100",
      "cluster_label": "search (0-100 chars)",
      "baseline_n": 120,
      "current_n": 125,
      "drift_score": 0.68,
      "top_contributors": [["latency_p95", 0.85], ["error_rate", 0.12]]
    }
  ]
}
```

## Limitations

### When Clustering Doesn't Help

1. **Homogeneous workloads**: If all runs use same tool sequence and input length, clustering finds no sub-populations
2. **Small sample sizes**: Need >= 10 runs per cluster per version (30 runs total minimum)
3. **High task variety**: With 100 unique task types, most clusters won't have enough samples

### Clustering vs Global

- Global drift: faster, works with fewer runs (n >= 50)
- Cluster drift: requires more data (n >= 30 per cluster), but more targeted insights

Recommendation: Use both. Global score for CI gates, cluster analysis for investigation.

## Testing

Fixture: `single_cluster_drift_pair(n=300, seed=12)`
- 3 clusters: tool_a (short), tool_b (medium), tool_c (long)
- Only cluster 0 (tool_a) shows 50% latency increase
- Other clusters unchanged

Tests in `tests/test_signal_gains.py`:
- `test_cluster_runs_by_task_basic()` - clustering logic
- `test_cluster_runs_max_clusters()` - max clusters limit
- `test_compute_per_cluster_drift_insufficient_data()` - min sample requirement
- `test_single_cluster_drift_detection()` - fixture integration

## Future Enhancements

Potential Phase 6+ improvements:
1. **Semantic clustering**: Use LLM embeddings instead of first_tool
2. **Adaptive bucketing**: Learn input length buckets from data
3. **Multi-dimensional clustering**: Cluster by (tool, length, session_id)
4. **Anomaly clusters**: Flag clusters with unusual drift patterns

## See Also

- [12-Dimension Rationale](.claude/decisions/015-12-dimensions-rationale.md) - Single global score vs per-cluster
- [CLAUDE.md](../CLAUDE.md) - Scoring system architecture
