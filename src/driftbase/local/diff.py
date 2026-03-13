import json
import math
import os
from typing import TYPE_CHECKING, Any

# Load from env, default to 50 for production safety
MIN_SAMPLES = int(os.getenv("DRIFTBASE_PRODUCTION_MIN_SAMPLES", "50"))

if TYPE_CHECKING:
    from driftbase.local.local_store import BehavioralFingerprint, DriftReport


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
        penalty = (math.log(min_samples) - math.log(sample_size)) / math.log(min_samples)
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

    base_sem = json.loads(getattr(baseline, "semantic_cluster_distribution", "{}") or "{}")
    curr_sem = json.loads(getattr(current, "semantic_cluster_distribution", "{}") or "{}")
    semantic_drift = _jensen_shannon_divergence(base_sem, curr_sem)

    base_p95 = max(baseline.p95_latency_ms, 1)
    latency_delta_raw = abs(current.p95_latency_ms - baseline.p95_latency_ms) / base_p95
    latency_drift = min(1.0, latency_delta_raw)

    error_delta_raw = abs(current.error_rate - baseline.error_rate)
    error_drift = min(1.0, error_delta_raw * 2.0)

    base_out = max(baseline.avg_output_length, 1.0)
    output_delta_raw = abs(current.avg_output_length - baseline.avg_output_length) / base_out
    output_drift = min(1.0, output_delta_raw)

    sigma_latency = _sigmoid_contribution(latency_delta_raw, k=2.0, c=1.0)
    sigma_errors = _sigmoid_contribution(error_drift, k=4.0, c=0.3)
    sigma_output = _sigmoid_contribution(output_drift, k=3.0, c=0.3)
    sigma_semantic = _sigmoid_contribution(semantic_drift, k=4.0, c=0.3)

    w_jsd = 0.55
    w_latency = 0.15
    w_errors = 0.15
    w_semantic = 0.10
    w_output = 0.05
    drift_score = (
        w_jsd * decision_drift
        + w_latency * sigma_latency
        + w_errors * sigma_errors
        + w_semantic * sigma_semantic
        + w_output * sigma_output
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

    from driftbase.local.fingerprinter import build_fingerprint_from_runs
    from driftbase.local.local_store import DriftReport, run_dict_to_agent_run

    base_dist = json.loads(baseline.tool_sequence_distribution)
    curr_dist = json.loads(current.tool_sequence_distribution)
    decision_drift = _jensen_shannon_divergence(base_dist, curr_dist)

    base_sem = json.loads(getattr(baseline, "semantic_cluster_distribution", "{}") or "{}")
    curr_sem = json.loads(getattr(current, "semantic_cluster_distribution", "{}") or "{}")
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
    output_delta_raw = abs(current.avg_output_length - baseline.avg_output_length) / base_out
    output_drift = min(1.0, output_delta_raw)

    sigma_latency = _sigmoid_contribution(latency_delta_raw, k=2.0, c=1.0)
    sigma_errors = _sigmoid_contribution(error_drift, k=4.0, c=0.3)
    sigma_output = _sigmoid_contribution(output_drift, k=3.0, c=0.3)
    sigma_semantic = _sigmoid_contribution(semantic_drift, k=4.0, c=0.3)

    w_jsd = 0.55
    w_latency = 0.15
    w_errors = 0.15
    w_semantic = 0.10
    w_output = 0.05
    drift_score = (
        w_jsd * decision_drift
        + w_latency * sigma_latency
        + w_errors * sigma_errors
        + w_semantic * sigma_semantic
        + w_output * sigma_output
    )
    drift_score = min(1.0, max(0.0, drift_score))
    if decision_drift > 0.30:
        drift_score = max(drift_score, 0.15)

    sample_size = min(baseline.sample_count, current.sample_count)
    severity = classify_severity(drift_score, sample_size)

    # Extract context values for before→after display
    baseline_dominant_tool = _get_dominant_tool(base_dist)
    current_dominant_tool = _get_dominant_tool(curr_dist)

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
    )

    # Bootstrap 95% CI when run lists are provided
    n_bootstrap = 500
    max_bootstrap_n = 200

    if baseline_runs is not None and current_runs is not None and len(baseline_runs) > 0 and len(current_runs) > 0:
        report.sample_size_warning = min(len(baseline_runs), len(current_runs)) < 30
        report.confidence_interval_pct = 95
        report.bootstrap_iterations = n_bootstrap

        baseline_agents = [run_dict_to_agent_run(d) for d in baseline_runs]
        current_agents = [run_dict_to_agent_run(d) for d in current_runs]

        # Cap for bootstrap performance
        if len(baseline_agents) > max_bootstrap_n:
            rng = np.random.default_rng(42)
            baseline_agents = list(rng.choice(baseline_agents, size=max_bootstrap_n, replace=False))
        if len(current_agents) > max_bootstrap_n:
            rng = np.random.default_rng(43)
            current_agents = list(rng.choice(current_agents, size=max_bootstrap_n, replace=False))

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