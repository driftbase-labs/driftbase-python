"""
Evidence generation for drift dimensions.

Converts fingerprint data into human-readable explanations of what changed.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from driftbase.local.local_store import BehavioralFingerprint

logger = logging.getLogger(__name__)


def generate_evidence(
    dimension: str,
    baseline_fp: BehavioralFingerprint,
    current_fp: BehavioralFingerprint,
    baseline_runs: list[dict[str, Any]] | None = None,
    current_runs: list[dict[str, Any]] | None = None,
) -> str:
    """
    Generate human-readable evidence for what changed in a dimension.

    Args:
        dimension: Dimension name (e.g. "decision_drift", "latency")
        baseline_fp: Baseline fingerprint
        current_fp: Current fingerprint
        baseline_runs: Optional baseline run dicts (unused currently)
        current_runs: Optional current run dicts (unused currently)

    Returns:
        Single-sentence explanation of what changed, or fallback generic message

    Examples:
        decision_drift: "Tool path '[search, write]' went from 3.2% to 27.1% of runs"
        latency: "P95 latency increased from 1,240ms to 2,890ms (+133%)"
        error_rate: "Error rate increased from 2.1% to 8.4% (+6.3pp)"
    """
    try:
        # Decision drift / tool sequence drift / tool sequence transitions
        if dimension in [
            "decision_drift",
            "tool_sequence",
            "tool_sequence_drift",
            "tool_sequence_transitions",
            "tool_sequence_transitions_drift",
            "tool_distribution",
        ]:
            return _evidence_decision_drift(baseline_fp, current_fp)

        # Latency drift
        if dimension in ["latency", "latency_drift"]:
            return _evidence_latency(baseline_fp, current_fp)

        # Planning latency (time to first tool)
        if dimension in [
            "time_to_first_tool",
            "planning_latency_drift",
            "planning_latency",
        ]:
            return _evidence_planning_latency(baseline_fp, current_fp)

        # Error drift
        if dimension in ["error_rate", "error_drift", "error"]:
            return _evidence_error_rate(baseline_fp, current_fp)

        # Semantic drift
        if dimension in ["semantic_drift", "semantic"]:
            return _evidence_semantic_drift(baseline_fp, current_fp)

        # Verbosity / output drift
        if dimension in [
            "verbosity_ratio",
            "verbosity_drift",
            "verbosity",
            "output_drift",
            "output",
        ]:
            return _evidence_verbosity(baseline_fp, current_fp)

        # Output length
        if dimension in ["output_length", "output_length_drift"]:
            return _evidence_output_length(baseline_fp, current_fp)

        # Loop depth
        if dimension in ["loop_depth", "loop_depth_drift", "loop"]:
            return _evidence_loop_depth(baseline_fp, current_fp)

        # Retry rate
        if dimension in ["retry_rate", "retry_drift", "retry"]:
            return _evidence_retry_rate(baseline_fp, current_fp)

        # Fallback for unknown dimensions
        return f"Drift observed in {dimension}"

    except Exception as e:
        logger.debug(f"Failed to generate evidence for {dimension}: {e}")
        return f"Drift observed in {dimension}"


def _evidence_decision_drift(
    baseline_fp: BehavioralFingerprint, current_fp: BehavioralFingerprint
) -> str:
    """Generate evidence for decision/tool sequence drift."""
    try:
        base_dist = json.loads(baseline_fp.tool_sequence_distribution)
        curr_dist = json.loads(current_fp.tool_sequence_distribution)

        # Find the sequence with the largest absolute change in share
        all_seqs = set(base_dist.keys()) | set(curr_dist.keys())
        if not all_seqs:
            return "Tool sequence distribution changed"

        max_delta = 0.0
        max_seq = None
        baseline_pct = 0.0
        current_pct = 0.0

        for seq in all_seqs:
            base_share = base_dist.get(seq, 0.0)
            curr_share = curr_dist.get(seq, 0.0)
            delta = abs(curr_share - base_share)
            if delta > max_delta:
                max_delta = delta
                max_seq = seq
                baseline_pct = base_share * 100
                current_pct = curr_share * 100

        if max_seq is None:
            return "Tool sequence distribution changed"

        # Format the sequence for display
        try:
            seq_list = json.loads(max_seq) if isinstance(max_seq, str) else max_seq
            if isinstance(seq_list, list):
                seq_display = f"[{', '.join(seq_list)}]"
            else:
                seq_display = str(max_seq)
        except Exception:
            seq_display = str(max_seq)

        # If new sequence (not in baseline)
        if baseline_pct < 0.1:
            return f"New tool path {seq_display} appeared in {current_pct:.1f}% of runs"

        # If disappeared (not in current)
        if current_pct < 0.1:
            return (
                f"Tool path {seq_display} dropped from {baseline_pct:.1f}% to near 0%"
            )

        # Normal case
        direction = "increased" if current_pct > baseline_pct else "decreased"
        return f"Tool path {seq_display} {direction} from {baseline_pct:.1f}% to {current_pct:.1f}% of runs"

    except Exception as e:
        logger.debug(f"Failed to generate decision drift evidence: {e}")
        return "Tool sequence distribution changed"


def _evidence_latency(
    baseline_fp: BehavioralFingerprint, current_fp: BehavioralFingerprint
) -> str:
    """Generate evidence for latency drift."""
    try:
        base_p95 = baseline_fp.p95_latency_ms
        curr_p95 = current_fp.p95_latency_ms
        base_p50 = baseline_fp.p50_latency_ms
        curr_p50 = current_fp.p50_latency_ms

        if base_p95 == 0:
            return f"P95 latency changed to {curr_p95:,}ms"

        delta_p95 = curr_p95 - base_p95
        pct_change = (delta_p95 / base_p95) * 100

        direction = "increased" if delta_p95 > 0 else "decreased"
        sign = "+" if delta_p95 > 0 else ""

        # If both p50 and p95 moved significantly
        if base_p50 > 0:
            delta_p50 = curr_p50 - base_p50
            pct_p50 = abs(delta_p50 / base_p50) * 100
            if pct_p50 > 10:  # More than 10% change in p50
                return (
                    f"Median latency {direction} from {base_p50:,}ms to {curr_p50:,}ms; "
                    f"P95 from {base_p95:,}ms to {curr_p95:,}ms"
                )

        return f"P95 latency {direction} from {base_p95:,}ms to {curr_p95:,}ms ({sign}{pct_change:+.0f}%)"

    except Exception as e:
        logger.debug(f"Failed to generate latency evidence: {e}")
        return "Latency changed"


def _evidence_planning_latency(
    baseline_fp: BehavioralFingerprint, current_fp: BehavioralFingerprint
) -> str:
    """Generate evidence for planning latency (time to first tool)."""
    try:
        base_planning = baseline_fp.avg_time_to_first_tool_ms
        curr_planning = current_fp.avg_time_to_first_tool_ms

        if base_planning == 0:
            return f"Time to first tool changed to {curr_planning:,}ms"

        delta = curr_planning - base_planning
        pct_change = (delta / base_planning) * 100

        direction = "increased" if delta > 0 else "decreased"
        sign = "+" if delta > 0 else ""

        return f"Time to first tool {direction} from {base_planning:,}ms to {curr_planning:,}ms ({sign}{pct_change:+.0f}%)"

    except Exception as e:
        logger.debug(f"Failed to generate planning latency evidence: {e}")
        return "Time to first tool changed"


def _evidence_error_rate(
    baseline_fp: BehavioralFingerprint, current_fp: BehavioralFingerprint
) -> str:
    """Generate evidence for error rate drift."""
    try:
        base_rate = baseline_fp.error_rate * 100
        curr_rate = current_fp.error_rate * 100
        delta = curr_rate - base_rate

        direction = "increased" if delta > 0 else "decreased"
        sign = "+" if delta > 0 else ""

        return f"Error rate {direction} from {base_rate:.1f}% to {curr_rate:.1f}% ({sign}{delta:.1f}pp)"

    except Exception as e:
        logger.debug(f"Failed to generate error rate evidence: {e}")
        return "Error rate changed"


def _evidence_semantic_drift(
    baseline_fp: BehavioralFingerprint, current_fp: BehavioralFingerprint
) -> str:
    """Generate evidence for semantic cluster drift."""
    try:
        base_dist = json.loads(baseline_fp.semantic_cluster_distribution or "{}")
        curr_dist = json.loads(current_fp.semantic_cluster_distribution or "{}")

        # Find the cluster with the largest absolute change
        all_clusters = set(base_dist.keys()) | set(curr_dist.keys())
        if not all_clusters:
            return "Semantic cluster distribution changed"

        max_delta = 0.0
        max_cluster = None
        baseline_pct = 0.0
        current_pct = 0.0

        for cluster in all_clusters:
            base_share = base_dist.get(cluster, 0.0)
            curr_share = curr_dist.get(cluster, 0.0)
            delta = abs(curr_share - base_share)
            if delta > max_delta:
                max_delta = delta
                max_cluster = cluster
                baseline_pct = base_share * 100
                current_pct = curr_share * 100

        if max_cluster is None:
            return "Semantic cluster distribution changed"

        direction = "grew" if current_pct > baseline_pct else "shrank"
        return f"Semantic cluster '{max_cluster}' {direction} from {baseline_pct:.1f}% to {current_pct:.1f}% of outcomes"

    except Exception as e:
        logger.debug(f"Failed to generate semantic drift evidence: {e}")
        return "Semantic cluster distribution changed"


def _evidence_verbosity(
    baseline_fp: BehavioralFingerprint, current_fp: BehavioralFingerprint
) -> str:
    """Generate evidence for verbosity ratio drift."""
    try:
        base_verbosity = baseline_fp.avg_verbosity_ratio
        curr_verbosity = current_fp.avg_verbosity_ratio

        if base_verbosity == 0:
            return f"Verbosity ratio changed to {curr_verbosity:.2f}"

        delta = curr_verbosity - base_verbosity
        pct_change = (delta / base_verbosity) * 100

        direction = "increased" if delta > 0 else "decreased"
        sign = "+" if delta > 0 else ""

        return f"Verbosity ratio {direction} from {base_verbosity:.2f} to {curr_verbosity:.2f} ({sign}{pct_change:+.0f}%)"

    except Exception as e:
        logger.debug(f"Failed to generate verbosity evidence: {e}")
        return "Verbosity changed"


def _evidence_output_length(
    baseline_fp: BehavioralFingerprint, current_fp: BehavioralFingerprint
) -> str:
    """Generate evidence for output length drift."""
    try:
        base_length = baseline_fp.avg_output_length
        curr_length = current_fp.avg_output_length

        if base_length == 0:
            return f"Average output length changed to {curr_length:,.0f} chars"

        delta = curr_length - base_length
        pct_change = (delta / base_length) * 100

        direction = "increased" if delta > 0 else "decreased"
        sign = "+" if delta > 0 else ""

        return f"Average output length {direction} from {base_length:,.0f} to {curr_length:,.0f} chars ({sign}{pct_change:+.0f}%)"

    except Exception as e:
        logger.debug(f"Failed to generate output length evidence: {e}")
        return "Output length changed"


def _evidence_loop_depth(
    baseline_fp: BehavioralFingerprint, current_fp: BehavioralFingerprint
) -> str:
    """Generate evidence for loop depth drift."""
    try:
        base_loop = baseline_fp.avg_loop_count
        curr_loop = current_fp.avg_loop_count

        if base_loop == 0:
            return f"Average loop depth changed to {curr_loop:.1f} iterations"

        delta = curr_loop - base_loop
        pct_change = (delta / base_loop) * 100

        direction = "increased" if delta > 0 else "decreased"
        sign = "+" if delta > 0 else ""

        return f"Average loop depth {direction} from {base_loop:.1f} to {curr_loop:.1f} iterations ({sign}{pct_change:+.0f}%)"

    except Exception as e:
        logger.debug(f"Failed to generate loop depth evidence: {e}")
        return "Loop depth changed"


def _evidence_retry_rate(
    baseline_fp: BehavioralFingerprint, current_fp: BehavioralFingerprint
) -> str:
    """Generate evidence for retry rate drift."""
    try:
        base_retry = baseline_fp.avg_retry_count
        curr_retry = current_fp.avg_retry_count

        # Convert to rate (avg retries per run)
        base_rate = base_retry * 100
        curr_rate = curr_retry * 100

        delta = curr_rate - base_rate
        direction = "increased" if delta > 0 else "decreased"
        sign = "+" if delta > 0 else ""

        return f"Retry rate {direction} from {base_rate:.1f}% to {curr_rate:.1f}% of runs ({sign}{delta:.1f}pp)"

    except Exception as e:
        logger.debug(f"Failed to generate retry rate evidence: {e}")
        return "Retry rate changed"
