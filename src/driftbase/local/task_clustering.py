"""Task clustering for per-task-type drift analysis."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ClusterDriftResult:
    """Per-cluster drift analysis result."""

    cluster_id: str
    cluster_label: str
    baseline_n: int
    current_n: int
    drift_score: float
    top_contributors: list[tuple[str, float]]  # [(dimension, score), ...]


def cluster_runs_by_task(
    runs: list[dict[str, Any]], max_clusters: int = 5
) -> dict[str, list[dict[str, Any]]]:
    """
    Cluster runs by task type using cheap heuristics.

    Clustering key: (first_tool, input_length_bucket)
    - first_tool: First tool in tool_sequence
    - input_length_bucket: 0-100, 100-500, 500-2000, 2000+ chars

    Args:
        runs: Run dicts (must have 'tool_sequence' field, optionally 'raw_prompt')
        max_clusters: Maximum number of clusters to return (keeps top N by size)

    Returns:
        Dict mapping cluster_id to list of run dicts
        Example: {"search:0-100": [run1, run2], "write:100-500": [run3]}
    """
    if not runs:
        return {}

    clusters: dict[str, list[dict[str, Any]]] = {}

    for run in runs:
        # Extract first tool from tool_sequence
        tool_seq_str = run.get("tool_sequence", "[]")
        first_tool = "unknown"
        try:
            if isinstance(tool_seq_str, str):
                tools = json.loads(tool_seq_str)
            else:
                tools = tool_seq_str
            if isinstance(tools, list) and tools:
                first_tool = str(tools[0])
        except (json.JSONDecodeError, TypeError, IndexError):
            pass

        # Bucket input length
        input_length = len(run.get("raw_prompt", ""))
        if input_length < 100:
            bucket = "0-100"
        elif input_length < 500:
            bucket = "100-500"
        elif input_length < 2000:
            bucket = "500-2000"
        else:
            bucket = "2000+"

        cluster_id = f"{first_tool}:{bucket}"
        if cluster_id not in clusters:
            clusters[cluster_id] = []
        clusters[cluster_id].append(run)

    # Keep only top max_clusters by size
    sorted_clusters = sorted(clusters.items(), key=lambda x: len(x[1]), reverse=True)
    top_clusters = dict(sorted_clusters[:max_clusters])

    return top_clusters


def compute_per_cluster_drift(
    baseline_runs: list[dict[str, Any]],
    current_runs: list[dict[str, Any]],
    max_clusters: int = 5,
) -> list[ClusterDriftResult]:
    """
    Compute drift for each task cluster separately.

    Args:
        baseline_runs: Baseline run dicts
        current_runs: Current run dicts
        max_clusters: Maximum clusters to analyze

    Returns:
        List of ClusterDriftResult, one per cluster with sufficient data
        Empty list if insufficient data for clustering

    Note:
        Requires >= 10 runs per cluster per version for analysis.
        Uses simplified drift scoring (decision + latency + error JSD).
    """
    if not baseline_runs or not current_runs:
        return []

    baseline_clusters = cluster_runs_by_task(baseline_runs, max_clusters=max_clusters)
    current_clusters = cluster_runs_by_task(current_runs, max_clusters=max_clusters)

    # Find clusters present in both versions
    common_cluster_ids = set(baseline_clusters.keys()) & set(current_clusters.keys())

    results = []
    for cluster_id in common_cluster_ids:
        baseline_cluster = baseline_clusters[cluster_id]
        current_cluster = current_clusters[cluster_id]

        # Require minimum 10 runs per cluster per version
        if len(baseline_cluster) < 10 or len(current_cluster) < 10:
            continue

        # Compute simplified drift score for this cluster
        drift_score = _compute_cluster_drift_score(baseline_cluster, current_cluster)

        # Generate human-readable label
        parts = cluster_id.split(":")
        tool = parts[0] if parts else "unknown"
        bucket = parts[1] if len(parts) > 1 else "unknown"
        cluster_label = f"{tool} ({bucket} chars)"

        # Top contributors (simplified: just show which dimensions varied most)
        top_contributors = _compute_cluster_top_contributors(
            baseline_cluster, current_cluster
        )

        results.append(
            ClusterDriftResult(
                cluster_id=cluster_id,
                cluster_label=cluster_label,
                baseline_n=len(baseline_cluster),
                current_n=len(current_cluster),
                drift_score=drift_score,
                top_contributors=top_contributors,
            )
        )

    # Sort by drift_score descending
    results.sort(key=lambda x: x.drift_score, reverse=True)

    return results


def _compute_cluster_drift_score(
    baseline_cluster: list[dict[str, Any]], current_cluster: list[dict[str, Any]]
) -> float:
    """
    Compute simplified drift score for a single cluster.

    Uses three dimensions: latency (p95), error rate, tool sequence variance.
    """
    if not baseline_cluster or not current_cluster:
        return 0.0

    # Latency drift (p95)
    baseline_latencies = [r.get("latency_ms", 0) for r in baseline_cluster]
    current_latencies = [r.get("latency_ms", 0) for r in current_cluster]
    baseline_p95 = _percentile(baseline_latencies, 95)
    current_p95 = _percentile(current_latencies, 95)
    latency_delta = abs(current_p95 - baseline_p95) / max(baseline_p95, 1.0)
    latency_drift = min(1.0, latency_delta)

    # Error rate drift
    baseline_errors = sum(r.get("error_count", 0) for r in baseline_cluster)
    current_errors = sum(r.get("error_count", 0) for r in current_cluster)
    baseline_error_rate = baseline_errors / len(baseline_cluster)
    current_error_rate = current_errors / len(current_cluster)
    error_drift = min(1.0, abs(current_error_rate - baseline_error_rate) * 2.0)

    # Tool sequence variance (unique sequences / total runs)
    baseline_seqs = {r.get("tool_sequence", "[]") for r in baseline_cluster}
    current_seqs = {r.get("tool_sequence", "[]") for r in current_cluster}
    baseline_variance = len(baseline_seqs) / len(baseline_cluster)
    current_variance = len(current_seqs) / len(current_cluster)
    variance_drift = min(1.0, abs(current_variance - baseline_variance))

    # Weighted composite (equal weights for simplicity)
    drift_score = 0.4 * latency_drift + 0.4 * error_drift + 0.2 * variance_drift

    return min(1.0, max(0.0, drift_score))


def _compute_cluster_top_contributors(
    baseline_cluster: list[dict[str, Any]], current_cluster: list[dict[str, Any]]
) -> list[tuple[str, float]]:
    """
    Identify top contributing dimensions to cluster drift.

    Returns top 3 dimensions by delta magnitude.
    """
    contributors = []

    # Latency
    baseline_latencies = [r.get("latency_ms", 0) for r in baseline_cluster]
    current_latencies = [r.get("latency_ms", 0) for r in current_cluster]
    baseline_p95 = _percentile(baseline_latencies, 95)
    current_p95 = _percentile(current_latencies, 95)
    latency_delta = abs(current_p95 - baseline_p95) / max(baseline_p95, 1.0)
    contributors.append(("latency_p95", latency_delta))

    # Error rate
    baseline_errors = sum(r.get("error_count", 0) for r in baseline_cluster)
    current_errors = sum(r.get("error_count", 0) for r in current_cluster)
    baseline_error_rate = baseline_errors / len(baseline_cluster)
    current_error_rate = current_errors / len(current_cluster)
    error_delta = abs(current_error_rate - baseline_error_rate)
    contributors.append(("error_rate", error_delta))

    # Tool sequence variance
    baseline_seqs = {r.get("tool_sequence", "[]") for r in baseline_cluster}
    current_seqs = {r.get("tool_sequence", "[]") for r in current_cluster}
    baseline_variance = len(baseline_seqs) / len(baseline_cluster)
    current_variance = len(current_seqs) / len(current_cluster)
    variance_delta = abs(current_variance - baseline_variance)
    contributors.append(("tool_variance", variance_delta))

    # Sort by delta descending, take top 3
    contributors.sort(key=lambda x: x[1], reverse=True)
    return contributors[:3]


def _percentile(values: list[int | float], p: int) -> float:
    """Compute percentile from list of values."""
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    index = int(len(sorted_vals) * p / 100)
    index = min(index, len(sorted_vals) - 1)
    return float(sorted_vals[index])
