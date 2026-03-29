"""
Weight learning from labeled deploy outcomes.

Learns which drift dimensions predict bad outcomes for a specific agent
using point-biserial correlation. Never raises at runtime.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger(__name__)

DIMENSION_KEYS = [
    "decision_drift",
    "tool_sequence",
    "latency",
    "tool_distribution",
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
class LearnedWeights:
    """Result of weight learning from labeled deploy outcomes."""

    agent_id: str
    weights: dict[str, float]  # final blended weights
    raw_correlations: dict[str, float]  # before normalization
    learned_factor: float  # how much learned vs preset
    n_good: int
    n_bad: int
    n_total: int
    top_predictors: list[str]  # top 3 dimensions by correlation
    computed_at: datetime


def _compute_blending_factor(n_samples: int) -> float:
    """
    Compute blending factor based on training set size.

    At 10 samples: 20% learned, 80% preset
    At 20 samples: 40% learned, 60% preset
    At 50 samples: 70% learned, 30% preset
    At 100+ samples: 90% learned, 10% preset
    """
    if n_samples < 10:
        return 0.0
    return min(0.90, (n_samples - 10) / 100 + 0.20)


def learn_weights(
    agent_id: str,
    db_path: str | None = None,
) -> LearnedWeights | None:
    """
    Learn dimension weights from labeled deploy outcomes.

    Returns LearnedWeights if sufficient data exists (10+ labeled versions
    with runs). Returns None otherwise. Never raises.

    Args:
        agent_id: Agent identifier
        db_path: Optional database path

    Returns:
        LearnedWeights or None if insufficient data
    """
    try:
        from driftbase.backends.factory import get_backend
        from driftbase.local.diff import compute_drift
        from driftbase.local.fingerprinter import build_fingerprint_from_runs
        from driftbase.local.local_store import run_dict_to_agent_run
        from driftbase.local.use_case_inference import USE_CASE_WEIGHTS

        try:
            import numpy as np
            from scipy.stats import pointbiserialr
        except ImportError:
            logger.debug(
                "scipy not available for weight learning - install driftbase[analyze]"
            )
            return None

        backend = get_backend()

        # Load labeled versions with runs
        labeled_versions = backend.get_labeled_versions_with_drift(agent_id)

        if len(labeled_versions) < 10:
            logger.debug(
                f"Insufficient labeled deploys for {agent_id}: {len(labeled_versions)} (need 10+)"
            )
            return None

        # Build training data: compute drift scores for each labeled version
        training_data = []

        # We need a baseline to compare against - use the oldest good version
        baseline_version = None
        for v in reversed(labeled_versions):  # Reversed to get oldest first
            if v["outcome"] == "good":
                baseline_version = v["version"]
                break

        if not baseline_version:
            # No good baseline found - can't compute drift
            logger.debug(f"No good baseline version found for {agent_id}")
            return None

        baseline_runs = backend.get_runs(
            deployment_version=baseline_version, limit=1000
        )
        baseline_runs = [r for r in baseline_runs if r.get("session_id") == agent_id]

        if len(baseline_runs) < 5:
            logger.debug(
                f"Insufficient baseline runs for {agent_id}: {len(baseline_runs)}"
            )
            return None

        baseline_agent_runs = [run_dict_to_agent_run(r) for r in baseline_runs]
        baseline_fp = build_fingerprint_from_runs(
            baseline_agent_runs, baseline_version, "production"
        )

        # Compute drift for each labeled version
        for labeled_v in labeled_versions:
            version = labeled_v["version"]
            if version == baseline_version:
                continue  # Skip baseline itself

            current_runs = backend.get_runs(deployment_version=version, limit=1000)
            current_runs = [r for r in current_runs if r.get("session_id") == agent_id]

            if len(current_runs) < 5:
                continue

            current_agent_runs = [run_dict_to_agent_run(r) for r in current_runs]
            current_fp = build_fingerprint_from_runs(
                current_agent_runs, version, "production"
            )

            # Compute drift report
            drift_report = compute_drift(
                baseline=baseline_fp,
                current=current_fp,
                baseline_runs=baseline_runs,
                current_runs=current_runs,
            )

            # Extract dimension scores
            drift_scores = {}
            for dim in DIMENSION_KEYS:
                # Map dimension key to drift report attribute
                if dim == "decision_drift":
                    drift_scores[dim] = drift_report.decision_drift
                elif dim == "tool_sequence":
                    drift_scores[dim] = drift_report.tool_sequence_drift
                elif dim == "latency":
                    drift_scores[dim] = drift_report.latency_drift
                elif dim == "tool_distribution":
                    drift_scores[dim] = drift_report.decision_drift  # Proxy
                elif dim == "error_rate":
                    drift_scores[dim] = drift_report.error_drift
                elif dim == "loop_depth":
                    drift_scores[dim] = drift_report.loop_depth_drift
                elif dim == "verbosity_ratio":
                    drift_scores[dim] = drift_report.verbosity_drift
                elif dim == "retry_rate":
                    drift_scores[dim] = drift_report.retry_drift
                elif dim == "output_length":
                    drift_scores[dim] = drift_report.output_length_drift
                elif dim == "time_to_first_tool":
                    drift_scores[dim] = drift_report.planning_latency_drift
                elif dim == "semantic_drift":
                    drift_scores[dim] = drift_report.semantic_drift
                elif dim == "tool_sequence_transitions":
                    drift_scores[dim] = drift_report.tool_sequence_transitions_drift
                else:
                    drift_scores[dim] = 0.0

            training_data.append(
                {
                    "version": version,
                    "outcome": labeled_v["outcome"],
                    "drift_scores": drift_scores,
                }
            )

        if len(training_data) < 10:
            logger.debug(
                f"Insufficient training data after drift computation: {len(training_data)}"
            )
            return None

        # Build training matrix
        y = np.array([1 if r["outcome"] == "bad" else 0 for r in training_data])

        n_good = np.sum(y == 0)
        n_bad = np.sum(y == 1)

        if n_bad == 0:
            # No bad outcomes - can't learn
            logger.debug(f"No bad outcomes in training data for {agent_id}")
            return None

        # Compute point-biserial correlation for each dimension
        correlations = {}
        for dim in DIMENSION_KEYS:
            scores = np.array([r["drift_scores"][dim] for r in training_data])

            # Skip if no variance
            if np.std(scores) == 0:
                correlations[dim] = 0.0
                continue

            try:
                corr, pvalue = pointbiserialr(y, scores)
                # Clip negative correlations to 0
                correlations[dim] = max(0.0, corr) if not np.isnan(corr) else 0.0
            except Exception:
                correlations[dim] = 0.0

        # Check if all correlations are zero
        if all(c == 0.0 for c in correlations.values()):
            logger.debug(f"No predictive signal found for {agent_id}")
            return None

        # Normalize correlations to sum to 1.0
        total_corr = sum(correlations.values())
        if total_corr == 0:
            return None

        learned_weights_raw = {dim: c / total_corr for dim, c in correlations.items()}

        # Get preset weights for blending (use GENERAL as baseline)
        preset_weights = USE_CASE_WEIGHTS["GENERAL"]

        # Compute blending factor
        learned_factor = _compute_blending_factor(len(training_data))
        preset_factor = 1.0 - learned_factor

        # Blend learned and preset weights
        blended = {}
        for dim in DIMENSION_KEYS:
            learned_w = learned_weights_raw.get(dim, 0.0)
            preset_w = preset_weights.get(dim, 0.0)
            blended[dim] = learned_factor * learned_w + preset_factor * preset_w

        # Renormalize to sum to 1.0
        total = sum(blended.values())
        if total > 0:
            blended = {dim: w / total for dim, w in blended.items()}
        else:
            blended = preset_weights.copy()

        # Get top 3 predictors
        sorted_corrs = sorted(correlations.items(), key=lambda x: x[1], reverse=True)
        top_predictors = [dim for dim, corr in sorted_corrs[:3] if corr > 0]

        return LearnedWeights(
            agent_id=agent_id,
            weights=blended,
            raw_correlations=correlations,
            learned_factor=learned_factor,
            n_good=int(n_good),
            n_bad=int(n_bad),
            n_total=len(training_data),
            top_predictors=top_predictors,
            computed_at=datetime.utcnow(),
        )

    except Exception as e:
        logger.debug(f"Weight learning failed for {agent_id}: {e}")
        return None
