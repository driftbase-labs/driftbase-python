"""
Baseline calibration: measures dimension variance, derives statistical thresholds.

Computes reliability-adjusted weights and per-dimension thresholds from baseline runs.
Applies volume and sensitivity multipliers. Caches results to avoid recomputation.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
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
    # Blend metadata
    keyword_use_case: str = "GENERAL"
    keyword_confidence: float = 0.0
    behavioral_use_case: str = "GENERAL"
    behavioral_confidence: float = 0.0
    blend_method: str = "general_fallback"
    behavioral_signals: dict[str, float] | None = None
    # Learned weights metadata
    learned_weights_available: bool = False
    learned_weights_n: int = 0
    top_predictors: list[str] | None = None
    # Correlation adjustment metadata
    correlated_pairs: list[tuple[str, str, float]] = field(default_factory=list)
    correlation_adjusted: bool = False


def _volume_multiplier(run_count: int) -> float:
    """Return threshold multiplier based on run count (tighten for higher volume)."""
    for threshold, multiplier in VOLUME_MULTIPLIERS:
        if threshold is None or run_count < threshold:
            return multiplier
    return 1.00


def _compute_threshold(
    mean: float, std: float, n: int, sigma_multiplier: float
) -> float:
    """
    Compute a threshold using t-distribution for small samples.

    For n >= 100: behaves like mean + sigma_multiplier * std (normal distribution)
    For n < 100:  widens the threshold to account for estimation uncertainty

    Uses the t-distribution's percent point function (inverse CDF) to find
    the value at the equivalent tail probability.

    Args:
        mean: Sample mean
        std: Sample standard deviation
        n: Sample size (baseline run count)
        sigma_multiplier: Standard deviation multiplier (2.0, 3.0, or 4.0)

    Returns:
        Threshold value
    """
    try:
        if std <= 0.01:
            std = 0.01

        df = max(1, n - 1)

        SIGMA_TO_PROBABILITY = {
            2.0: 0.9772,
            3.0: 0.9987,
            4.0: 0.99997,
        }
        probability = SIGMA_TO_PROBABILITY.get(sigma_multiplier)
        if probability is None:
            from scipy.stats import norm

            probability = norm.cdf(sigma_multiplier)

        from scipy.stats import t as t_dist

        t_multiplier = t_dist.ppf(probability, df=df)

        return mean + t_multiplier * std
    except Exception as e:
        logger.debug(
            f"t-distribution threshold computation failed: {e}, falling back to normal"
        )
        return mean + sigma_multiplier * std


def _compute_correlation_adjustments(
    dimension_scores: dict[str, list[float]],
    weights: dict[str, float],
) -> tuple[dict[str, float], list[tuple[str, str, float]]]:
    """
    Compute weight adjustments to reduce double-counting of correlated dimensions.

    Common correlations (empirically observed):
    - latency ↔ retry_rate (timeouts cause retries)
    - loop_depth ↔ error_rate (loops often end in errors)
    - loop_depth ↔ retry_rate (retry loops increase depth)
    - latency ↔ loop_depth (more loops = more latency)
    - output_length ↔ verbosity_ratio (longer output = higher ratio)

    For each pair with correlation > 0.7:
    - Identify less important dimension (lower weight)
    - Reduce its weight by: correlation * 0.5 (max 50% reduction)
    - More important dimension keeps full weight

    Args:
        dimension_scores: Dict of dimension name → list of scores from baseline runs
        weights: Current weights (after reliability multipliers)

    Returns:
        (adjustment_factors, correlated_pairs)
        - adjustment_factors: Dict of multiplicative factors (< 1.0 = reduced)
        - correlated_pairs: List of (dim_a, dim_b, correlation) tuples

    Never raises. Returns all 1.0 factors on any failure.
    Requires minimum 30 data points per dimension.
    """
    try:
        import numpy as np
        from scipy.stats import spearmanr
    except ImportError:
        logger.debug("scipy/numpy not available for correlation adjustment")
        return dict.fromkeys(weights, 1.0), []

    try:
        dimensions = list(weights.keys())
        n = min(len(v) for v in dimension_scores.values()) if dimension_scores else 0

        if n < 30:
            return dict.fromkeys(dimensions, 1.0), []

        CORRELATION_THRESHOLD = 0.70
        MAX_REDUCTION = 0.50

        adjustment_factors = dict.fromkeys(dimensions, 1.0)
        correlated_pairs = []

        score_matrix = np.array(
            [dimension_scores.get(dim, [0.0] * n)[:n] for dim in dimensions]
        )

        for i, dim_a in enumerate(dimensions):
            for j, dim_b in enumerate(dimensions):
                if j <= i:
                    continue

                scores_a = score_matrix[i]
                scores_b = score_matrix[j]

                if np.std(scores_a) < 1e-9 or np.std(scores_b) < 1e-9:
                    continue

                corr, pvalue = spearmanr(scores_a, scores_b)

                if abs(corr) < CORRELATION_THRESHOLD:
                    continue

                if corr < 0:
                    continue

                correlated_pairs.append((dim_a, dim_b, float(corr)))

                weight_a = weights.get(dim_a, 0.0)
                weight_b = weights.get(dim_b, 0.0)

                if weight_a <= weight_b:
                    less_important = dim_a
                else:
                    less_important = dim_b

                reduction = min(MAX_REDUCTION, corr * 0.5)
                adjustment_factors[less_important] = min(
                    adjustment_factors[less_important], 1.0 - reduction
                )

        return adjustment_factors, correlated_pairs

    except Exception as e:
        logger.debug(f"Correlation adjustment failed: {e}")
        return dict.fromkeys(weights, 1.0), []


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
    preset_weights: dict[str, float] | None = None,
    keyword_use_case: str = "GENERAL",
    keyword_confidence: float = 0.0,
    behavioral_use_case: str = "GENERAL",
    behavioral_confidence: float = 0.0,
    blend_method: str = "general_fallback",
    behavioral_signals: dict[str, float] | None = None,
    agent_id: str | None = None,
) -> CalibrationResult:
    """
    Calibrate weights and thresholds from baseline statistics.

    Args:
        baseline_version: Baseline version identifier
        eval_version: Version being evaluated
        inferred_use_case: Use case from inference (determines preset weights)
        sensitivity: "strict" | "standard" | "relaxed"
        db_path: Optional database path
        preset_weights: Optional pre-blended weights (bypasses USE_CASE_WEIGHTS lookup)
        keyword_use_case: Keyword inference result
        keyword_confidence: Keyword confidence
        behavioral_use_case: Behavioral inference result
        behavioral_confidence: Behavioral confidence
        blend_method: How weights were blended
        behavioral_signals: Extracted behavioral signals
        agent_id: Optional agent ID for learned weights lookup

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
                    keyword_use_case=keyword_use_case,
                    keyword_confidence=keyword_confidence,
                    behavioral_use_case=behavioral_use_case,
                    behavioral_confidence=behavioral_confidence,
                    blend_method=blend_method,
                    behavioral_signals=behavioral_signals,
                    correlated_pairs=cached.get("correlated_pairs", []),
                    correlation_adjusted=cached.get("correlation_adjusted", False),
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
                    "correlated_pairs": result.correlated_pairs,
                    "correlation_adjusted": result.correlation_adjusted,
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

        # Use provided preset_weights if available, otherwise lookup from use case
        base_weights = preset_weights or USE_CASE_WEIGHTS.get(
            inferred_use_case, USE_CASE_WEIGHTS["GENERAL"]
        )

        raw_calibrated = {}
        for dim in DIMENSION_KEYS:
            base_weight = base_weights.get(dim, 0.111)
            reliability_mult = reliability_multipliers.get(dim, 1.0)
            raw_calibrated[dim] = base_weight * reliability_mult

        total = sum(raw_calibrated.values())
        if total > 0:
            reliability_adjusted_weights = {
                dim: w / total for dim, w in raw_calibrated.items()
            }
        else:
            reliability_adjusted_weights = base_weights

        # Apply correlation adjustment to reduce double-counting
        corr_adjustments, correlated_pairs = _compute_correlation_adjustments(
            dimension_scores,
            reliability_adjusted_weights,
        )
        correlation_adjusted = len(correlated_pairs) > 0

        correlation_adjusted_weights = {
            dim: reliability_adjusted_weights[dim] * corr_adjustments[dim]
            for dim in reliability_adjusted_weights
        }

        # Renormalize after correlation adjustment
        total = sum(correlation_adjusted_weights.values())
        if total > 0:
            calibrated_weights = {
                dim: w / total for dim, w in correlation_adjusted_weights.items()
            }
        else:
            calibrated_weights = reliability_adjusted_weights

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

        # Load learned weights if available and blend with calibrated weights
        learned_weights_available = False
        learned_weights_n = 0
        top_predictors = []

        if agent_id:
            try:
                learned_cache = backend.get_learned_weights(agent_id)
                if learned_cache and learned_cache.get("n_total", 0) >= 10:
                    learned_weights_data = learned_cache.get("weights", {})
                    learned_metadata = learned_cache.get("metadata", {})
                    learned_factor = learned_metadata.get("learned_factor", 0.0)

                    # Blend learned weights on top of calibrated weights
                    final_weights = {}
                    for dim in DIMENSION_KEYS:
                        learned_w = learned_weights_data.get(dim, 0.0)
                        calibrated_w = calibrated_weights.get(dim, 0.0)
                        final_weights[dim] = (
                            learned_factor * learned_w
                            + (1 - learned_factor) * calibrated_w
                        )

                    # Renormalize
                    total = sum(final_weights.values())
                    if total > 0:
                        calibrated_weights = {
                            dim: w / total for dim, w in final_weights.items()
                        }

                    learned_weights_available = True
                    learned_weights_n = learned_cache.get("n_total", 0)
                    top_predictors = learned_metadata.get("top_predictors", [])
            except Exception as e:
                logger.debug(f"Failed to load learned weights: {e}")

        per_dimension_thresholds = {}
        n = len(baseline_runs)
        for dim in DIMENSION_KEYS:
            mean = stats[dim]["mean"]
            std = stats[dim]["std"]

            per_dimension_thresholds[dim] = {
                "MONITOR": _compute_threshold(mean, std, n, 2.0),
                "REVIEW": _compute_threshold(mean, std, n, 3.0),
                "BLOCK": _compute_threshold(mean, std, n, 4.0),
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

        calibration_method_final = (
            "learned" if learned_weights_available else "statistical"
        )

        result = CalibrationResult(
            calibrated_weights=calibrated_weights,
            thresholds=per_dimension_thresholds,
            composite_thresholds=composite_thresholds,
            calibration_method=calibration_method_final,
            baseline_n=len(baseline_runs),
            reliability_multipliers=reliability_multipliers,
            inferred_use_case=inferred_use_case,
            confidence=1.0,
            keyword_use_case=keyword_use_case,
            keyword_confidence=keyword_confidence,
            behavioral_use_case=behavioral_use_case,
            behavioral_confidence=behavioral_confidence,
            blend_method=blend_method,
            behavioral_signals=behavioral_signals,
            learned_weights_available=learned_weights_available,
            learned_weights_n=learned_weights_n,
            top_predictors=top_predictors or [],
            correlated_pairs=correlated_pairs or [],
            correlation_adjusted=correlation_adjusted,
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
                "correlated_pairs": result.correlated_pairs,
                "correlation_adjusted": result.correlation_adjusted,
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
        correlated_pairs=[],
        correlation_adjusted=False,
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
        correlated_pairs=[],
        correlation_adjusted=False,
    )
