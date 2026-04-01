"""Automatic behavioral epoch detection for agents without explicit versioning."""

import json
import logging
import math
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class Epoch:
    """Represents a detected behavioral epoch."""

    label: str
    start_run_id: str | None
    end_run_id: str | None
    start_time: datetime | None
    end_time: datetime | None
    run_count: int
    stability: str  # HIGH | MODERATE | LOW
    summary: str


def _jensen_shannon_divergence(p: dict[str, float], q: dict[str, float]) -> float:
    """
    Compute Jensen-Shannon divergence between two probability distributions.
    Returns a value in [0, 1]. 0 = identical, 1 = disjoint support.
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


def _build_simple_fingerprint(
    runs: list[dict[str, Any]],
) -> dict[str, dict[str, float]]:
    """
    Build a simplified fingerprint focusing on decision distribution and tool distribution.
    Returns {"decision_dist": {...}, "tool_dist": {...}}
    """
    if not runs:
        return {"decision_dist": {}, "tool_dist": {}}

    # Decision distribution
    decisions = [run.get("semantic_cluster", "cluster_none") for run in runs]
    decision_counts = Counter(decisions)
    total_decisions = len(decisions)
    decision_dist = {d: count / total_decisions for d, count in decision_counts.items()}

    # Tool distribution
    all_tools = []
    for run in runs:
        try:
            tool_seq = run.get("tool_sequence", "[]")
            if isinstance(tool_seq, str):
                tools = json.loads(tool_seq)
                if isinstance(tools, list):
                    all_tools.extend(str(t) for t in tools if t)
        except Exception:
            continue

    if all_tools:
        tool_counts = Counter(all_tools)
        total_tools = len(all_tools)
        tool_dist = {t: count / total_tools for t, count in tool_counts.items()}
    else:
        tool_dist = {}

    return {"decision_dist": decision_dist, "tool_dist": tool_dist}


def _compute_fingerprint_drift(fp1: dict, fp2: dict) -> float:
    """
    Compute drift between two fingerprints.
    Average JSD across decision_dist and tool_dist.
    """
    decision_jsd = _jensen_shannon_divergence(
        fp1.get("decision_dist", {}), fp2.get("decision_dist", {})
    )
    tool_jsd = _jensen_shannon_divergence(
        fp1.get("tool_dist", {}), fp2.get("tool_dist", {})
    )
    return (decision_jsd + tool_jsd) / 2.0


def _compute_stability(runs: list[dict[str, Any]]) -> str:
    """
    Compute stability of an epoch by checking internal variance.
    Split runs into two halves, compute drift between them.
    """
    if len(runs) < 10:
        return "UNKNOWN"

    mid = len(runs) // 2
    first_half = runs[:mid]
    second_half = runs[mid:]

    fp1 = _build_simple_fingerprint(first_half)
    fp2 = _build_simple_fingerprint(second_half)

    drift = _compute_fingerprint_drift(fp1, fp2)

    if drift < 0.10:
        return "HIGH"
    elif drift < 0.20:
        return "MODERATE"
    else:
        return "LOW"


def detect_epochs(
    agent_id: str,
    db_path: str,
    window_size: int = 20,
    sensitivity: float = 0.15,
) -> list[Epoch]:
    """
    Scan run history and detect behavioral breakpoints.

    Parameters:
    - agent_id: Agent identifier (session_id from runs)
    - db_path: Path to SQLite database
    - window_size: Number of runs per comparison window (default 20)
    - sensitivity: JSD threshold for declaring a breakpoint (default 0.15)

    Returns:
    - List of Epoch objects, each representing a period of stable behavior

    Never raises - returns empty list on error.
    """
    try:
        from driftbase.backends.factory import get_backend

        backend = get_backend()

        # Check cache first
        cached = backend.get_detected_epochs(agent_id)
        if cached is not None:
            # Cache hit - convert dicts back to Epoch objects
            return [
                Epoch(
                    label=e["label"],
                    start_run_id=e.get("start_run_id"),
                    end_run_id=e.get("end_run_id"),
                    start_time=e.get("start_time"),
                    end_time=e.get("end_time"),
                    run_count=e["run_count"],
                    stability=e.get("stability", "UNKNOWN"),
                    summary=e.get("summary", ""),
                )
                for e in cached
            ]

        # Load all runs for this agent, ordered by time
        all_runs = backend.get_all_runs()

        # If agent_id is None or empty, use all runs
        # Otherwise filter by session_id or id
        if agent_id:
            agent_runs = [
                r
                for r in all_runs
                if r.get("session_id") == agent_id or r.get("id") == agent_id
            ]
            # If no runs match or too few runs, fall back to all runs
            if len(agent_runs) < 40:
                agent_runs = all_runs
        else:
            agent_runs = all_runs

        if not agent_runs:
            # No runs found
            return []

        # Sort by started_at
        agent_runs.sort(key=lambda r: r.get("started_at", ""))

        if len(agent_runs) < 40:
            # Not enough data for epoch detection
            return []

        # Detect breakpoints using sliding window
        breakpoints = []  # List of indices where breakpoints occur
        prev_fingerprint = None

        for i in range(0, len(agent_runs) - window_size, window_size // 2):
            # Current window
            window_runs = agent_runs[i : i + window_size]
            if len(window_runs) < window_size:
                continue

            curr_fingerprint = _build_simple_fingerprint(window_runs)

            if prev_fingerprint is not None:
                drift = _compute_fingerprint_drift(prev_fingerprint, curr_fingerprint)
                if drift > sensitivity:
                    breakpoints.append(i)

            prev_fingerprint = curr_fingerprint

        # Merge breakpoints that are close together (< 10 runs apart)
        merged_breakpoints = []
        for bp in breakpoints:
            if not merged_breakpoints or bp - merged_breakpoints[-1] >= 10:
                merged_breakpoints.append(bp)

        # Create epochs from breakpoints
        epochs = []
        epoch_boundaries = [0] + merged_breakpoints + [len(agent_runs)]

        for i in range(len(epoch_boundaries) - 1):
            start_idx = epoch_boundaries[i]
            end_idx = epoch_boundaries[i + 1]
            epoch_runs = agent_runs[start_idx:end_idx]

            if not epoch_runs:
                continue

            # Determine epoch label
            first_run = epoch_runs[0]
            start_time_str = first_run.get("started_at", "")
            if isinstance(start_time_str, str) and start_time_str:
                try:
                    start_time = datetime.fromisoformat(
                        start_time_str.replace("Z", "+00:00")
                    )
                    epoch_label = f"epoch-{start_time.date().isoformat()}"
                except Exception:
                    epoch_label = f"epoch-{i + 1}"
            else:
                epoch_label = f"epoch-{i + 1}"

            start_time = None
            end_time = None
            try:
                if isinstance(epoch_runs[0].get("started_at"), str):
                    start_time = datetime.fromisoformat(
                        epoch_runs[0]["started_at"].replace("Z", "+00:00")
                    )
                if isinstance(epoch_runs[-1].get("completed_at"), str):
                    end_time = datetime.fromisoformat(
                        epoch_runs[-1]["completed_at"].replace("Z", "+00:00")
                    )
            except Exception:
                pass

            stability = _compute_stability(epoch_runs)

            summary = f"Stable behavior: {len(epoch_runs)} runs"
            if stability == "LOW":
                summary = f"Unstable behavior: {len(epoch_runs)} runs, high variance"

            epoch = Epoch(
                label=epoch_label,
                start_run_id=epoch_runs[0].get("id"),
                end_run_id=epoch_runs[-1].get("id"),
                start_time=start_time,
                end_time=end_time,
                run_count=len(epoch_runs),
                stability=stability,
                summary=summary,
            )
            epochs.append(epoch)

        # Cache the results
        if epochs:
            epoch_dicts = [
                {
                    "label": e.label,
                    "start_run_id": e.start_run_id,
                    "end_run_id": e.end_run_id,
                    "start_time": e.start_time,
                    "end_time": e.end_time,
                    "run_count": e.run_count,
                    "stability": e.stability,
                    "summary": e.summary,
                }
                for e in epochs
            ]
            backend.write_detected_epochs(agent_id, epoch_dicts, ttl_hours=1)

        return epochs

    except Exception as e:
        logger.debug(f"epoch_detector: {e}", exc_info=True)
        return []
