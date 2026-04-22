"""
Power analysis forecasts for TIER2 drift detection.

Estimates how many additional runs are needed to achieve sufficient statistical
power for full drift analysis (TIER3).
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
from scipy import stats

from driftbase.local.fingerprinter import build_fingerprint_from_runs
from driftbase.local.local_store import run_dict_to_agent_run
from driftbase.stats.dimension_ci import _extract_dimension_scores
from driftbase.utils.determinism import get_rng

logger = logging.getLogger(__name__)


def forecast_runs_needed(
    baseline_runs: list[dict[str, Any]],
    current_runs: list[dict[str, Any]],
    dimensions: list[str],
    target_mde: float = 0.10,
    alpha: float = 0.05,
    power: float = 0.80,
    n_bootstrap: int = 500,
    salt: str = "power_forecast",
) -> dict[str, int]:
    """
    Forecast additional runs needed per dimension to detect target effect size.

    Inverts the MDE formula to solve for required sample size given a target
    minimum detectable effect. Useful for TIER2 analysis where sample sizes
    are insufficient for full statistical analysis.

    Formula (assuming balanced samples):
        n_total = 2 * ((z_alpha/2 + z_power) * sigma / target_mde)^2
        additional_needed = max(0, n_total - n_current)

    Args:
        baseline_runs: List of run dicts (baseline version)
        current_runs: List of run dicts (current version)
        dimensions: List of dimension names to forecast for
        target_mde: Target minimum detectable effect (default 0.10)
        alpha: Significance level (default 0.05)
        power: Statistical power (default 0.80)
        n_bootstrap: Number of bootstrap iterations for variance estimation (default 500)
        salt: Salt for deterministic RNG

    Returns:
        Dict mapping dimension name to additional runs needed (int)
        Returns 0 if already sufficient, NaN on failure

    Notes:
        - Assumes balanced sampling (equal runs from baseline and current)
        - Returns floor of additional runs needed
        - Returns 0 if current sample already sufficient for target MDE
        - Returns NaN on failure, logs warning, never raises
    """
    try:
        # Validate inputs
        if not baseline_runs or not current_runs:
            logger.warning("Empty run lists provided to forecast_runs_needed")
            return dict.fromkeys(dimensions, -1)  # -1 sentinel for NaN

        n_baseline = len(baseline_runs)
        n_current = len(current_runs)
        n_total_current = n_baseline + n_current

        # Convert to AgentRun objects
        baseline_agent_runs = [run_dict_to_agent_run(r) for r in baseline_runs]
        current_agent_runs = [run_dict_to_agent_run(r) for r in current_runs]

        # Critical values for two-tailed test
        z_alpha_half = stats.norm.ppf(1 - alpha / 2)  # 1.96 for alpha=0.05
        z_power = stats.norm.ppf(power)  # 0.84 for power=0.80

        # Bootstrap to estimate variance per dimension
        rng = get_rng(salt)

        # Store bootstrap scores per dimension for variance estimation
        bootstrap_scores = {dim: [] for dim in dimensions}

        for _ in range(n_bootstrap):
            # Resample baseline runs with replacement
            baseline_indices = rng.choice(n_baseline, size=n_baseline, replace=True)
            resampled_baseline = [baseline_agent_runs[idx] for idx in baseline_indices]

            # Resample current runs with replacement
            current_indices = rng.choice(n_current, size=n_current, replace=True)
            resampled_current = [current_agent_runs[idx] for idx in current_indices]

            # Build temporary fingerprints from resampled runs
            from datetime import datetime

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

        # Compute runs needed for each dimension
        result = {}
        for dim in dimensions:
            boot_vals = bootstrap_scores[dim]
            if not boot_vals or len(boot_vals) < 2:
                logger.warning(
                    f"Insufficient bootstrap values for dimension {dim} power forecast"
                )
                result[dim] = -1  # -1 sentinel for NaN
                continue

            # Estimate pooled standard deviation from bootstrap variance
            sigma_pooled = float(np.std(boot_vals, ddof=1))

            # Prevent division by zero
            if target_mde <= 0:
                logger.warning(f"Invalid target_mde={target_mde}, must be > 0")
                result[dim] = -1  # -1 sentinel for NaN
                continue

            # Solve for required sample size (assuming balanced samples)
            # n_per_group = ((z_alpha/2 + z_power) * sigma / target_mde)^2
            n_per_group = ((z_alpha_half + z_power) * sigma_pooled / target_mde) ** 2
            n_total_needed = int(np.ceil(2 * n_per_group))

            # Additional runs needed (both baseline and current combined)
            additional_needed = max(0, n_total_needed - n_total_current)

            result[dim] = additional_needed

        return result

    except Exception as e:
        logger.warning(f"Failed to forecast runs needed: {e}")
        return dict.fromkeys(dimensions, -1)  # -1 sentinel for NaN
