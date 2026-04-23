"""
Structured verdict payload for CI/CD integration.

Converts DriftReport into clean, documented JSON for programmatic consumption.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from driftbase.output.evidence import generate_evidence

if TYPE_CHECKING:
    from driftbase.backends.base import StorageBackend
    from driftbase.local.local_store import DriftReport

logger = logging.getLogger(__name__)


def build_verdict_payload(
    report: DriftReport,
    backend: StorageBackend | None = None,
) -> dict[str, Any]:
    """
    Build structured verdict payload from DriftReport.

    Args:
        report: DriftReport from compute_drift()
        backend: Optional backend for rollback target lookup

    Returns:
        Dict with clean, documented structure for CI/CD consumption

    Payload structure:
        {
            "version": "1.0",
            "verdict": "REVIEW" | "SHIP" | "MONITOR" | "BLOCK" | null,
            "composite_score": 0.61,
            "confidence_tier": "TIER3",
            "confidence": {"ci_lower": 0.52, "ci_upper": 0.70},
            "top_contributors": [
                {
                    "dimension": "decision_drift",
                    "observed": 0.41,
                    "ci_lower": 0.33,
                    "ci_upper": 0.49,
                    "significant": true,
                    "contribution_pct": 43.2,
                    "evidence": "Tool path '[search, write]' went from 3% to 27%"
                }
            ],
            "rollback_target": "v1.2.3" | null,
            "power_forecast": {"message": "...", "runs_needed": {...}} | null,
            "mdes": {"decision_drift": 0.08, ...},
            "sample_sizes": {"baseline": 200, "current": 150},
            "thresholds": {"monitor": 0.15, "review": 0.30, "block": 0.60}
        }
    """
    try:
        # Extract verdict from report
        # Verdict can come from anomaly override or severity mapping
        verdict_str = _extract_verdict(report)

        # Build confidence interval
        confidence = {
            "ci_lower": report.drift_score_lower,
            "ci_upper": report.drift_score_upper,
        }

        # Build top contributors (top 3 by attribution)
        top_contributors = _build_top_contributors(report)

        # Rollback target
        rollback_target = None
        if backend is not None and verdict_str in ["REVIEW", "BLOCK"]:
            rollback_target = _find_rollback_target(
                backend, report.environment or "production"
            )

        # Power forecast (TIER1/TIER2 only)
        power_forecast = None
        if report.confidence_tier in ["TIER1", "TIER2"]:
            power_forecast = _build_power_forecast(report)

        # MDEs
        mdes = report.dimension_mdes or {}

        # Sample sizes
        sample_sizes = {
            "baseline": report.baseline_n,
            "current": report.eval_n,
        }

        # Thresholds
        thresholds = report.composite_thresholds or {
            "monitor": 0.15,
            "review": 0.30,
            "block": 0.60,
        }

        return {
            "version": "1.0",
            "verdict": verdict_str,
            "composite_score": round(report.drift_score, 4),
            "confidence_tier": report.confidence_tier,
            "confidence": confidence,
            "top_contributors": top_contributors,
            "rollback_target": rollback_target,
            "power_forecast": power_forecast,
            "mdes": mdes,
            "sample_sizes": sample_sizes,
            "thresholds": thresholds,
        }

    except Exception as e:
        logger.warning(f"Failed to build verdict payload: {e}")
        # Minimal fallback payload
        return {
            "version": "1.0",
            "verdict": None,
            "composite_score": getattr(report, "drift_score", 0.0),
            "confidence_tier": getattr(report, "confidence_tier", "TIER1"),
            "error": str(e),
        }


def _extract_verdict(report: DriftReport) -> str | None:
    """Extract verdict string from report severity."""
    severity_to_verdict = {
        "none": "SHIP",
        "low": "SHIP",
        "moderate": "MONITOR",
        "significant": "REVIEW",
        "critical": "BLOCK",
    }
    return severity_to_verdict.get(report.severity)


def _build_top_contributors(report: DriftReport) -> list[dict[str, Any]]:
    """Build top 3 contributors with evidence."""
    try:
        # Get attribution scores
        attribution = report.dimension_attribution or {}
        if not attribution:
            return []

        # Get dimension CIs
        dimension_cis = report.dimension_cis or {}

        # Get dimension scores from report
        dimension_scores = {
            "decision_drift": report.decision_drift,
            "semantic_drift": report.semantic_drift,
            "latency": report.latency_drift,
            "error_rate": report.error_drift,
            "tool_distribution": report.decision_drift,
            "verbosity_ratio": report.verbosity_drift,
            "loop_depth": report.loop_depth_drift,
            "output_length": report.output_length_drift,
            "tool_sequence": report.tool_sequence_drift,
            "retry_rate": report.retry_drift,
            "time_to_first_tool": report.planning_latency_drift,
            "tool_sequence_transitions": report.tool_sequence_transitions_drift,
        }

        # Sort by attribution (absolute value, descending)
        sorted_dims = sorted(attribution.items(), key=lambda x: abs(x[1]), reverse=True)

        # Take top 3
        top_3 = sorted_dims[:3]

        contributors = []
        total_attribution = sum(abs(v) for v in attribution.values())

        for dim, attr_value in top_3:
            observed = dimension_scores.get(dim, 0.0)

            # Get CI bounds
            ci = dimension_cis.get(dim)
            if ci is not None:
                ci_lower = getattr(ci, "ci_lower", observed)
                ci_upper = getattr(ci, "ci_upper", observed)
                significant = getattr(ci, "significant", False)
            else:
                ci_lower = observed
                ci_upper = observed
                significant = False

            # Contribution percentage
            contribution_pct = 0.0
            if total_attribution > 0:
                contribution_pct = (abs(attr_value) / total_attribution) * 100

            # Generate evidence (requires fingerprints)
            # We need to get them from somewhere - for now, use generic fallback
            evidence = f"Observed drift of {observed:.3f}"

            # Try to get more specific evidence if we have access to report context
            # For now, generic evidence based on dimension name and observed value
            if dim == "decision_drift" and observed > 0.1:
                evidence = f"Tool sequence patterns shifted (drift: {observed:.2f})"
            elif dim == "latency" and observed > 0.1:
                evidence = f"Latency changed significantly (drift: {observed:.2f})"
            elif dim == "error_rate" and observed > 0.1:
                evidence = f"Error rate changed (drift: {observed:.2f})"

            contributors.append(
                {
                    "dimension": dim,
                    "observed": round(observed, 4),
                    "ci_lower": round(ci_lower, 4),
                    "ci_upper": round(ci_upper, 4),
                    "significant": significant,
                    "contribution_pct": round(contribution_pct, 1),
                    "evidence": evidence,
                }
            )

        return contributors

    except Exception as e:
        logger.warning(f"Failed to build top contributors: {e}")
        return []


def _find_rollback_target(backend: StorageBackend, environment: str) -> str | None:
    """Find the most recent SHIP verdict for rollback."""
    try:
        verdicts = backend.list_verdicts(limit=50)
        for v in verdicts:
            if v.get("environment") == environment and v.get("verdict") in [
                "SHIP",
                None,
            ]:
                return v.get("current_version") or v.get("baseline_version")
        return None
    except Exception as e:
        logger.debug(f"Failed to find rollback target: {e}")
        return None


def _build_power_forecast(report: DriftReport) -> dict[str, Any] | None:
    """Build power forecast message for TIER1/TIER2."""
    try:
        runs_needed = report.runs_needed_forecast or {}
        if not runs_needed:
            return None

        # Find the dimension needing the most runs
        max_runs = max(runs_needed.values()) if runs_needed else 0

        if max_runs <= 0:
            message = "Sample size is sufficient for analysis"
        else:
            message = f"With {max_runs} more runs, statistical power will be sufficient"

        return {
            "message": message,
            "runs_needed": runs_needed,
        }

    except Exception as e:
        logger.debug(f"Failed to build power forecast: {e}")
        return None
