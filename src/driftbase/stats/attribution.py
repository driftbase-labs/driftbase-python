"""
Counterfactual attribution analysis for drift dimensions.

Quantifies which dimensions contributed most to the composite drift score
via leave-one-out (LOO) analysis.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from driftbase.local.local_store import BehavioralFingerprint

logger = logging.getLogger(__name__)


def compute_dimension_attribution(
    baseline: BehavioralFingerprint,
    current: BehavioralFingerprint,
    calibrated_weights: dict[str, float],
    original_composite: float,
    dimension_scores: dict[str, float],
) -> dict[str, float]:
    """
    Compute counterfactual attribution for each drift dimension.

    For each dimension, compute what the composite score would be if that
    dimension showed zero drift (leave-one-out analysis). Attribution is
    the difference between original composite and counterfactual composite.

    Attribution interpretation:
        - Positive: dimension drove drift upward
        - Negative: dimension dampened drift (mitigating factor)
        - Near zero: dimension had minimal impact on composite

    Args:
        baseline: Baseline behavioral fingerprint
        current: Current behavioral fingerprint
        calibrated_weights: Calibrated weights for each dimension
        original_composite: Original composite drift score
        dimension_scores: Observed scores for all dimensions

    Returns:
        Dict mapping dimension name to attribution score (float)
        Sum of attributions ≈ original_composite (may differ due to nonlinearity)

    Notes:
        - Uses leave-one-out approach:
          composite_without_dim = sum(w_i * score_i for i != dim)
        - Attribution = original_composite - composite_without_dim
        - Returns NaN on failure, logs warning, never raises
    """
    try:
        # Validate inputs
        if not calibrated_weights or not dimension_scores:
            logger.warning(
                "Empty calibrated_weights or dimension_scores in attribution"
            )
            return {dim: float("nan") for dim in dimension_scores}

        # All 12 dimensions (standard drift dimensions)
        all_dimensions = [
            "decision_drift",
            "semantic_drift",
            "latency",
            "error_rate",
            "tool_distribution",
            "verbosity_ratio",
            "loop_depth",
            "output_length",
            "tool_sequence",
            "retry_rate",
            "time_to_first_tool",
            "tool_sequence_transitions",
        ]

        result = {}

        for dim in all_dimensions:
            # Compute composite without this dimension
            # composite_without_dim = sum(w_i * score_i for i != dim)
            composite_without_dim = 0.0
            for other_dim in all_dimensions:
                if other_dim != dim:
                    other_weight = calibrated_weights.get(other_dim, 0.0)
                    other_score = dimension_scores.get(other_dim, 0.0)
                    composite_without_dim += other_weight * other_score

            # Attribution = original - counterfactual
            # Positive means this dimension increased drift
            # Negative means this dimension decreased drift
            attribution = original_composite - composite_without_dim

            result[dim] = float(attribution)

        return result

    except Exception as e:
        logger.warning(f"Failed to compute dimension attribution: {e}")
        return {dim: float("nan") for dim in dimension_scores}


def compute_marginal_contribution(
    dimension_scores: dict[str, float],
    calibrated_weights: dict[str, float],
) -> dict[str, float]:
    """
    Compute marginal contribution of each dimension to composite score.

    Simpler alternative to counterfactual attribution. Marginal contribution
    is just the weighted score: w_i * score_i.

    This is NOT leave-one-out analysis - it's the direct linear contribution.
    Sum of marginal contributions = composite score (by construction).

    Args:
        dimension_scores: Observed scores for all dimensions
        calibrated_weights: Calibrated weights for each dimension

    Returns:
        Dict mapping dimension name to marginal contribution (float)

    Notes:
        - More interpretable than LOO attribution for linear composites
        - Guaranteed to sum to composite score
        - Does not account for interaction effects
    """
    try:
        result = {}
        for dim, score in dimension_scores.items():
            weight = calibrated_weights.get(dim, 0.0)
            result[dim] = weight * score
        return result

    except Exception as e:
        logger.warning(f"Failed to compute marginal contributions: {e}")
        return {dim: float("nan") for dim in dimension_scores}
