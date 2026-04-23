import json
import logging
import math
import os
from typing import TYPE_CHECKING, Any

from driftbase.local.task_clustering import compute_per_cluster_drift
from driftbase.stats.emd import compute_latency_emd_signal
from driftbase.stats.ngrams import compute_bigram_jsd

# Load from env, default to 50 for production safety
MIN_SAMPLES = int(os.getenv("DRIFTBASE_PRODUCTION_MIN_SAMPLES", "50"))

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from driftbase.backends.base import StorageBackend
    from driftbase.local.local_store import BehavioralFingerprint, DriftReport


def _extract_tool_names(runs: list[dict[str, Any]]) -> list[str]:
    """Extract unique tool names from runs for use case inference."""
    tool_names = set()
    for run in runs:
        try:
            tool_seq = run.get("tool_sequence", "[]")
            if isinstance(tool_seq, str):
                tools = json.loads(tool_seq)
                if isinstance(tools, list):
                    tool_names.update(str(t) for t in tools if t)
        except Exception:
            continue
    return list(tool_names)


def _jensen_shannon_divergence(p: dict[str, float], q: dict[str, float]) -> float:
    """Compute Jensen-Shannon divergence between two probability distributions.

    Returns a value in [0, 1]. 0 = identical, 1 = disjoint support.
    JSD(P||Q) = 0.5*KL(P||M) + 0.5*KL(Q||M) with M = (P+Q)/2.
    """
    if not p and not q:
        return 0.0
    if not p or not q:
        return 1.0
    keys = set(p) | set(q)
    m: dict[str, float] = {}
    for k in keys:
        m[k] = (p.get(k, 0.0) + q.get(k, 0.0)) / 2.0
    js = 0.0
    for k in keys:
        pi = p.get(k, 0.0)
        qi = q.get(k, 0.0)
        mi = m[k]
        if pi > 0 and mi > 0:
            js += pi * math.log(pi / mi)
        if qi > 0 and mi > 0:
            js += qi * math.log(qi / mi)
    js *= 0.5
    # Normalize to [0, 1]; max JSD with natural log is ln(2)
    return min(1.0, max(0.0, js) / math.log(2))


def _sigmoid(x: float, k: float = 2.0, c: float = 0.5) -> float:
    """Bounded sigmoid: 1 / (1 + exp(-k*(x - c))). Maps real x to (0, 1)."""
    return 1.0 / (1.0 + math.exp(-k * (x - c)))


def _sigmoid_contribution(x: float, k: float, c: float) -> float:
    """Sigmoid contribution normalized so 0 input → 0 contribution (for use in weighted sum).
    Returns (sigmoid(x) - sigmoid(0)) / (1 - sigmoid(0)), clamped to [0, 1].
    """
    if x <= 0:
        return 0.0
    s0 = _sigmoid(0.0, k=k, c=c)
    s = _sigmoid(x, k=k, c=c)
    denom = 1.0 - s0
    if denom <= 0:
        return 0.0
    return min(1.0, max(0.0, (s - s0) / denom))


def _threshold_multiplier(sample_size: int, min_samples: int = MIN_SAMPLES) -> float:
    """
    Scales threshold up for small sample sizes to prevent false positive alerts.
    """
    if sample_size >= min_samples:
        return 1.0

    # Logarithmic scaling to soften the penalty as N approaches min_samples
    try:
        penalty = (math.log(min_samples) - math.log(sample_size)) / math.log(
            min_samples
        )
        return 1.0 + penalty
    except ValueError:
        return 2.0  # Fallback for edge cases like N=0 or 1


def _get_dominant_tool(tool_dist: dict[str, float]) -> str:
    """Get the most frequently used tool from a distribution."""
    if not tool_dist:
        return ""
    return max(tool_dist.items(), key=lambda x: x[1])[0]


def _classify_severity(drift_score: float, threshold_multiplier: float = 1.0) -> str:
    """Classify severity from drift score using a given threshold multiplier."""
    critical_threshold = 0.50 * threshold_multiplier
    significant_threshold = 0.35 * threshold_multiplier
    moderate_threshold = 0.20 * threshold_multiplier
    low_threshold = 0.10 * threshold_multiplier

    if drift_score >= critical_threshold:
        return "critical"
    if drift_score >= significant_threshold:
        return "significant"
    if drift_score >= moderate_threshold:
        return "moderate"
    if drift_score >= low_threshold:
        return "low"
    return "none"


def classify_severity(drift_score: float, sample_size: int) -> str:
    multiplier = _threshold_multiplier(sample_size)
    return _classify_severity(drift_score, threshold_multiplier=multiplier)


def compute_dimension_significance(
    baseline_runs: list,
    eval_runs: list,
    min_runs_per_dimension: dict[str, int],
) -> dict[str, str]:
    """
    For each dimension, determine its significance status:
        "reliable"    — n >= min_runs for this dimension
        "indicative"  — n >= 15 but < min_runs for this dimension
        "insufficient" — n < 15

    Returns: {dim: status}
    Never raises.
    """
    baseline_n = len(baseline_runs or [])
    eval_n = len(eval_runs or [])
    min_n = min(baseline_n, eval_n)

    statuses = {}
    for dim, min_runs in min_runs_per_dimension.items():
        if min_n < 15:
            statuses[dim] = "insufficient"
        elif min_n < min_runs:
            statuses[dim] = "indicative"
        else:
            statuses[dim] = "reliable"

    return statuses


def get_confidence_tier(baseline_n: int, eval_n: int, min_runs_needed: int = 50) -> str:
    """
    Determine confidence tier based on sample sizes.

    Args:
        baseline_n: Number of baseline runs
        eval_n: Number of eval runs
        min_runs_needed: Minimum runs from power analysis (default 50)

    Returns: "TIER1" | "TIER2" | "TIER3"
    """
    from driftbase.config import get_settings

    settings = get_settings()
    tier1_min = settings.TIER1_MIN_RUNS

    min_n = min(baseline_n, eval_n)

    if min_n < tier1_min:
        return "TIER1"
    elif min_n < min_runs_needed:
        return "TIER2"
    else:
        return "TIER3"


def compute_indicative_signal(
    baseline: "BehavioralFingerprint",
    current: "BehavioralFingerprint",
) -> dict[str, str]:
    """
    Compute directional signals for Tier 2 (15 ≤ n < 50).

    Returns dict mapping dimension to signal: "↑" | "↓" | "→"
    Only shows signals for dimensions with meaningful changes (>10% relative).
    """
    import json

    signals = {}

    # Decision drift (tool sequence distribution)
    base_dist = json.loads(baseline.tool_sequence_distribution)
    curr_dist = json.loads(current.tool_sequence_distribution)
    jsd = _jensen_shannon_divergence(base_dist, curr_dist)
    if jsd > 0.10:
        signals["decision_patterns"] = "↑" if jsd > 0.20 else "→"

    # Latency drift
    base_p95 = max(baseline.p95_latency_ms, 1)
    curr_p95 = current.p95_latency_ms
    latency_delta = (curr_p95 - base_p95) / base_p95
    if abs(latency_delta) > 0.10:
        signals["latency"] = "↑" if latency_delta > 0 else "↓"

    # Error rate drift
    error_delta = current.error_rate - baseline.error_rate
    if abs(error_delta) > 0.05:  # 5% absolute change
        signals["error_rate"] = "↑" if error_delta > 0 else "↓"

    # Verbosity drift
    baseline_verbosity = getattr(baseline, "avg_verbosity_ratio", 0.0)
    current_verbosity = getattr(current, "avg_verbosity_ratio", 0.0)
    if baseline_verbosity > 0:
        verbosity_delta = (current_verbosity - baseline_verbosity) / baseline_verbosity
        if abs(verbosity_delta) > 0.15:  # 15% relative change
            signals["verbosity"] = "↑" if verbosity_delta > 0 else "↓"

    # Loop depth drift
    baseline_loop = getattr(baseline, "p95_loop_count", 0.0)
    current_loop = getattr(current, "p95_loop_count", 0.0)
    if baseline_loop > 0:
        loop_delta = (current_loop - baseline_loop) / baseline_loop
        if abs(loop_delta) > 0.20:  # 20% relative change
            signals["reasoning_depth"] = "↑" if loop_delta > 0 else "↓"

    # Semantic drift (outcome patterns)
    base_sem = json.loads(
        getattr(baseline, "semantic_cluster_distribution", "{}") or "{}"
    )
    curr_sem = json.loads(
        getattr(current, "semantic_cluster_distribution", "{}") or "{}"
    )
    if base_sem and curr_sem:
        sem_jsd = _jensen_shannon_divergence(base_sem, curr_sem)
        if sem_jsd > 0.10:
            signals["outcome_patterns"] = "↑" if sem_jsd > 0.20 else "→"

    return signals


def _compute_drift_score(
    baseline: "BehavioralFingerprint",
    current: "BehavioralFingerprint",
) -> float:
    """Compute the overall drift score (0–1) between two fingerprints. Used for point estimate and bootstrap."""
    base_dist = json.loads(baseline.tool_sequence_distribution)
    curr_dist = json.loads(current.tool_sequence_distribution)
    decision_drift = _jensen_shannon_divergence(base_dist, curr_dist)

    base_sem = json.loads(
        getattr(baseline, "semantic_cluster_distribution", "{}") or "{}"
    )
    curr_sem = json.loads(
        getattr(current, "semantic_cluster_distribution", "{}") or "{}"
    )
    semantic_drift = _jensen_shannon_divergence(base_sem, curr_sem)

    base_p95 = max(baseline.p95_latency_ms, 1)
    latency_delta_raw = abs(current.p95_latency_ms - baseline.p95_latency_ms) / base_p95
    min(1.0, latency_delta_raw)

    error_delta_raw = abs(current.error_rate - baseline.error_rate)
    error_drift = min(1.0, error_delta_raw * 2.0)

    base_out = max(baseline.avg_output_length, 1.0)
    output_delta_raw = (
        abs(current.avg_output_length - baseline.avg_output_length) / base_out
    )
    output_drift = min(1.0, output_delta_raw)

    sigma_latency = _sigmoid_contribution(latency_delta_raw, k=2.0, c=1.0)
    sigma_errors = _sigmoid_contribution(error_drift, k=4.0, c=0.3)
    sigma_output = _sigmoid_contribution(output_drift, k=3.0, c=0.3)
    sigma_semantic = _sigmoid_contribution(semantic_drift, k=4.0, c=0.3)

    # New behavioral drift dimensions (same as in compute_drift)
    baseline_verbosity = getattr(baseline, "avg_verbosity_ratio", 0.0)
    current_verbosity = getattr(current, "avg_verbosity_ratio", 0.0)
    verbosity_delta = abs(current_verbosity - baseline_verbosity)
    verbosity_drift = _sigmoid_contribution(verbosity_delta, k=3.0, c=0.3)

    baseline_p95_loop = getattr(baseline, "p95_loop_count", 0.0)
    current_p95_loop = getattr(current, "p95_loop_count", 0.0)
    loop_delta = abs(current_p95_loop - baseline_p95_loop) / max(baseline_p95_loop, 1.0)
    sigma_loop = _sigmoid_contribution(loop_delta, k=2.5, c=0.4)

    baseline_out_len = getattr(
        baseline, "avg_output_length", baseline.avg_output_length
    )
    current_out_len = getattr(current, "avg_output_length", current.avg_output_length)
    out_len_delta = abs(current_out_len - baseline_out_len) / max(baseline_out_len, 1.0)
    sigma_out_len = _sigmoid_contribution(out_len_delta, k=2.0, c=0.4)

    baseline_retry = getattr(baseline, "avg_retry_count", baseline.retry_rate)
    current_retry = getattr(current, "avg_retry_count", current.retry_rate)
    retry_delta = abs(current_retry - baseline_retry)
    sigma_retry = _sigmoid_contribution(retry_delta, k=4.0, c=0.2)

    # Rebalanced weights (same as in compute_drift)
    w_jsd = 0.40
    w_latency = 0.12
    w_errors = 0.12
    w_semantic = 0.08
    w_output = 0.04
    w_verbosity = 0.06
    w_loop = 0.06
    w_out_len = 0.04
    w_tool_seq = 0.04
    w_retry = 0.04

    drift_score = (
        w_jsd * decision_drift
        + w_latency * sigma_latency
        + w_errors * sigma_errors
        + w_semantic * sigma_semantic
        + w_output * sigma_output
        + w_verbosity * verbosity_drift
        + w_loop * sigma_loop
        + w_out_len * sigma_out_len
        + w_tool_seq * decision_drift  # tool_sequence_drift uses decision_drift
        + w_retry * sigma_retry
    )
    drift_score = min(1.0, max(0.0, drift_score))
    if decision_drift > 0.30:
        drift_score = max(drift_score, 0.15)
    return drift_score


def compute_drift(
    baseline: "BehavioralFingerprint",
    current: "BehavioralFingerprint",
    baseline_runs: list[dict[str, Any]] | None = None,
    current_runs: list[dict[str, Any]] | None = None,
    sensitivity: str | None = None,
    backend: "StorageBackend | None" = None,
    compute_statistics: bool = True,
) -> "DriftReport":
    """Compute a drift report between two behavioral fingerprints.

    Total score is a weighted sum so one dimension cannot max out the result.
    If baseline_runs and current_runs are provided, a 500-iteration bootstrap is run
    to set drift_score_lower and drift_score_upper (95% CI).

    Args:
        baseline: Baseline fingerprint.
        current: Current fingerprint to compare.
        baseline_runs: Optional list of run dicts for bootstrap (uses full set for point estimate).
        current_runs: Optional list of run dicts for bootstrap.

    Returns:
        DriftReport with drift_score, severity, component drifts, and optional CI fields.
    """
    import numpy as np

    from driftbase.config import get_settings
    from driftbase.local.anomaly_detector import compute_anomaly_signal
    from driftbase.local.baseline_calibrator import calibrate
    from driftbase.local.fingerprinter import build_fingerprint_from_runs
    from driftbase.local.local_store import DriftReport, run_dict_to_agent_run
    from driftbase.local.use_case_inference import (
        blend_inferences,
        infer_use_case,
        infer_use_case_from_behavior,
    )

    # Calibration: infer use case from keywords + behavior, then blend
    all_runs = (baseline_runs or []) + (current_runs or [])
    tool_names = []
    if all_runs:
        tool_names = _extract_tool_names(all_runs)

    keyword_result = infer_use_case(tool_names)
    behavioral_result = infer_use_case_from_behavior(all_runs)
    blend_result = blend_inferences(keyword_result, behavioral_result)

    baseline_version = baseline.deployment_version or "unknown"
    current_version = current.deployment_version or "unknown"

    settings = get_settings()
    effective_sensitivity = sensitivity or settings.DRIFTBASE_SENSITIVITY

    # Log effective configuration
    logger.info(
        f"compute_drift: fingerprint_limit={settings.DRIFTBASE_FINGERPRINT_LIMIT}, "
        f"bootstrap_iters={settings.DRIFTBASE_BOOTSTRAP_ITERS}, sensitivity={effective_sensitivity}"
    )

    # Compute power analysis and minimum runs needed
    baseline_n = baseline.sample_count
    eval_n = current.sample_count
    min_n = min(baseline_n, eval_n)

    # Default values for power analysis
    min_runs_needed = 50
    power_analysis_used = False
    min_runs_per_dimension = {}
    limiting_dim = ""

    # Extract agent_id for caching (use session_id from runs)
    agent_id = ""
    if baseline_runs:
        agent_id = baseline_runs[0].get("session_id", "")
    elif current_runs:
        agent_id = current_runs[0].get("session_id", "")

    # Try to load cached threshold first
    cached_threshold = None
    if agent_id and backend:
        try:
            if hasattr(backend, "get_significance_threshold"):
                cached_threshold = backend.get_significance_threshold(
                    agent_id, baseline_version
                )
        except Exception:
            pass

    # Check if we should recompute (baseline_n has grown by > 20% since last computation)
    should_recompute = False
    if cached_threshold:
        baseline_n_at_computation = cached_threshold.get("baseline_n_at_computation", 0)
        if (
            baseline_n_at_computation > 0
            and baseline_n > baseline_n_at_computation * 1.20
        ):
            should_recompute = True
    else:
        should_recompute = True

    # Compute or use cached power analysis
    if should_recompute and baseline_runs and len(baseline_runs) >= 10:
        try:
            from driftbase.local.baseline_calibrator import (
                _extract_dimension_scores,
                compute_min_runs_needed,
            )

            baseline_dimension_scores = _extract_dimension_scores(baseline_runs)
            power_result = compute_min_runs_needed(
                baseline_dimension_scores=baseline_dimension_scores,
                use_case=blend_result["use_case"],
            )

            min_runs_needed = power_result["overall"]
            min_runs_per_dimension = power_result["per_dimension"]
            limiting_dim = power_result["limiting_dimension"]
            power_analysis_used = True

            # Store the computed threshold
            if (
                agent_id
                and backend
                and hasattr(backend, "write_significance_threshold")
            ):
                try:
                    threshold_data = {
                        "use_case": blend_result["use_case"],
                        "effect_size": power_result.get("effect_size", 0.10),
                        "overall": min_runs_needed,
                        "per_dimension": min_runs_per_dimension,
                        "limiting_dimension": limiting_dim,
                        "baseline_n_at_computation": baseline_n,
                    }
                    backend.write_significance_threshold(
                        agent_id, baseline_version, threshold_data
                    )
                except Exception:
                    pass
        except Exception:
            # Fall back to default
            min_runs_needed = 50
            power_analysis_used = False
    elif cached_threshold:
        # Use cached threshold
        min_runs_needed = cached_threshold.get("overall", 50)
        min_runs_per_dimension = cached_threshold.get("per_dimension", {})
        limiting_dim = cached_threshold.get("limiting_dimension", "")
        power_analysis_used = True

    # Compute dimension significance if we have power analysis
    dimension_significance = {}
    reliable_dimension_count = 0
    partial_tier3 = False

    if power_analysis_used and min_runs_per_dimension:
        dimension_significance = compute_dimension_significance(
            baseline_runs or [],
            current_runs or [],
            min_runs_per_dimension,
        )
        reliable_dimension_count = sum(
            1 for s in dimension_significance.values() if s == "reliable"
        )

        # Check for partial TIER3 (8+ dimensions reliable AND n >= 80% of min_runs_needed)
        if (
            reliable_dimension_count >= 8
            and min_n < min_runs_needed
            and min_n >= 0.8 * min_runs_needed
        ):
            partial_tier3 = True

    total_dimension_count = 12
    significance_pct = (
        reliable_dimension_count / total_dimension_count
        if total_dimension_count > 0
        else 0.0
    )

    # Check confidence tier based on sample sizes and power analysis
    limiting_version = "baseline" if baseline_n < eval_n else "eval"

    # Use adaptive tier determination
    tier = get_confidence_tier(baseline_n, eval_n, min_runs_needed)

    # Override to TIER3 if partial_tier3 is True
    if partial_tier3:
        tier = "TIER3"

    # Check version_source quality and apply warnings/downgrades (three-way distinction)
    version_warning = None
    tier_downgrade = False
    if baseline_runs and current_runs:
        # Count version sources in each fingerprint
        confident_sources = {"release", "tag", "env"}

        baseline_epoch_count = sum(
            1 for r in baseline_runs if r.get("version_source") == "epoch"
        )
        baseline_unknown_count = sum(
            1 for r in baseline_runs if r.get("version_source") == "unknown"
        )
        baseline_confident_count = sum(
            1 for r in baseline_runs if r.get("version_source") in confident_sources
        )

        current_epoch_count = sum(
            1 for r in current_runs if r.get("version_source") == "epoch"
        )
        current_unknown_count = sum(
            1 for r in current_runs if r.get("version_source") == "unknown"
        )
        current_confident_count = sum(
            1 for r in current_runs if r.get("version_source") in confident_sources
        )

        baseline_epoch_pct = baseline_epoch_count / len(baseline_runs)
        current_epoch_pct = current_epoch_count / len(current_runs)
        baseline_unknown_pct = baseline_unknown_count / len(baseline_runs)
        current_unknown_pct = current_unknown_count / len(current_runs)

        # Strongest applicable warning wins: epoch > unknown > none
        if baseline_epoch_pct > 0.5 or current_epoch_pct > 0.5:
            # Epoch-dominant: loud warning + tier downgrade
            version_warning = (
                "Comparing time-bucketed versions. Versions were resolved from timestamps, not explicit tags. "
                "Results may not reflect real deployment drift. Tag your deployments with Langfuse release field "
                "or DRIFTBASE_VERSION for accurate diffs."
            )
            logger.warning(f"Epoch-resolved versions detected: {version_warning}")
            tier_downgrade = True

            # Downgrade tier: TIER3 → TIER2, TIER2 → TIER1
            if tier == "TIER3":
                tier = "TIER2"
            elif tier == "TIER2":
                tier = "TIER1"
        elif baseline_unknown_pct > 0.5 or current_unknown_pct > 0.5:
            # Unknown-dominant: soft advisory, no tier downgrade
            version_warning = "Some runs predate version-source tracking. Re-sync from Langfuse to improve diff confidence."
            logger.info(f"Unknown version sources detected: {version_warning}")

    # TIER1: Insufficient data - return minimal report with progress bars only
    if tier == "TIER1":
        tier1_min = settings.TIER1_MIN_RUNS
        runs_needed = tier1_min - min_n
        warnings = []
        if version_warning:
            warnings.append(version_warning)
        return DriftReport(
            baseline_fingerprint_id=baseline.id,
            current_fingerprint_id=current.id,
            drift_score=0.0,
            severity="none",
            confidence_tier="TIER1",
            baseline_n=baseline_n,
            eval_n=eval_n,
            runs_needed=runs_needed,
            limiting_version=limiting_version,
            baseline_version=baseline_version,
            eval_version=current_version,
            min_runs_needed=min_runs_needed,
            power_analysis_used=power_analysis_used,
            warnings=warnings,
        )

    # TIER2: Indicative signals only - no numeric scores, no verdict
    if tier == "TIER2":
        # Compute indicative directional signals
        indicative_signal = compute_indicative_signal(baseline, current)
        runs_needed = min_runs_needed - min_n

        warnings = []
        if version_warning:
            warnings.append(version_warning)

        return DriftReport(
            baseline_fingerprint_id=baseline.id,
            current_fingerprint_id=current.id,
            drift_score=0.0,
            severity="none",
            confidence_tier="TIER2",
            baseline_n=baseline_n,
            eval_n=eval_n,
            indicative_signal=indicative_signal,
            runs_needed=runs_needed,
            limiting_version=limiting_version,
            baseline_version=baseline_version,
            eval_version=current_version,
            min_runs_needed=min_runs_needed,
            min_runs_per_dimension=min_runs_per_dimension,
            dimension_significance=dimension_significance,
            reliable_dimension_count=reliable_dimension_count,
            total_dimension_count=total_dimension_count,
            significance_pct=significance_pct,
            power_analysis_used=power_analysis_used,
            limiting_dimension=limiting_dim,
            warnings=warnings,
        )

    # TIER3: Full analysis (existing behavior)

    # Detect semantic data availability
    base_sem_check = json.loads(
        getattr(baseline, "semantic_cluster_distribution", "{}") or "{}"
    )
    curr_sem_check = json.loads(
        getattr(current, "semantic_cluster_distribution", "{}") or "{}"
    )
    semantic_available = bool(base_sem_check and curr_sem_check)

    # Detect transition matrix availability
    # TODO: Check backend for transition matrix data when available
    transitions_available = False

    # Extract agent_id for learned weights lookup
    agent_id = None
    if baseline_runs:
        agent_id = baseline_runs[0].get("session_id")
    elif current_runs:
        agent_id = current_runs[0].get("session_id")

    calibration = calibrate(
        baseline_version=baseline_version,
        eval_version=current_version,
        inferred_use_case=blend_result["use_case"],
        sensitivity=effective_sensitivity,
        semantic_available=semantic_available,
        transitions_available=transitions_available,
        preset_weights=blend_result["blended_weights"],
        keyword_use_case=blend_result["keyword_use_case"],
        keyword_confidence=blend_result["keyword_confidence"],
        behavioral_use_case=blend_result["behavioral_use_case"],
        behavioral_confidence=blend_result["behavioral_confidence"],
        blend_method=blend_result["blend_method"],
        behavioral_signals=blend_result["behavioral_signals"],
        agent_id=agent_id,
    )

    calibrated_weights = calibration.calibrated_weights

    # Apply feedback-driven weight adjustments (Phase 6)
    if backend is not None and agent_id:
        from driftbase.local.feedback_weights import apply_feedback_weights

        calibrated_weights = apply_feedback_weights(
            calibrated_weights, agent_id, backend
        )

    base_dist = json.loads(baseline.tool_sequence_distribution)
    curr_dist = json.loads(current.tool_sequence_distribution)
    decision_drift = _jensen_shannon_divergence(base_dist, curr_dist)

    base_sem = json.loads(
        getattr(baseline, "semantic_cluster_distribution", "{}") or "{}"
    )
    curr_sem = json.loads(
        getattr(current, "semantic_cluster_distribution", "{}") or "{}"
    )
    semantic_drift = _jensen_shannon_divergence(base_sem, curr_sem)
    escalation_base = base_sem.get("escalated", 0.0)
    escalation_curr = curr_sem.get("escalated", 0.0)
    escalation_rate_delta = escalation_curr - escalation_base

    base_p95 = max(baseline.p95_latency_ms, 1)
    latency_delta_raw = abs(current.p95_latency_ms - baseline.p95_latency_ms) / base_p95
    latency_drift = min(1.0, latency_delta_raw)

    error_delta_raw = abs(current.error_rate - baseline.error_rate)
    error_drift = min(1.0, error_delta_raw * 2.0)

    base_out = max(baseline.avg_output_length, 1.0)
    output_delta_raw = (
        abs(current.avg_output_length - baseline.avg_output_length) / base_out
    )
    output_drift = min(1.0, output_delta_raw)

    # Latency drift: blend p95 delta sigmoid with EMD distribution signal (50/50)
    sigma_latency_p95 = _sigmoid_contribution(latency_delta_raw, k=2.0, c=1.0)
    emd_signal = None
    if baseline_runs is not None and current_runs is not None:
        emd_signal = compute_latency_emd_signal(baseline_runs, current_runs)

    # When EMD unavailable, use full p95 signal; when available, blend 50/50
    if emd_signal is None:
        sigma_latency = sigma_latency_p95
    else:
        sigma_latency = 0.5 * sigma_latency_p95 + 0.5 * emd_signal
    sigma_errors = _sigmoid_contribution(error_drift, k=4.0, c=0.3)
    sigma_output = _sigmoid_contribution(output_drift, k=3.0, c=0.3)
    sigma_semantic = _sigmoid_contribution(semantic_drift, k=4.0, c=0.3)

    # New behavioral drift dimensions
    # Verbosity drift: absolute difference in avg_verbosity_ratio, normalized with sigmoid
    baseline_verbosity = getattr(baseline, "avg_verbosity_ratio", 0.0)
    current_verbosity = getattr(current, "avg_verbosity_ratio", 0.0)
    verbosity_delta = abs(current_verbosity - baseline_verbosity)
    verbosity_drift = _sigmoid_contribution(verbosity_delta, k=3.0, c=0.3)

    # Loop depth drift: JSD on loop_count distributions (using p95 as proxy)
    baseline_loop = getattr(baseline, "avg_loop_count", 0.0)
    current_loop = getattr(current, "avg_loop_count", 0.0)
    baseline_p95_loop = getattr(baseline, "p95_loop_count", 0.0)
    current_p95_loop = getattr(current, "p95_loop_count", 0.0)
    loop_delta = abs(current_p95_loop - baseline_p95_loop) / max(baseline_p95_loop, 1.0)
    loop_depth_drift = min(1.0, loop_delta)
    sigma_loop = _sigmoid_contribution(loop_delta, k=2.5, c=0.4)

    # Output length drift: normalized difference in avg_output_length
    baseline_out_len = getattr(
        baseline, "avg_output_length", baseline.avg_output_length
    )
    current_out_len = getattr(current, "avg_output_length", current.avg_output_length)
    out_len_delta = abs(current_out_len - baseline_out_len) / max(baseline_out_len, 1.0)
    output_length_drift = min(1.0, out_len_delta)
    sigma_out_len = _sigmoid_contribution(out_len_delta, k=2.0, c=0.4)

    # Tool sequence drift: JSD on tool_call_sequence distributions
    # tool_call_sequence is already captured as tool_sequence_distribution
    # This catches reordering of tools even when same tools are used
    tool_sequence_drift = decision_drift  # Already computed with JSD above

    # Retry drift: normalized difference in avg_retry_count
    baseline_retry = getattr(baseline, "avg_retry_count", baseline.retry_rate)
    current_retry = getattr(current, "avg_retry_count", current.retry_rate)
    retry_delta = abs(current_retry - baseline_retry)
    retry_drift = min(1.0, retry_delta * 2.0)
    sigma_retry = _sigmoid_contribution(retry_delta, k=4.0, c=0.2)

    # Planning latency drift: time to first tool call (thinking time before action)
    baseline_planning = getattr(baseline, "avg_time_to_first_tool_ms", 0.0)
    current_planning = getattr(current, "avg_time_to_first_tool_ms", 0.0)
    planning_delta = abs(current_planning - baseline_planning) / max(
        baseline_planning, 1.0
    )
    planning_latency_drift = min(1.0, planning_delta)
    sigma_planning = _sigmoid_contribution(planning_delta, k=2.0, c=0.5)

    # Tool sequence transitions drift: bigram-based transition detection
    baseline_bigram_dist = {}
    current_bigram_dist = {}
    baseline_bigram_json = getattr(baseline, "bigram_distribution", None)
    current_bigram_json = getattr(current, "bigram_distribution", None)
    if baseline_bigram_json:
        try:
            baseline_bigram_dist = json.loads(baseline_bigram_json)
        except (json.JSONDecodeError, TypeError):
            pass
    if current_bigram_json:
        try:
            current_bigram_dist = json.loads(current_bigram_json)
        except (json.JSONDecodeError, TypeError):
            pass
    tool_sequence_transitions_drift = compute_bigram_jsd(
        baseline_bigram_dist, current_bigram_dist
    )

    # Use calibrated weights (fallback to defaults if missing)
    w_jsd = calibrated_weights.get("decision_drift", 0.38)
    w_latency = calibrated_weights.get("latency", 0.12)
    w_errors = calibrated_weights.get("error_rate", 0.12)
    w_semantic = calibrated_weights.get("semantic_drift", 0.08)
    w_tool_dist = calibrated_weights.get("tool_distribution", 0.08)
    w_verbosity = calibrated_weights.get("verbosity_ratio", 0.06)
    w_loop = calibrated_weights.get("loop_depth", 0.06)
    w_out_len = calibrated_weights.get("output_length", 0.04)
    w_tool_seq = calibrated_weights.get("tool_sequence", 0.04)
    w_retry = calibrated_weights.get("retry_rate", 0.04)
    w_planning = calibrated_weights.get("time_to_first_tool", 0.02)
    w_tool_transitions = calibrated_weights.get("tool_sequence_transitions", 0.0)

    drift_score = (
        w_jsd * decision_drift
        + w_latency * sigma_latency
        + w_errors * sigma_errors
        + w_semantic * sigma_semantic
        + w_tool_dist * decision_drift  # tool_distribution uses decision_drift as proxy
        + w_verbosity * verbosity_drift
        + w_loop * sigma_loop
        + w_out_len * sigma_out_len
        + w_tool_seq * tool_sequence_drift
        + w_retry * sigma_retry
        + w_planning * sigma_planning
        + w_tool_transitions * tool_sequence_transitions_drift
    )
    drift_score = min(1.0, max(0.0, drift_score))
    if decision_drift > 0.30:
        drift_score = max(drift_score, 0.15)

    sample_size = min(baseline.sample_count, current.sample_count)
    severity = classify_severity(drift_score, sample_size)

    # Extract context values for before→after display
    baseline_dominant_tool = _get_dominant_tool(base_dist)
    current_dominant_tool = _get_dominant_tool(curr_dist)

    # Compute anomaly signal (supplementary multivariate detection)
    anomaly_signal = None
    if baseline_runs is not None and current_runs is not None:
        anomaly_signal = compute_anomaly_signal(
            baseline_runs=baseline_runs,
            eval_runs=current_runs,
        )

    # Compute per-cluster drift analysis
    cluster_analysis = None
    if baseline_runs is not None and current_runs is not None:
        cluster_results = compute_per_cluster_drift(
            baseline_runs=baseline_runs, current_runs=current_runs, max_clusters=5
        )
        cluster_analysis = cluster_results if cluster_results else None

    # Apply verdict override if anomaly is CRITICAL
    anomaly_override = False
    anomaly_override_reason = ""
    if anomaly_signal and anomaly_signal.level == "CRITICAL":
        if severity in ["none", "low"]:
            # SHIP → MONITOR
            severity = "moderate"
            anomaly_override = True
            anomaly_override_reason = "Overridden by multivariate anomaly signal"
        elif severity == "moderate":
            # MONITOR → REVIEW
            severity = "significant"
            anomaly_override = True
            anomaly_override_reason = "Escalated by multivariate anomaly signal"

    report = DriftReport(
        baseline_fingerprint_id=baseline.id,
        current_fingerprint_id=current.id,
        drift_score=drift_score,
        severity=severity,
        decision_drift=decision_drift,
        latency_drift=latency_drift,
        error_drift=error_drift,
        output_drift=output_drift,
        semantic_drift=semantic_drift,
        escalation_rate_delta=escalation_rate_delta,
        summary="",
        # Context values
        baseline_escalation_rate=escalation_base,
        current_escalation_rate=escalation_curr,
        baseline_p95_latency_ms=baseline.p95_latency_ms,
        current_p95_latency_ms=current.p95_latency_ms,
        baseline_error_rate=baseline.error_rate,
        current_error_rate=current.error_rate,
        baseline_dominant_tool=baseline_dominant_tool,
        current_dominant_tool=current_dominant_tool,
        # New behavioral drift dimensions
        verbosity_drift=verbosity_drift,
        loop_depth_drift=loop_depth_drift,
        output_length_drift=output_length_drift,
        tool_sequence_drift=tool_sequence_drift,
        retry_drift=retry_drift,
        planning_latency_drift=planning_latency_drift,
        tool_sequence_transitions_drift=tool_sequence_transitions_drift,
        # Context values for new dimensions
        baseline_avg_verbosity_ratio=baseline_verbosity,
        current_avg_verbosity_ratio=current_verbosity,
        baseline_avg_loop_count=baseline_loop,
        current_avg_loop_count=current_loop,
        baseline_avg_output_length=baseline_out_len,
        current_avg_output_length=current_out_len,
        baseline_avg_retry_count=baseline_retry,
        current_avg_retry_count=current_retry,
        baseline_avg_time_to_first_tool_ms=baseline_planning,
        current_avg_time_to_first_tool_ms=current_planning,
        # Calibration metadata
        inferred_use_case=blend_result["use_case"],
        use_case_confidence=max(
            blend_result["keyword_confidence"], blend_result["behavioral_confidence"]
        ),
        calibration_method=calibration.calibration_method,
        calibrated_weights=calibration.calibrated_weights,
        composite_thresholds=calibration.composite_thresholds,
        baseline_n=baseline_n,  # Actual fingerprint sample count (for tier logic)
        # Confidence tier metadata
        confidence_tier="TIER3",
        eval_n=eval_n,
        runs_needed=0,
        limiting_version="",
        baseline_version=baseline_version,
        eval_version=current_version,
        # Blend metadata
        blend_method=blend_result["blend_method"],
        behavioral_signals=blend_result["behavioral_signals"],
        # Learned weights metadata
        learned_weights_available=calibration.learned_weights_available,
        learned_weights_n=calibration.learned_weights_n,
        top_predictors=calibration.top_predictors,
        # Correlation adjustment metadata
        correlated_pairs=calibration.correlated_pairs,
        correlation_adjusted=calibration.correlation_adjusted,
        # Anomaly detection
        anomaly_signal=anomaly_signal,
        anomaly_override=anomaly_override,
        anomaly_override_reason=anomaly_override_reason,
        # Task clustering
        cluster_analysis=cluster_analysis,
        # Adaptive power analysis fields
        min_runs_needed=min_runs_needed,
        min_runs_per_dimension=min_runs_per_dimension,
        dimension_significance=dimension_significance,
        reliable_dimension_count=reliable_dimension_count,
        total_dimension_count=total_dimension_count,
        significance_pct=significance_pct,
        power_analysis_used=power_analysis_used,
        limiting_dimension=limiting_dim,
        partial_tier3=partial_tier3,
    )

    # Add epoch warnings if present
    if version_warning:
        report.warnings.append(version_warning)

    # Bootstrap 95% CI when run lists are provided
    from driftbase.utils.determinism import get_rng

    n_bootstrap = settings.DRIFTBASE_BOOTSTRAP_ITERS
    max_bootstrap_n = 200

    if (
        baseline_runs is not None
        and current_runs is not None
        and len(baseline_runs) > 0
        and len(current_runs) > 0
    ):
        report.sample_size_warning = min(len(baseline_runs), len(current_runs)) < 30
        report.confidence_interval_pct = 95
        report.bootstrap_iterations = n_bootstrap

        baseline_agents = [run_dict_to_agent_run(d) for d in baseline_runs]
        current_agents = [run_dict_to_agent_run(d) for d in current_runs]

        # Cap for bootstrap performance
        # Use fingerprint IDs as salt for reproducible sampling
        baseline_fp_id = baseline.id or "baseline"
        current_fp_id = current.id or "current"

        if len(baseline_agents) > max_bootstrap_n:
            rng = get_rng(f"sampling:baseline:{baseline_fp_id}")
            baseline_agents = list(
                rng.choice(baseline_agents, size=max_bootstrap_n, replace=False)
            )
        if len(current_agents) > max_bootstrap_n:
            rng = get_rng(f"sampling:current:{current_fp_id}")
            current_agents = list(
                rng.choice(current_agents, size=max_bootstrap_n, replace=False)
            )

        n_b, n_c = len(baseline_agents), len(current_agents)
        all_runs = baseline_agents + current_agents
        window_start = min(r.started_at for r in all_runs)
        window_end = max((r.completed_at or r.started_at) for r in all_runs)
        base_version = baseline.deployment_version or "unknown"
        curr_version = current.deployment_version or "unknown"
        base_env = getattr(baseline, "environment", "production") or "production"
        curr_env = getattr(current, "environment", "production") or "production"

        # Use fingerprint IDs as salt for bootstrap reproducibility
        bootstrap_salt = f"bootstrap:{baseline_fp_id}:{current_fp_id}"
        rng = get_rng(bootstrap_salt)
        scores: list[float] = []
        for _ in range(n_bootstrap):
            idx_b = rng.integers(0, n_b, size=n_b)
            idx_c = rng.integers(0, n_c, size=n_c)
            sample_b = [baseline_agents[i] for i in idx_b]
            sample_c = [current_agents[i] for i in idx_c]
            fp_b = build_fingerprint_from_runs(
                sample_b,
                window_start=window_start,
                window_end=window_end,
                deployment_version=base_version,
                environment=base_env,
            )
            fp_c = build_fingerprint_from_runs(
                sample_c,
                window_start=window_start,
                window_end=window_end,
                deployment_version=curr_version,
                environment=curr_env,
            )
            scores.append(_compute_drift_score(fp_b, fp_c))

        report.drift_score_lower = float(np.percentile(scores, 2.5))
        report.drift_score_upper = float(np.percentile(scores, 97.5))
        # Ensure point estimate lies within reported interval (CI can be slightly wider)
        report.drift_score_lower = min(report.drift_score_lower, report.drift_score)
        report.drift_score_upper = max(report.drift_score_upper, report.drift_score)
    else:
        report.drift_score_lower = report.drift_score
        report.drift_score_upper = report.drift_score
        report.sample_size_warning = sample_size < 30
        report.confidence_interval_pct = 95
        report.bootstrap_iterations = 0

    # Phase 3a: Statistical foundation
    if (
        compute_statistics
        and baseline_runs is not None
        and current_runs is not None
        and len(baseline_runs) > 0
        and len(current_runs) > 0
    ):
        from driftbase.stats.attribution import (
            compute_dimension_attribution,
            compute_marginal_contribution,
        )
        from driftbase.stats.dimension_ci import compute_dimension_cis
        from driftbase.stats.mde import compute_mde
        from driftbase.stats.power_forecast import forecast_runs_needed

        # All 12 drift dimensions
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

        # Collect dimension scores from report
        dimension_scores = {
            "decision_drift": report.decision_drift,
            "semantic_drift": report.semantic_drift,
            "latency": report.latency_drift,
            "error_rate": report.error_drift,
            "tool_distribution": report.decision_drift,  # proxy
            "verbosity_ratio": report.verbosity_drift,
            "loop_depth": report.loop_depth_drift,
            "output_length": report.output_length_drift,
            "tool_sequence": report.tool_sequence_drift,
            "retry_rate": report.retry_drift,
            "time_to_first_tool": report.planning_latency_drift,
            "tool_sequence_transitions": report.tool_sequence_transitions_drift,
        }

        # 1. Per-dimension confidence intervals
        dimension_cis = compute_dimension_cis(
            baseline_runs=baseline_runs,
            current_runs=current_runs,
            dimensions=all_dimensions,
            n_bootstrap=n_bootstrap,
            confidence_level=0.95,
            salt="dimension_ci",
        )
        report.dimension_cis = dimension_cis

        # 2. Minimum Detectable Effects
        dimension_mdes = compute_mde(
            baseline_runs=baseline_runs,
            current_runs=current_runs,
            dimensions=all_dimensions,
            alpha=0.05,
            power=0.80,
            n_bootstrap=n_bootstrap,
            salt="mde_estimation",
        )
        report.dimension_mdes = dimension_mdes

        # 3. Power forecast (runs needed for target MDE)
        runs_needed_forecast = forecast_runs_needed(
            baseline_runs=baseline_runs,
            current_runs=current_runs,
            dimensions=all_dimensions,
            target_mde=0.10,
            alpha=0.05,
            power=0.80,
            n_bootstrap=n_bootstrap,
            salt="power_forecast",
        )
        report.runs_needed_forecast = runs_needed_forecast

        # 4. Counterfactual attribution
        dimension_attribution = compute_dimension_attribution(
            baseline=baseline,
            current=current,
            calibrated_weights=calibrated_weights,
            original_composite=report.drift_score,
            dimension_scores=dimension_scores,
        )
        report.dimension_attribution = dimension_attribution

    return report
