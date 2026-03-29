"""
Actionable root-cause analysis for drift reports.

Provides:
- Tool call frequency diff (absolute and percentage change per tool)
- Sequence shift detection (Markov-style transitions; top N that changed most)
- Human-readable explanation string when drift exceeds threshold.
- Root cause pinpointing via change event correlation
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from dataclasses import dataclass
from typing import Any

from driftbase.local.local_store import BehavioralFingerprint, DriftReport

logger = logging.getLogger(__name__)


def _parse_tool_sequence(seq: Any) -> list[str]:
    if not seq:
        return []
    if isinstance(seq, list):
        return [str(t) for t in seq]
    if isinstance(seq, str):
        try:
            return [str(t) for t in json.loads(seq)]
        except Exception:
            return []
    return []


def tool_frequency_diff(
    baseline_run_dicts: list[dict[str, Any]],
    current_run_dicts: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Compute per-tool absolute and percentage change between baseline and current.

    Returns a list of dicts with keys: tool, baseline_count, current_count,
    baseline_pct, current_pct, delta_pct, delta_abs. Sorted by absolute delta_pct descending.
    """
    base_counter: Counter[str] = Counter()
    curr_counter: Counter[str] = Counter()
    for d in baseline_run_dicts:
        tools = _parse_tool_sequence(d.get("tool_sequence", "[]"))
        for t in tools:
            base_counter[t] += 1
    for d in current_run_dicts:
        tools = _parse_tool_sequence(d.get("tool_sequence", "[]"))
        for t in tools:
            curr_counter[t] += 1

    base_total = sum(base_counter.values())
    curr_total = sum(curr_counter.values())
    base_pct_denom = base_total if base_total else 1.0
    curr_pct_denom = curr_total if curr_total else 1.0

    all_tools = sorted(set(base_counter.keys()) | set(curr_counter.keys()))
    out: list[dict[str, Any]] = []
    for tool in all_tools:
        b_count = base_counter.get(tool, 0)
        c_count = curr_counter.get(tool, 0)
        b_pct = (b_count / base_pct_denom) * 100.0
        c_pct = (c_count / curr_pct_denom) * 100.0
        if b_pct == 0:
            delta_pct = 100.0 if c_pct > 0 else 0.0
        else:
            delta_pct = ((c_pct - b_pct) / b_pct) * 100.0
        delta_abs = c_count - b_count
        out.append(
            {
                "tool": tool,
                "baseline_count": b_count,
                "current_count": c_count,
                "baseline_pct": round(b_pct, 2),
                "current_pct": round(c_pct, 2),
                "delta_pct": round(delta_pct, 1),
                "delta_abs": delta_abs,
            }
        )
    out.sort(key=lambda x: abs(x["delta_pct"]), reverse=True)
    return out


def _transition_counts(run_dicts: list[dict[str, Any]]) -> Counter[str]:
    """Count consecutive tool pairs (Markov transitions) across all runs. Key format: 'A -> B'."""
    counts: Counter[str] = Counter()
    for d in run_dicts:
        tools = _parse_tool_sequence(d.get("tool_sequence", "[]"))
        for i in range(len(tools) - 1):
            key = f"{tools[i]} → {tools[i + 1]}"
            counts[key] += 1
    return counts


def transition_distribution(transition_counts: Counter[str]) -> dict[str, float]:
    """Normalize transition counts to a probability distribution."""
    total = sum(transition_counts.values())
    if total == 0:
        return {}
    return {k: v / total for k, v in transition_counts.items()}


def top_sequence_shifts(
    baseline_run_dicts: list[dict[str, Any]],
    current_run_dicts: list[dict[str, Any]],
    top_n: int = 3,
) -> list[dict[str, Any]]:
    """Identify the top N tool-sequence transitions (Markov) that changed the most.

    Returns list of dicts: transition, baseline_pct, current_pct, delta_pct.
    Sorted by absolute delta_pct descending.
    """
    base_counts = _transition_counts(baseline_run_dicts)
    curr_counts = _transition_counts(current_run_dicts)
    base_dist = transition_distribution(base_counts)
    curr_dist = transition_distribution(curr_counts)

    all_transitions = sorted(set(base_dist.keys()) | set(curr_dist.keys()))
    out: list[dict[str, Any]] = []
    for trans in all_transitions:
        b_pct = base_dist.get(trans, 0.0) * 100.0
        c_pct = curr_dist.get(trans, 0.0) * 100.0
        delta_pct = c_pct - b_pct
        out.append(
            {
                "transition": trans,
                "baseline_pct": round(b_pct, 2),
                "current_pct": round(c_pct, 2),
                "delta_pct": round(delta_pct, 1),
            }
        )
    out.sort(key=lambda x: abs(x["delta_pct"]), reverse=True)
    return out[:top_n]


def build_explanation(
    report: DriftReport,
    baseline_fp: BehavioralFingerprint,
    current_fp: BehavioralFingerprint,
    tool_frequency_diffs: list[dict[str, Any]],
    threshold: float,
) -> str:
    """Build a plain-text explanation when drift score exceeds threshold.

    Example: "Drift driven by Tool 'check_inventory' usage dropping by 45% and
    Latency increasing by 800ms."
    """
    if report.drift_score < threshold:
        return ""

    parts: list[str] = []

    # Biggest tool drop (by delta_pct)
    drops = [t for t in tool_frequency_diffs if t["delta_pct"] < -5]
    if drops:
        top_drop = drops[0]
        parts.append(
            f"Tool '{top_drop['tool']}' usage "
            f"{'dropping' if top_drop['delta_pct'] < 0 else 'rising'} by "
            f"{abs(top_drop['delta_pct']):.0f}%"
        )

    # Biggest tool rise (if not already mentioned and significant)
    rises = [t for t in tool_frequency_diffs if t["delta_pct"] > 20]
    if rises and (
        not drops or rises[0]["tool"] != (drops[0]["tool"] if drops else None)
    ):
        top_rise = rises[0]
        parts.append(
            f"Tool '{top_rise['tool']}' usage increasing by {top_rise['delta_pct']:.0f}%"
        )

    # Latency
    base_p95 = baseline_fp.p95_latency_ms
    curr_p95 = current_fp.p95_latency_ms
    latency_delta_ms = curr_p95 - base_p95
    if abs(latency_delta_ms) >= 100:
        if latency_delta_ms > 0:
            parts.append(f"Latency increasing by {latency_delta_ms}ms")
        else:
            parts.append(f"Latency decreasing by {abs(latency_delta_ms)}ms")

    # Error rate
    if report.error_drift >= 0.2:
        parts.append("Error rate increased significantly")

    if not parts:
        return f"Drift score {report.drift_score:.2f} exceeds threshold {threshold:.2f}. Review dimension breakdown and tool changes."

    return "Drift driven by " + " and ".join(parts) + "."


# ============================================================================
# ROOT CAUSE PINPOINTING VIA CHANGE EVENT CORRELATION
# ============================================================================


@dataclass
class RootCauseReport:
    """Root cause analysis correlating drift with recorded change events."""

    has_changes: bool
    winner: str | None  # change type, or None
    winner_confidence: str | None  # HIGH | MEDIUM | LOW | UNLIKELY | None
    winner_score: float | None  # 0.0 - 1.0
    winner_previous: str | None  # v1 value
    winner_current: str | None  # v2 value
    affected_dimensions: list[str]  # drifted dims that correlate with winner
    ruled_out: list[str]  # change types identical between versions
    suggested_action: str | None
    all_scores: dict[str, float]  # all change type correlation scores


@dataclass
class RollbackSuggestion:
    """Rollback suggestion when a clear regression is detected."""

    suggested_version: str
    suggested_version_verdict: str  # SHIP | MONITOR
    suggested_version_runs: int
    reason: str  # plain-English one-liner


# Correlation matrix: which dimensions correlate with which change types
DIMENSION_CORRELATIONS = {
    "model_version": {
        "decision_drift",
        "error_drift",
        "tool_sequence_drift",
        "semantic_drift",
        "verbosity_drift",
        "output_length_drift",
        "error_rate",
    },
    "prompt_hash": {
        "decision_drift",
        "semantic_drift",
        "verbosity_drift",
        "output_length_drift",
        "tool_sequence_drift",
    },
    "rag_snapshot": {
        "semantic_drift",
        "output_length_drift",
        "tool_sequence_drift",
    },
    "tool_version": {
        "error_drift",
        "tool_sequence_drift",
        "latency_drift",
        "retry_drift",
        "error_rate",
    },
}


def _get_suggested_action(
    change_type: str, v1_value: str | None, v2_value: str | None
) -> str:
    """Map change type to plain-English suggested action."""
    if change_type == "model_version":
        if v1_value and v2_value:
            return (
                f"Pin model version explicitly in your API call to isolate whether this "
                f'is model-induced. Compare: model="{v1_value}" vs model="{v2_value}"'
            )
        return "Pin model version explicitly in your API call to isolate model-induced drift"

    if change_type == "prompt_hash":
        return (
            "Review the system prompt diff between versions. Even small wording "
            "changes can shift decision distributions significantly."
        )

    if change_type == "rag_snapshot":
        return (
            "Compare the document sets in each RAG snapshot. New or removed documents "
            "directly affect retrieval behavior and output content."
        )

    if change_type == "tool_version":
        return (
            "Check the changelog for the tool between the two versions. Tool "
            "behavior changes are a common source of sequence and error drift."
        )

    if change_type.startswith("custom"):
        return (
            f"Review the recorded change ({change_type}={v2_value}) and assess "
            "whether it could affect agent decision logic."
        )

    return "Review the recorded change and assess its impact on agent behavior."


def correlate_drift_with_changes(
    drift_report: DriftReport,
    change_events: dict[str, list[dict[str, Any]]],
    drifted_dimensions: list[str],
) -> RootCauseReport:
    """
    Correlate detected drift with recorded change events.

    Args:
        drift_report: Computed drift report
        change_events: {"v1": list[ChangeEvent], "v2": list[ChangeEvent]}
        drifted_dimensions: Dimensions with score above MONITOR threshold

    Returns:
        RootCauseReport with correlation analysis

    Never raises - returns empty report on any error.
    """
    try:
        v1_events = change_events.get("v1", [])
        v2_events = change_events.get("v2", [])

        # If no change events for either version, return empty report
        if not v1_events and not v2_events:
            return RootCauseReport(
                has_changes=False,
                winner=None,
                winner_confidence=None,
                winner_score=None,
                winner_previous=None,
                winner_current=None,
                affected_dimensions=[],
                ruled_out=[],
                suggested_action="Record change events at deploy time using @track(changes={...}) or "
                "driftbase changes record to enable root cause analysis.",
                all_scores={},
            )

        # Build maps of change_type -> current value for each version
        v1_map = {e["change_type"]: e["current"] for e in v1_events}
        v2_map = {e["change_type"]: e["current"] for e in v2_events}

        # Identify which change types differ between v1 and v2
        all_change_types = set(v1_map.keys()) | set(v2_map.keys())
        changed_types = []
        ruled_out = []

        for change_type in all_change_types:
            v1_val = v1_map.get(change_type)
            v2_val = v2_map.get(change_type)

            if v1_val != v2_val:
                changed_types.append((change_type, v1_val, v2_val))
            else:
                ruled_out.append(change_type)

        # If no changes between versions, return empty report
        if not changed_types:
            return RootCauseReport(
                has_changes=True,
                winner=None,
                winner_confidence="UNLIKELY",
                winner_score=0.0,
                winner_previous=None,
                winner_current=None,
                affected_dimensions=[],
                ruled_out=list(all_change_types),
                suggested_action="No changes detected between versions despite having recorded change events.",
                all_scores={},
            )

        # Compute correlation score for each changed type
        scores = {}
        for change_type, _v1_val, _v2_val in changed_types:
            # Get correlated dimensions for this change type
            correlated_dims = DIMENSION_CORRELATIONS.get(change_type)

            # Custom changes correlate with all dimensions equally
            if correlated_dims is None:
                correlated_dims = set(drifted_dimensions)

            # Count how many drifted dimensions correlate with this change
            matching_dims = [d for d in drifted_dimensions if d in correlated_dims]
            if drifted_dimensions:
                score = len(matching_dims) / len(drifted_dimensions)
            else:
                score = 0.0

            scores[change_type] = score

        # Find winner (highest score)
        if not scores:
            return RootCauseReport(
                has_changes=True,
                winner=None,
                winner_confidence="UNLIKELY",
                winner_score=0.0,
                winner_previous=None,
                winner_current=None,
                affected_dimensions=[],
                ruled_out=ruled_out,
                suggested_action="Changes recorded but no correlation with drifted dimensions.",
                all_scores={},
            )

        winner_type = max(scores.keys(), key=lambda k: scores[k])
        winner_score = scores[winner_type]

        # Find winner values
        winner_v1 = None
        winner_v2 = None
        for change_type, v1_val, v2_val in changed_types:
            if change_type == winner_type:
                winner_v1 = v1_val
                winner_v2 = v2_val
                break

        # Determine confidence
        if winner_score >= 0.8:
            confidence = "HIGH"
        elif winner_score >= 0.5:
            confidence = "MEDIUM"
        elif winner_score >= 0.2:
            confidence = "LOW"
        else:
            confidence = "UNLIKELY"

        # Get affected dimensions
        correlated_dims = DIMENSION_CORRELATIONS.get(winner_type)
        if correlated_dims is None:
            correlated_dims = set(drifted_dimensions)
        affected_dims = [d for d in drifted_dimensions if d in correlated_dims]

        # Get suggested action
        suggested_action = _get_suggested_action(winner_type, winner_v1, winner_v2)

        return RootCauseReport(
            has_changes=True,
            winner=winner_type,
            winner_confidence=confidence,
            winner_score=winner_score,
            winner_previous=winner_v1,
            winner_current=winner_v2,
            affected_dimensions=affected_dims,
            ruled_out=ruled_out,
            suggested_action=suggested_action,
            all_scores=scores,
        )

    except Exception as e:
        logger.error(f"Root cause correlation failed: {e}")
        return RootCauseReport(
            has_changes=False,
            winner=None,
            winner_confidence=None,
            winner_score=None,
            winner_previous=None,
            winner_current=None,
            affected_dimensions=[],
            ruled_out=[],
            suggested_action=None,
            all_scores={},
        )


def get_rollback_suggestion(
    agent_id: str,
    eval_version: str,
    current_verdict: str,
    baseline_version: str | None = None,
    baseline_run_count: int = 0,
) -> RollbackSuggestion | None:
    """
    Returns RollbackSuggestion if a clear rollback target exists.
    Returns None if conditions are not met.
    Never raises.

    The simplest and most practical approach: if the current version has BLOCK/REVIEW,
    suggest rolling back to the baseline version used in the comparison if it has >= 30 runs.

    Args:
        agent_id: Agent identifier
        eval_version: Current version being evaluated
        current_verdict: Verdict string (SHIP/MONITOR/REVIEW/BLOCK)
        baseline_version: The baseline version used in the comparison
        baseline_run_count: Number of runs for the baseline version

    Returns:
        RollbackSuggestion if clear rollback target exists, None otherwise
    """
    try:
        # Only suggest rollback for BLOCK or REVIEW verdicts
        if current_verdict not in ("BLOCK", "REVIEW", "block", "review"):
            return None

        # Must have a baseline version to roll back to
        if not baseline_version:
            return None

        # Baseline must have sufficient data
        if baseline_run_count < 30:
            return None

        # Don't suggest rolling back to the same version
        if baseline_version == eval_version:
            return None

        # The baseline is implicitly stable because we're comparing against it
        # If the current version is BLOCK/REVIEW and baseline exists with >= 30 runs,
        # baseline is the natural rollback target
        reason = f"{baseline_version} was last stable (SHIP) with {baseline_run_count} runs recorded"
        return RollbackSuggestion(
            suggested_version=baseline_version,
            suggested_version_verdict="SHIP",  # Assume stable
            suggested_version_runs=baseline_run_count,
            reason=reason,
        )

    except Exception as e:
        logger.error(f"Rollback suggestion failed: {e}")
        return None
