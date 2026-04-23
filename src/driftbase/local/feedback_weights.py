"""
Feedback-driven weight adjustment for drift detection.

Applies exponential decay to dimension weights based on user dismissals.
"""

from __future__ import annotations

import logging
from typing import Any

from driftbase.backends.base import StorageBackend

logger = logging.getLogger(__name__)

# Decay factor: 1 dismiss → 70%, 2 → 49%, 3 → 34%
DECAY_FACTOR = 0.7

# Minimum weight floor (never reduce below 10% of original)
WEIGHT_FLOOR = 0.1


def apply_feedback_weights(
    base_weights: dict[str, float], agent_id: str | None, backend: StorageBackend
) -> dict[str, float]:
    """
    Adjust drift weights based on user feedback dismissals.

    Args:
        base_weights: Calibrated weights from baseline_calibrator
        agent_id: Agent identifier for per-agent learning
        backend: Storage backend for feedback queries

    Returns:
        Adjusted weights dict (same keys as base_weights)

    Formula:
        adjusted_weight = base_weight * (DECAY_FACTOR ** dismiss_count)
        with floor: max(adjusted_weight, base_weight * WEIGHT_FLOOR)

    Never raises - returns base_weights on any error.
    """
    if not agent_id:
        logger.debug("No agent_id provided, skipping feedback weight adjustment")
        return base_weights

    if not base_weights:
        logger.debug("Empty base_weights, skipping feedback weight adjustment")
        return base_weights

    try:
        # Get all dismiss feedback for this agent
        all_feedback = backend.get_feedback_for_agent(agent_id)
        dismiss_feedback = [f for f in all_feedback if f["action"] == "dismiss"]

        if not dismiss_feedback:
            logger.debug(
                f"No dismiss feedback for agent {agent_id}, using base weights"
            )
            return base_weights

        # Count dismissals per dimension
        dismiss_counts: dict[str, int] = {}
        for feedback in dismiss_feedback:
            dismissed_dims = feedback.get("dismissed_dimensions")
            if not dismissed_dims:
                continue
            for dim in dismissed_dims:
                dismiss_counts[dim] = dismiss_counts.get(dim, 0) + 1

        if not dismiss_counts:
            logger.debug("No dismissed dimensions found, using base weights")
            return base_weights

        # Apply decay formula with floor
        adjusted_weights = {}
        for dim, base_weight in base_weights.items():
            if dim in dismiss_counts:
                count = dismiss_counts[dim]
                decay = DECAY_FACTOR**count
                adjusted = base_weight * decay
                floor = base_weight * WEIGHT_FLOOR
                adjusted_weights[dim] = max(adjusted, floor)

                logger.debug(
                    f"Feedback adjustment for {dim}: "
                    f"{count} dismissals → {base_weight:.3f} * {decay:.3f} = "
                    f"{adjusted_weights[dim]:.3f} (floor: {floor:.3f})"
                )
            else:
                # No dismissals for this dimension
                adjusted_weights[dim] = base_weight

        logger.info(
            f"Applied feedback weights for agent {agent_id}: "
            f"{len(dismiss_counts)} dimensions adjusted from {len(dismiss_feedback)} dismissals"
        )

        return adjusted_weights

    except Exception as e:
        logger.warning(f"Feedback weight adjustment failed for agent {agent_id}: {e}")
        return base_weights


def get_feedback_impact(
    base_weights: dict[str, float], agent_id: str | None, backend: StorageBackend
) -> dict[str, Any]:
    """
    Compute feedback impact report (for Task 6.6).

    Args:
        base_weights: Calibrated weights from baseline_calibrator
        agent_id: Agent identifier
        backend: Storage backend

    Returns:
        Dict with:
        - adjusted_weights: Weights after feedback
        - changes: List of {dimension, base, adjusted, dismiss_count}
        - total_dismissals: Total dismiss feedback count
    """
    adjusted_weights = apply_feedback_weights(base_weights, agent_id, backend)

    if not agent_id:
        return {
            "adjusted_weights": adjusted_weights,
            "changes": [],
            "total_dismissals": 0,
        }

    try:
        # Get dismiss counts
        all_feedback = backend.get_feedback_for_agent(agent_id)
        dismiss_feedback = [f for f in all_feedback if f["action"] == "dismiss"]

        dismiss_counts: dict[str, int] = {}
        for feedback in dismiss_feedback:
            dismissed_dims = feedback.get("dismissed_dimensions")
            if not dismissed_dims:
                continue
            for dim in dismissed_dims:
                dismiss_counts[dim] = dismiss_counts.get(dim, 0) + 1

        # Build changes report
        changes = []
        for dim in sorted(base_weights.keys()):
            base = base_weights[dim]
            adjusted = adjusted_weights[dim]
            if abs(adjusted - base) > 0.001:  # Changed
                changes.append(
                    {
                        "dimension": dim,
                        "base_weight": base,
                        "adjusted_weight": adjusted,
                        "dismiss_count": dismiss_counts.get(dim, 0),
                        "reduction_pct": ((base - adjusted) / base) * 100,
                    }
                )

        return {
            "adjusted_weights": adjusted_weights,
            "changes": changes,
            "total_dismissals": len(dismiss_feedback),
        }

    except Exception as e:
        logger.warning(f"Failed to compute feedback impact: {e}")
        return {
            "adjusted_weights": adjusted_weights,
            "changes": [],
            "total_dismissals": 0,
        }
