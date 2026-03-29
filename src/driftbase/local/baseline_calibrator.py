"""
Baseline calibration: measures dimension variance, derives statistical thresholds.

Computes reliability-adjusted weights and per-dimension thresholds from baseline runs.
Applies volume and sensitivity multipliers. Caches results to avoid recomputation.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_THRESHOLDS = {
    "MONITOR": 0.15,
    "REVIEW": 0.28,
    "BLOCK": 0.42,
}

VOLUME_MULTIPLIERS = [
    (500, 1.00),
    (2000, 0.90),
    (10000, 0.80),
    (None, 0.70),
]

SENSITIVITY_MULTIPLIERS = {
    "strict": 0.75,
    "standard": 1.00,
    "relaxed": 1.35,
}

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
class CalibrationResult:
    """Result of baseline calibration with weights, thresholds, and metadata."""

    calibrated_weights: dict[str, float]
    thresholds: dict[str, dict[str, float]]
    composite_thresholds: dict[str, float]
    calibration_method: str
    baseline_n: int
    reliability_multipliers: dict[str, float]
    inferred_use_case: str
    confidence: float


def _volume_multiplier(run_count: int) -> float:
    """Return threshold multiplier based on run count (tighten for higher volume)."""
    for threshold, multiplier in VOLUME_MULTIPLIERS:
        if threshold is None or run_count < threshold:
            return multiplier
    return 1.00


def _redistribute_weights(
    weights: dict[str, float],
    unavailable_dimensions: list[str],
) -> dict[str, float]:
    """
    Redistribute weights from unavailable dimensions proportionally across available ones.

    When semantic_drift or tool_sequence_transitions data is missing, we zero their
    weights and redistribute proportionally to remaining dimensions so total = 1.0.

    Never raises - degrades silently to avoid breaking drift computation.

    Args:
        weights: Original weight dictionary
        unavailable_dimensions: List of dimension keys to zero out

    Returns:
        Redistributed weights dictionary (still sums to 1.0)
    """
    try:
        if not unavailable_dimensions:
            return weights.copy()

        # Zero out unavailable dimensions
        redistributed = weights.copy()
        weight_to_redistribute = 0.0

        for dim in unavailable_dimensions:
            if dim in redistributed:
                weight_to_redistribute += redistributed[dim]
                redistributed[dim] = 0.0

        # If no weight to redistribute, we're done
        if weight_to_redistribute <= 0.0:
            return redistributed

        # Sum remaining weights (excluding zeroed dimensions)
        remaining_sum = sum(
            w for k, w in redistributed.items() if k not in unavailable_dimensions
        )

        # If no remaining dimensions have weight, fall back to equal distribution
        if remaining_sum <= 0.0:
            available_dims = [
                k for k in redistributed if k not in unavailable_dimensions
            ]
            if not available_dims:
                return redistributed
            equal_weight = 1.0 / len(available_dims)
            return {
                k: (equal_weight if k not in unavailable_dimensions else 0.0)
                for k in redistributed
            }

        # Redistribute proportionally to non-zero, available dimensions
        for dim in redistributed:
            if dim not in unavailable_dimensions and redistributed[dim] > 0.0:
                proportion = redistributed[dim] / remaining_sum
                redistributed[dim] += weight_to_redistribute * proportion

        # Verify sum is still ~1.0 (allow small floating point error)
        total = sum(redistributed.values())
        if abs(total - 1.0) > 0.01:
            logger.warning(
                f"Weight redistribution resulted in sum={total:.4f}, expected 1.0"
            )

        return redistributed

    except Exception as e:
        logger.debug(f"Weight redistribution failed: {e}")
        # Never raise - return original weights as fallback
        return weights.copy()


def _extract_dimension_scores(runs: list[dict[str, Any]]) -> dict[str, list[float]]:
    """
    Extract per-dimension drift scores from runs.

    Note: This assumes runs have already been fingerprinted and compared.
    For baseline calibration, we need historical dimension scores.
    If not available, we compute them from raw metrics.
    """
    dimension_scores = {dim: [] for dim in DIMENSION_KEYS}

    try:
        import numpy as np
    except ImportError:
        logger.warning("numpy not available - calibration requires [analyze] extra")
        return dimension_scores

    for run in runs:
        try:
            if "tool_sequence" in run and run["tool_sequence"]:
                tool_seq_str = run.get("tool_sequence", "[]")
                if isinstance(tool_seq_str, str):
                    tools = json.loads(tool_seq_str)
                    if tools:
                        dimension_scores["decision_drift"].append(0.0)
                        dimension_scores["tool_sequence"].append(0.0)
                        dimension_scores["tool_distribution"].append(0.0)

            latency = run.get("latency_ms", 0)
            if latency > 0:
                normalized_latency = min(1.0, latency / 5000.0)
                dimension_scores["latency"].append(normalized_latency)

            error_count = run.get("error_count", 0)
            dimension_scores["error_rate"].append(min(1.0, error_count / 10.0))

            loop_count = run.get("loop_count", 0)
            dimension_scores["loop_depth"].append(min(1.0, loop_count / 20.0))

            verbosity_ratio = run.get("verbosity_ratio", 0.0)
            dimension_scores["verbosity_ratio"].append(min(1.0, verbosity_ratio))

            retry_count = run.get("retry_count", 0)
            dimension_scores["retry_rate"].append(min(1.0, retry_count / 5.0))

            output_length = run.get("output_length", 0)
            dimension_scores["output_length"].append(min(1.0, output_length / 10000.0))

            # time_to_first_tool: planning latency before first tool call
            time_to_first_tool = run.get("time_to_first_tool_ms", 0)
            normalized_ttft = min(1.0, time_to_first_tool / 5000.0)
            dimension_scores["time_to_first_tool"].append(normalized_ttft)

            # semantic_drift: will be extracted from semantic cluster distribution if available
            # For now, placeholder - actual semantic drift computed in diff.py from clusters
            dimension_scores["semantic_drift"].append(0.0)

            # tool_sequence_transitions: will be extracted from transition matrix if available
            # For now, placeholder - actual transitions computed separately
            dimension_scores["tool_sequence_transitions"].append(0.0)

        except Exception as e:
            logger.debug(f"Failed to extract dimension scores from run: {e}")
            continue

    return dimension_scores


def calibrate(
    baseline_version: str,
    eval_version: str,
    inferred_use_case: str,
    sensitivity: str = "standard",
    db_path: str | None = None,
    semantic_available: bool = True,
    transitions_available: bool = True,
) -> CalibrationResult:
    """
    Calibrate weights and thresholds from baseline statistics.

    Args:
        baseline_version: Baseline version identifier
        eval_version: Version being evaluated
        inferred_use_case: Use case from inference (determines preset weights)
        sensitivity: "strict" | "standard" | "relaxed"
        db_path: Optional database path

    Returns:
        CalibrationResult with calibrated parameters
    """
    try:
        import numpy as np
    except ImportError:
        logger.warning("numpy required for calibration - install driftbase[analyze]")
        return _default_calibration_result(
            inferred_use_case,
            semantic_available=semantic_available,
            transitions_available=transitions_available,
        )

    from driftbase.backends.factory import get_backend
    from driftbase.local.use_case_inference import USE_CASE_WEIGHTS

    try:
        backend = get_backend()

        cache_key = (
            f"{baseline_version}:{eval_version}:{inferred_use_case}:{sensitivity}"
        )
        cached = backend.get_calibration_cache(cache_key)

        if cached:
            baseline_runs = backend.get_runs(deployment_version=baseline_version)
            eval_runs = backend.get_runs(deployment_version=eval_version)

            baseline_n_current = len(baseline_runs)
            eval_n_current = len(eval_runs)

            cached_total_n = cached.get("run_count_at_calibration", 0)
            current_total_n = baseline_n_current + eval_n_current

            if current_total_n < cached_total_n * 1.20:
                return CalibrationResult(
                    calibrated_weights=cached["calibrated_weights"],
                    thresholds=cached["thresholds"],
                    composite_thresholds=cached["composite_thresholds"],
                    calibration_method=cached["calibration_method"],
                    baseline_n=cached["baseline_n"],
                    reliability_multipliers=cached.get("reliability_multipliers", {}),
                    inferred_use_case=inferred_use_case,
                    confidence=cached.get("confidence", 0.0),
                )

        baseline_runs = backend.get_runs(deployment_version=baseline_version)

        if len(baseline_runs) < 30:
            logger.info(
                f"Insufficient baseline data (n={len(baseline_runs)}). "
                f"Using preset weights. Calibration activates at 30+ runs."
            )
            result = _preset_calibration_result(
                inferred_use_case,
                len(baseline_runs),
                semantic_available=semantic_available,
                transitions_available=transitions_available,
            )

            backend.set_calibration_cache(
                cache_key,
                {
                    "calibrated_weights": result.calibrated_weights,
                    "thresholds": result.thresholds,
                    "composite_thresholds": result.composite_thresholds,
                    "calibration_method": result.calibration_method,
                    "baseline_n": result.baseline_n,
                    "reliability_multipliers": result.reliability_multipliers,
                    "confidence": result.confidence,
                    "run_count_at_calibration": len(baseline_runs),
                },
            )

            return result

        dimension_scores = _extract_dimension_scores(baseline_runs)

        stats = {}
        reliability_multipliers = {}

        for dim, scores in dimension_scores.items():
            if not scores:
                stats[dim] = {"mean": 0.0, "std": 0.01, "cv": 0.0}
                reliability_multipliers[dim] = 1.0
                continue

            mean = float(np.mean(scores))
            std = float(np.std(scores))

            if std == 0.0:
                std = 0.01

            cv = std / mean if mean > 0 else 0.0
            reliability_multiplier = 1.0 / (1.0 + cv)

            stats[dim] = {"mean": mean, "std": std, "cv": cv}
            reliability_multipliers[dim] = reliability_multiplier

        preset_weights = USE_CASE_WEIGHTS.get(
            inferred_use_case, USE_CASE_WEIGHTS["GENERAL"]
        )

        raw_calibrated = {}
        for dim in DIMENSION_KEYS:
            preset_weight = preset_weights.get(dim, 0.111)
            reliability_mult = reliability_multipliers.get(dim, 1.0)
            raw_calibrated[dim] = preset_weight * reliability_mult

        total = sum(raw_calibrated.values())
        if total > 0:
            calibrated_weights = {dim: w / total for dim, w in raw_calibrated.items()}
        else:
            calibrated_weights = preset_weights

        # Redistribute weights if conditional dimensions are unavailable
        unavailable_dims = []
        if not semantic_available:
            unavailable_dims.append("semantic_drift")
        if not transitions_available:
            unavailable_dims.append("tool_sequence_transitions")

        if unavailable_dims:
            calibrated_weights = _redistribute_weights(
                calibrated_weights, unavailable_dims
            )

        per_dimension_thresholds = {}
        for dim in DIMENSION_KEYS:
            mean = stats[dim]["mean"]
            std = stats[dim]["std"]

            per_dimension_thresholds[dim] = {
                "MONITOR": mean + 2.0 * std,
                "REVIEW": mean + 3.0 * std,
                "BLOCK": mean + 4.0 * std,
            }

        composite_thresholds = {}
        for level in ["MONITOR", "REVIEW", "BLOCK"]:
            weighted_sum = 0.0
            for dim in DIMENSION_KEYS:
                dim_threshold = per_dimension_thresholds[dim][level]
                weight = calibrated_weights.get(dim, 0.0)
                weighted_sum += dim_threshold * weight
            composite_thresholds[level] = weighted_sum

        eval_runs = backend.get_runs(deployment_version=eval_version)
        eval_n = len(eval_runs)
        volume_mult = _volume_multiplier(eval_n)

        for level in composite_thresholds:
            composite_thresholds[level] *= volume_mult

        for dim in per_dimension_thresholds:
            for level in per_dimension_thresholds[dim]:
                per_dimension_thresholds[dim][level] *= volume_mult

        sensitivity_mult = SENSITIVITY_MULTIPLIERS.get(sensitivity, 1.0)

        for level in composite_thresholds:
            composite_thresholds[level] *= sensitivity_mult

        for dim in per_dimension_thresholds:
            for level in per_dimension_thresholds[dim]:
                per_dimension_thresholds[dim][level] *= sensitivity_mult

        result = CalibrationResult(
            calibrated_weights=calibrated_weights,
            thresholds=per_dimension_thresholds,
            composite_thresholds=composite_thresholds,
            calibration_method="statistical",
            baseline_n=len(baseline_runs),
            reliability_multipliers=reliability_multipliers,
            inferred_use_case=inferred_use_case,
            confidence=1.0,
        )

        backend.set_calibration_cache(
            cache_key,
            {
                "calibrated_weights": result.calibrated_weights,
                "thresholds": result.thresholds,
                "composite_thresholds": result.composite_thresholds,
                "calibration_method": result.calibration_method,
                "baseline_n": result.baseline_n,
                "reliability_multipliers": result.reliability_multipliers,
                "confidence": result.confidence,
                "run_count_at_calibration": len(baseline_runs) + eval_n,
            },
        )

        return result

    except Exception as e:
        logger.debug(f"Calibration failed: {e}")
        return _default_calibration_result(inferred_use_case)


def _preset_calibration_result(
    use_case: str,
    baseline_n: int,
    semantic_available: bool = True,
    transitions_available: bool = True,
) -> CalibrationResult:
    """Return calibration using preset weights only (no statistical adjustment)."""
    from driftbase.local.use_case_inference import USE_CASE_WEIGHTS

    preset_weights = USE_CASE_WEIGHTS.get(use_case, USE_CASE_WEIGHTS["GENERAL"])

    # Redistribute if conditional dimensions unavailable
    unavailable_dims = []
    if not semantic_available:
        unavailable_dims.append("semantic_drift")
    if not transitions_available:
        unavailable_dims.append("tool_sequence_transitions")

    if unavailable_dims:
        preset_weights = _redistribute_weights(preset_weights, unavailable_dims)

    per_dimension_thresholds = {}
    for dim in DIMENSION_KEYS:
        per_dimension_thresholds[dim] = DEFAULT_THRESHOLDS.copy()

    return CalibrationResult(
        calibrated_weights=preset_weights,
        thresholds=per_dimension_thresholds,
        composite_thresholds=DEFAULT_THRESHOLDS.copy(),
        calibration_method="preset_only",
        baseline_n=baseline_n,
        reliability_multipliers=dict.fromkeys(DIMENSION_KEYS, 1.0),
        inferred_use_case=use_case,
        confidence=0.5,
    )


def _default_calibration_result(
    use_case: str,
    semantic_available: bool = True,
    transitions_available: bool = True,
) -> CalibrationResult:
    """Return default calibration (fallback on any error)."""
    from driftbase.local.use_case_inference import USE_CASE_WEIGHTS

    general_weights = USE_CASE_WEIGHTS["GENERAL"].copy()

    # Redistribute if conditional dimensions unavailable
    unavailable_dims = []
    if not semantic_available:
        unavailable_dims.append("semantic_drift")
    if not transitions_available:
        unavailable_dims.append("tool_sequence_transitions")

    if unavailable_dims:
        general_weights = _redistribute_weights(general_weights, unavailable_dims)

    per_dimension_thresholds = {}
    for dim in DIMENSION_KEYS:
        per_dimension_thresholds[dim] = DEFAULT_THRESHOLDS.copy()

    return CalibrationResult(
        calibrated_weights=general_weights,
        thresholds=per_dimension_thresholds,
        composite_thresholds=DEFAULT_THRESHOLDS.copy(),
        calibration_method="default",
        baseline_n=0,
        reliability_multipliers=dict.fromkeys(DIMENSION_KEYS, 1.0),
        inferred_use_case=use_case,
        confidence=0.0,
    )
