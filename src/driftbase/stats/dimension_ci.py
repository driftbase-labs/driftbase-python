"""
Bootstrap confidence intervals for drift dimensions.

Computes per-dimension 95% CIs via bootstrap resampling of runs.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime

import numpy as np

from driftbase.utils.determinism import get_rng

logger = logging.getLogger(__name__)


@dataclass
class DimensionCI:
    """Confidence interval for a drift dimension."""

    dimension: str
    observed: float
    ci_lower: float
    ci_upper: float
    significant: bool  # True if CI excludes 0


def _jensen_shannon_divergence(p: dict[str, float], q: dict[str, float]) -> float:
    """Compute JSD between two distributions."""
    all_keys = set(p.keys()) | set(q.keys())
    if not all_keys:
        return 0.0

    p_arr = np.array([p.get(k, 0.0) for k in all_keys])
    q_arr = np.array([q.get(k, 0.0) for k in all_keys])

    # Normalize
    p_sum = p_arr.sum()
    q_sum = q_arr.sum()
    if p_sum > 0:
        p_arr = p_arr / p_sum
    if q_sum > 0:
        q_arr = q_arr / q_sum

    # JSD
    m = 0.5 * (p_arr + q_arr)
    m = np.where(m == 0, 1e-10, m)
    p_arr = np.where(p_arr == 0, 1e-10, p_arr)
    q_arr = np.where(q_arr == 0, 1e-10, q_arr)

    kl_pm = np.sum(p_arr * np.log(p_arr / m))
    kl_qm = np.sum(q_arr * np.log(q_arr / m))
    jsd = 0.5 * kl_pm + 0.5 * kl_qm
    return float(np.clip(jsd, 0.0, 1.0))


def _sigmoid_contribution(delta: float, k: float, c: float) -> float:
    """Sigmoid contribution for continuous metrics."""
    return float(1.0 / (1.0 + np.exp(-k * (delta - c))))


def _extract_dimension_scores(
    baseline_fp,
    current_fp,
) -> dict[str, float]:
    """
    Extract all 12 dimension scores from two fingerprints.

    Replicates dimension computation logic from diff.py without refactoring.
    """
    scores = {}

    # decision_drift: JSD on tool_sequence_distribution
    base_dist = json.loads(baseline_fp.tool_sequence_distribution)
    curr_dist = json.loads(current_fp.tool_sequence_distribution)
    scores["decision_drift"] = _jensen_shannon_divergence(base_dist, curr_dist)

    # semantic_drift: JSD on semantic_cluster_distribution
    base_sem = json.loads(baseline_fp.semantic_cluster_distribution or "{}")
    curr_sem = json.loads(current_fp.semantic_cluster_distribution or "{}")
    scores["semantic_drift"] = _jensen_shannon_divergence(base_sem, curr_sem)

    # latency_drift: normalized delta on p95_latency_ms
    base_p95 = max(baseline_fp.p95_latency_ms, 1)
    latency_delta_raw = (
        abs(current_fp.p95_latency_ms - baseline_fp.p95_latency_ms) / base_p95
    )
    scores["latency"] = min(1.0, latency_delta_raw)

    # error_drift: scaled delta on error_rate
    error_delta_raw = abs(current_fp.error_rate - baseline_fp.error_rate)
    scores["error_rate"] = min(1.0, error_delta_raw * 2.0)

    # tool_distribution: uses decision_drift as proxy (fingerprint schema debt)
    scores["tool_distribution"] = scores["decision_drift"]

    # verbosity_drift: sigmoid on verbosity_ratio delta
    baseline_verbosity = baseline_fp.avg_verbosity_ratio
    current_verbosity = current_fp.avg_verbosity_ratio
    verbosity_delta = abs(current_verbosity - baseline_verbosity)
    scores["verbosity_ratio"] = _sigmoid_contribution(verbosity_delta, k=3.0, c=0.3)

    # loop_depth_drift: normalized delta on p95_loop_count
    baseline_p95_loop = baseline_fp.p95_loop_count
    current_p95_loop = current_fp.p95_loop_count
    loop_delta = abs(current_p95_loop - baseline_p95_loop) / max(baseline_p95_loop, 1.0)
    scores["loop_depth"] = min(1.0, loop_delta)

    # output_length_drift: normalized delta on avg_output_length
    baseline_out_len = baseline_fp.avg_output_length
    current_out_len = current_fp.avg_output_length
    out_len_delta = abs(current_out_len - baseline_out_len) / max(baseline_out_len, 1.0)
    scores["output_length"] = min(1.0, out_len_delta)

    # tool_sequence_drift: uses decision_drift as proxy
    scores["tool_sequence"] = scores["decision_drift"]

    # retry_drift: scaled delta on avg_retry_count
    baseline_retry = baseline_fp.avg_retry_count
    current_retry = current_fp.avg_retry_count
    retry_delta = abs(current_retry - baseline_retry)
    scores["retry_rate"] = min(1.0, retry_delta * 2.0)

    # planning_latency_drift: normalized delta on avg_time_to_first_tool_ms
    baseline_planning = baseline_fp.avg_time_to_first_tool_ms
    current_planning = current_fp.avg_time_to_first_tool_ms
    planning_delta = abs(current_planning - baseline_planning) / max(
        baseline_planning, 1.0
    )
    scores["time_to_first_tool"] = min(1.0, planning_delta)

    # tool_sequence_transitions_drift: uses decision_drift as proxy
    scores["tool_sequence_transitions"] = scores["decision_drift"]

    return scores


def compute_dimension_cis(
    baseline_runs: list[dict],
    current_runs: list[dict],
    dimensions: list[str],
    n_bootstrap: int = 500,
    confidence_level: float = 0.95,
    salt: str = "dimension_ci",
) -> dict[str, DimensionCI]:
    """
    Compute bootstrap confidence intervals for drift dimensions.

    Args:
        baseline_runs: List of run dicts (baseline version)
        current_runs: List of run dicts (current version)
        dimensions: List of dimension names to compute CIs for
        n_bootstrap: Number of bootstrap iterations (default 500)
        confidence_level: Confidence level for CIs (default 0.95)
        salt: Salt for deterministic RNG

    Returns:
        Dict mapping dimension name to DimensionCI

    Notes:
        - Resamples runs ONCE per iteration, computes all dimensions from
          same resample
        - Uses wrapper approach (builds temporary fingerprints) to avoid
          refactoring diff.py
        - Returns NaN CIs on failure, logs warning, never raises
    """
    try:
        # Validate inputs
        if not baseline_runs or not current_runs:
            logger.warning("Empty run lists provided to compute_dimension_cis")
            return {
                dim: DimensionCI(
                    dimension=dim,
                    observed=float("nan"),
                    ci_lower=float("nan"),
                    ci_upper=float("nan"),
                    significant=False,
                )
                for dim in dimensions
            }

        # Compute observed dimension scores
        # Build fingerprints from full run lists
        from driftbase.local.fingerprinter import build_fingerprint_from_runs
        from driftbase.local.local_store import run_dict_to_agent_run

        baseline_agent_runs = [run_dict_to_agent_run(r) for r in baseline_runs]
        current_agent_runs = [run_dict_to_agent_run(r) for r in current_runs]

        baseline_fp = build_fingerprint_from_runs(
            runs=baseline_agent_runs,
            window_start=datetime.min,
            window_end=datetime.max,
            deployment_version="baseline",
            environment="production",
        )
        current_fp = build_fingerprint_from_runs(
            runs=current_agent_runs,
            window_start=datetime.min,
            window_end=datetime.max,
            deployment_version="current",
            environment="production",
        )
        observed_scores = _extract_dimension_scores(baseline_fp, current_fp)

        # Bootstrap: resample runs once per iteration, compute all dimensions
        rng = get_rng(salt)
        n_baseline = len(baseline_runs)
        n_current = len(current_runs)

        # Store bootstrap scores per dimension
        bootstrap_scores = {dim: [] for dim in dimensions}

        for _ in range(n_bootstrap):
            # Resample baseline runs with replacement
            baseline_indices = rng.choice(n_baseline, size=n_baseline, replace=True)
            resampled_baseline = [baseline_agent_runs[idx] for idx in baseline_indices]

            # Resample current runs with replacement
            current_indices = rng.choice(n_current, size=n_current, replace=True)
            resampled_current = [current_agent_runs[idx] for idx in current_indices]

            # Build temporary fingerprints from resampled runs
            baseline_fp_boot = build_fingerprint_from_runs(
                runs=resampled_baseline,
                window_start=datetime.min,
                window_end=datetime.max,
                deployment_version="baseline_boot",
                environment="production",
            )
            current_fp_boot = build_fingerprint_from_runs(
                runs=resampled_current,
                window_start=datetime.min,
                window_end=datetime.max,
                deployment_version="current_boot",
                environment="production",
            )

            # Extract all dimension scores from this bootstrap sample
            boot_scores = _extract_dimension_scores(baseline_fp_boot, current_fp_boot)

            # Store scores for each dimension
            for dim in dimensions:
                if dim in boot_scores:
                    bootstrap_scores[dim].append(boot_scores[dim])

        # Compute CIs from bootstrap distributions
        alpha = 1.0 - confidence_level
        lower_percentile = 100 * (alpha / 2)
        upper_percentile = 100 * (1 - alpha / 2)

        result = {}
        for dim in dimensions:
            if dim not in observed_scores:
                logger.warning(f"Dimension {dim} not found in observed scores")
                result[dim] = DimensionCI(
                    dimension=dim,
                    observed=float("nan"),
                    ci_lower=float("nan"),
                    ci_upper=float("nan"),
                    significant=False,
                )
                continue

            boot_vals = bootstrap_scores[dim]
            if not boot_vals:
                logger.warning(f"No bootstrap values for dimension {dim}")
                result[dim] = DimensionCI(
                    dimension=dim,
                    observed=observed_scores[dim],
                    ci_lower=float("nan"),
                    ci_upper=float("nan"),
                    significant=False,
                )
                continue

            ci_lower = float(np.percentile(boot_vals, lower_percentile))
            ci_upper = float(np.percentile(boot_vals, upper_percentile))
            observed = observed_scores[dim]

            # Significant if CI excludes 0
            significant = ci_lower > 0.0

            result[dim] = DimensionCI(
                dimension=dim,
                observed=observed,
                ci_lower=ci_lower,
                ci_upper=ci_upper,
                significant=significant,
            )

        return result

    except Exception as e:
        logger.warning(f"Failed to compute dimension CIs: {e}")
        return {
            dim: DimensionCI(
                dimension=dim,
                observed=float("nan"),
                ci_lower=float("nan"),
                ci_upper=float("nan"),
                significant=False,
            )
            for dim in dimensions
        }
