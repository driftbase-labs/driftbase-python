"""
Minimum Detectable Effect (MDE) computation for drift dimensions.

Estimates the smallest drift effect that can be reliably detected given
current sample sizes and statistical parameters.
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


def compute_mde(
    baseline_runs: list[dict[str, Any]],
    current_runs: list[dict[str, Any]],
    dimensions: list[str],
    alpha: float = 0.05,
    power: float = 0.80,
    n_bootstrap: int = 500,
    salt: str = "mde_estimation",
) -> dict[str, float]:
    """
    Compute Minimum Detectable Effect (MDE) for each drift dimension.

    The MDE is the smallest effect size that can be detected with specified
    statistical power given current sample sizes. Smaller MDEs indicate better
    detection sensitivity.

    Formula:
        MDE = (z_alpha/2 + z_power) * sigma_pooled * sqrt(1/n_baseline + 1/n_current)

    Where:
        - z_alpha/2 = critical value for two-tailed test (1.96 for alpha=0.05)
        - z_power = critical value for power (0.84 for power=0.80)
        - sigma_pooled = pooled standard deviation estimated from bootstrap

    Args:
        baseline_runs: List of run dicts (baseline version)
        current_runs: List of run dicts (current version)
        dimensions: List of dimension names to compute MDEs for
        alpha: Significance level (default 0.05)
        power: Statistical power (default 0.80)
        n_bootstrap: Number of bootstrap iterations for variance estimation (default 500)
        salt: Salt for deterministic RNG

    Returns:
        Dict mapping dimension name to MDE (float)

    Notes:
        - Returns NaN on failure, logs warning, never raises
        - Uses bootstrap to estimate pooled standard deviation
        - MDE increases with lower sample sizes (need more runs to detect smaller effects)
        - MDE decreases with higher variance (noisier dimensions need larger effects)
    """
    try:
        # Validate inputs
        if not baseline_runs or not current_runs:
            logger.warning("Empty run lists provided to compute_mde")
            return {dim: float("nan") for dim in dimensions}

        n_baseline = len(baseline_runs)
        n_current = len(current_runs)

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

        # Compute MDE for each dimension
        result = {}
        for dim in dimensions:
            boot_vals = bootstrap_scores[dim]
            if not boot_vals or len(boot_vals) < 2:
                logger.warning(f"Insufficient bootstrap values for dimension {dim}")
                result[dim] = float("nan")
                continue

            # Estimate pooled standard deviation from bootstrap variance
            sigma_pooled = float(np.std(boot_vals, ddof=1))

            # MDE formula
            mde = (
                (z_alpha_half + z_power)
                * sigma_pooled
                * np.sqrt(1 / n_baseline + 1 / n_current)
            )

            result[dim] = float(mde)

        return result

    except Exception as e:
        logger.warning(f"Failed to compute MDEs: {e}")
        return {dim: float("nan") for dim in dimensions}
