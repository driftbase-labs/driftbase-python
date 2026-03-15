"""
Actionable root-cause analysis for drift reports.

Provides:
- Tool call frequency diff (absolute and percentage change per tool)
- Sequence shift detection (Markov-style transitions; top N that changed most)
- Human-readable explanation string when drift exceeds threshold.
"""

from __future__ import annotations

import json
from collections import Counter
from typing import Any

from driftbase.local.local_store import BehavioralFingerprint, DriftReport


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
