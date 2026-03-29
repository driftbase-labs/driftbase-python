import json
import math
import os
from typing import TYPE_CHECKING, Any

# Load from env, default to 50 for production safety
MIN_SAMPLES = int(os.getenv("DRIFTBASE_PRODUCTION_MIN_SAMPLES", "50"))

if TYPE_CHECKING:
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
    try:
        import numpy as np
    except ImportError:
        raise ImportError(
            "numpy is required for drift computation with confidence intervals. "
            "Install with: pip install 'driftbase[analyze]'"
        )

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

    sigma_latency = _sigmoid_contribution(latency_delta_raw, k=2.0, c=1.0)
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

    # Tool sequence transitions drift: transitions between different tool pairs
    # TODO: Compute from transition matrix when available
    # For now, use decision_drift as proxy (similar to tool_sequence_drift)
    tool_sequence_transitions_drift = decision_drift

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
        baseline_n=calibration.baseline_n,
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
    )

    # Bootstrap 95% CI when run lists are provided
    n_bootstrap = 500
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
        if len(baseline_agents) > max_bootstrap_n:
            rng = np.random.default_rng(42)
            baseline_agents = list(
                rng.choice(baseline_agents, size=max_bootstrap_n, replace=False)
            )
        if len(current_agents) > max_bootstrap_n:
            rng = np.random.default_rng(43)
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

        rng = np.random.default_rng(0)
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

    return report
