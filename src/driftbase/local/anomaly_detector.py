"""
Isolation forest anomaly detection for multivariate behavioral drift.

Supplementary signal to the weighted composite drift score.
Catches correlated shifts across multiple dimensions that per-dimension
scoring misses.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler

logger = logging.getLogger(__name__)

ANOMALY_DIMENSIONS = [
    "decision_drift",
    "tool_sequence",
    "tool_distribution",
    "latency",
    "error_rate",
    "loop_depth",
    "verbosity_ratio",
    "retry_rate",
    "output_length",
    "time_to_first_tool",
    "semantic_drift",
    "tool_sequence_transitions",
]


@dataclass
class AnomalySignal:
    """Anomaly detection result for multivariate behavioral drift."""

    score: float  # 0.0–1.0, higher = more anomalous
    level: str  # "NORMAL" | "ELEVATED" | "HIGH" | "CRITICAL"
    contributing_dimensions: list[str]  # top 3 dims driving anomaly
    baseline_n: int  # training set size
    eval_n: int  # eval set size
    method: str  # "isolation_forest"
    contamination: float  # assumed outlier rate in baseline


def _score_to_level(score: float) -> str:
    """Map anomaly score to severity level."""
    if score >= 0.75:
        return "CRITICAL"
    if score >= 0.55:
        return "HIGH"
    if score >= 0.30:
        return "ELEVATED"
    return "NORMAL"


def _extract_behavioral_vector(run: dict[str, Any]) -> list[float]:
    """Extract 12-dimensional behavioral vector from a single run.

    Missing values are filled with 0.0 (not available = no drift).
    Returns normalized dimension scores.
    """
    vector = []

    # decision_drift: approximated by tool diversity (0–1)
    try:
        import json

        tool_seq = run.get("tool_sequence", "[]")
        if isinstance(tool_seq, str):
            tools = json.loads(tool_seq)
            unique_tools = len(set(tools)) if tools else 0
            total_tools = len(tools) if tools else 1
            vector.append(min(1.0, unique_tools / max(total_tools, 1)))
        else:
            vector.append(0.0)
    except Exception:
        vector.append(0.0)

    # tool_sequence: tool call count normalized
    tool_count = run.get("tool_call_count", 0)
    vector.append(min(1.0, tool_count / 20.0))

    # tool_distribution: same as decision_drift (placeholder)
    vector.append(vector[0] if vector else 0.0)

    # latency: normalized by 5000ms
    latency = run.get("latency_ms", 0)
    vector.append(min(1.0, latency / 5000.0))

    # error_rate: normalized by 10 errors
    error_count = run.get("error_count", 0)
    vector.append(min(1.0, error_count / 10.0))

    # loop_depth: normalized by 20 loops
    loop_count = run.get("loop_count", 0)
    vector.append(min(1.0, loop_count / 20.0))

    # verbosity_ratio: already 0–1
    verbosity_ratio = run.get("verbosity_ratio", 0.0)
    vector.append(min(1.0, max(0.0, verbosity_ratio)))

    # retry_rate: normalized by 5 retries
    retry_count = run.get("retry_count", 0)
    vector.append(min(1.0, retry_count / 5.0))

    # output_length: normalized by 10000 chars
    output_length = run.get("output_length", 0)
    vector.append(min(1.0, output_length / 10000.0))

    # time_to_first_tool: normalized by 5000ms
    time_to_first_tool = run.get("time_to_first_tool_ms", 0)
    vector.append(min(1.0, time_to_first_tool / 5000.0))

    # semantic_drift: placeholder (would need cluster data)
    vector.append(0.0)

    # tool_sequence_transitions: placeholder (would need transition matrix)
    vector.append(0.0)

    return vector


def _identify_contributing_dimensions(
    baseline_matrix: list[list[float]],
    eval_matrix: list[list[float]],
) -> list[str]:
    """Identify top 3 dimensions by distribution shift magnitude.

    Computes mean difference normalized by baseline std for each dimension.
    Returns dimension names sorted by shift magnitude.
    """
    try:
        baseline_arr = np.array(baseline_matrix)
        eval_arr = np.array(eval_matrix)

        dimension_shifts = {}
        for i, dim in enumerate(ANOMALY_DIMENSIONS):
            baseline_vals = baseline_arr[:, i]
            eval_vals = eval_arr[:, i]
            baseline_std = np.std(baseline_vals)

            if baseline_std < 1e-9:
                dimension_shifts[dim] = 0.0
            else:
                shift = abs(np.mean(eval_vals) - np.mean(baseline_vals)) / baseline_std
                dimension_shifts[dim] = float(shift)

        # Return top 3 dimensions by shift magnitude
        top_dims = sorted(dimension_shifts, key=dimension_shifts.get, reverse=True)[:3]
        return top_dims
    except Exception as e:
        logger.debug(f"Failed to identify contributing dimensions: {e}")
        return []


def compute_anomaly_signal(
    baseline_runs: list[dict[str, Any]],
    eval_runs: list[dict[str, Any]],
    dimensions: list[str] | None = None,
) -> AnomalySignal | None:
    """
    Fit an isolation forest on baseline behavioral vectors.
    Score eval behavioral vectors against the model.
    Return AnomalySignal with aggregate score and contributing dimensions.

    Returns None if:
    - fewer than 30 baseline runs
    - fewer than 5 eval runs
    - any exception occurs

    Never raises.

    Args:
        baseline_runs: List of baseline run dicts
        eval_runs: List of eval run dicts
        dimensions: Optional list of dimension names (unused, for future extension)

    Returns:
        AnomalySignal if detection succeeds, None otherwise
    """
    try:
        # Check minimum data requirements
        if len(baseline_runs) < 30:
            logger.debug(
                f"Insufficient baseline runs for anomaly detection (n={len(baseline_runs)}, need 30)"
            )
            return None

        if len(eval_runs) < 5:
            logger.debug(
                f"Insufficient eval runs for anomaly detection (n={len(eval_runs)}, need 5)"
            )
            return None

        # Extract behavioral vectors
        baseline_matrix = []
        for run in baseline_runs:
            vector = _extract_behavioral_vector(run)
            baseline_matrix.append(vector)

        eval_matrix = []
        for run in eval_runs:
            vector = _extract_behavioral_vector(run)
            eval_matrix.append(vector)

        # Convert to numpy arrays
        baseline_arr = np.array(baseline_matrix)
        eval_arr = np.array(eval_matrix)

        # Scale features using baseline distribution
        scaler = StandardScaler()
        baseline_scaled = scaler.fit_transform(baseline_arr)
        eval_scaled = scaler.transform(eval_arr)

        # Fit isolation forest on baseline
        # contamination=0.05: assume 5% of baseline runs are slight outliers
        # n_estimators=100: standard, fast enough for typical run counts
        # random_state from DRIFTBASE_SEED for reproducibility
        from driftbase.config import get_settings

        settings = get_settings()
        model = IsolationForest(
            contamination=0.05,
            n_estimators=100,
            random_state=settings.DRIFTBASE_SEED,
        )
        model.fit(baseline_scaled)

        # Score eval runs
        # decision_function returns: positive = inlier, negative = outlier
        # Convert to 0-1 scale where 1 = most anomalous
        raw_scores = model.decision_function(eval_scaled)

        # Normalize: most negative (most anomalous) → 1.0
        # Most positive (most normal) → 0.0
        min_score = raw_scores.min()
        max_score = raw_scores.max()

        if max_score == min_score:
            # All runs have same score - no anomaly
            normalized = np.zeros(len(raw_scores))
        else:
            normalized = (max_score - raw_scores) / (max_score - min_score)

        # Aggregate: use 90th percentile of eval anomaly scores
        # (most anomalous eval runs, not average)
        aggregate_score = float(np.percentile(normalized, 90))

        # Identify contributing dimensions
        top_dims = _identify_contributing_dimensions(baseline_matrix, eval_matrix)

        # Map score to level
        level = _score_to_level(aggregate_score)

        return AnomalySignal(
            score=round(aggregate_score, 4),
            level=level,
            contributing_dimensions=top_dims,
            baseline_n=len(baseline_runs),
            eval_n=len(eval_runs),
            method="isolation_forest",
            contamination=0.05,
        )

    except Exception as e:
        logger.debug(f"Anomaly detection failed: {e}")
        return None
