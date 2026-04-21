"""
Synthetic drift generators for testing detection accuracy.

All generators use deterministic seeding for reproducible tests.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

from driftbase.utils.determinism import get_rng


def no_drift_pair(n: int = 200, seed: int = 1) -> tuple[list[dict], list[dict]]:
    """
    Generate two sets of runs from identical distributions (no drift).

    Returns:
        (baseline_runs, current_runs) where distributions are identical
    """
    rng = get_rng(f"no_drift:{seed}")

    baseline = []
    current = []

    base_time = datetime.utcnow()

    for i in range(n):
        # Identical distribution parameters
        latency = int(rng.normal(1000, 200))
        error_count = 1 if rng.random() < 0.02 else 0
        tools = ["tool_a", "tool_b", "tool_c"]
        rng.shuffle(tools)
        tool_seq = tools[:2]

        baseline_run = {
            "id": f"baseline-{i}",
            "session_id": "test-session",
            "deployment_version": "v1.0",
            "version_source": "tag",
            "environment": "production",
            "started_at": base_time + timedelta(seconds=i),
            "completed_at": base_time + timedelta(seconds=i + latency / 1000),
            "task_input_hash": f"input-{i % 10}",
            "tool_sequence": json.dumps(tool_seq),
            "tool_call_count": len(tool_seq),
            "output_length": int(rng.normal(300, 50)),
            "output_structure_hash": f"output-{i % 10}",
            "latency_ms": latency,
            "error_count": error_count,
            "retry_count": 0,
            "semantic_cluster": "cluster_0" if error_count == 0 else "cluster_error",
            "loop_count": 1,
            "time_to_first_tool_ms": int(latency * 0.1),
            "verbosity_ratio": 0.5,
            "prompt_tokens": 100,
            "completion_tokens": 50,
        }
        baseline.append(baseline_run)

        # Current with identical distribution
        current_run = baseline_run.copy()
        current_run["id"] = f"current-{i}"
        current_run["deployment_version"] = "v2.0"
        current_run["started_at"] = base_time + timedelta(seconds=1000 + i)
        current_run["completed_at"] = base_time + timedelta(
            seconds=1000 + i + latency / 1000
        )
        current.append(current_run)

    return baseline, current


def decision_drift_pair(
    n: int = 200, shift: float = 0.3, seed: int = 2
) -> tuple[list[dict], list[dict]]:
    """
    Generate runs with decision drift (tool sequence changes).

    Args:
        n: Number of runs per version
        shift: Fraction of runs that switch to new tool path (0-1)
        seed: Random seed

    Returns:
        (baseline_runs, current_runs) where current has shifted tool usage
    """
    rng = get_rng(f"decision_drift:{seed}")

    baseline = []
    current = []

    base_time = datetime.utcnow()

    for i in range(n):
        latency = int(rng.normal(1000, 200))
        error_count = 1 if rng.random() < 0.02 else 0

        # Baseline uses path A→B
        tool_seq_baseline = ["tool_a", "tool_b"]

        baseline_run = {
            "id": f"baseline-{i}",
            "session_id": "test-session",
            "deployment_version": "v1.0",
            "version_source": "tag",
            "environment": "production",
            "started_at": base_time + timedelta(seconds=i),
            "completed_at": base_time + timedelta(seconds=i + latency / 1000),
            "task_input_hash": f"input-{i % 10}",
            "tool_sequence": json.dumps(tool_seq_baseline),
            "tool_call_count": len(tool_seq_baseline),
            "output_length": int(rng.normal(300, 50)),
            "output_structure_hash": f"output-{i % 10}",
            "latency_ms": latency,
            "error_count": error_count,
            "retry_count": 0,
            "semantic_cluster": "cluster_0" if error_count == 0 else "cluster_error",
            "loop_count": 1,
            "time_to_first_tool_ms": int(latency * 0.1),
            "verbosity_ratio": 0.5,
            "prompt_tokens": 100,
            "completion_tokens": 50,
        }
        baseline.append(baseline_run)

        # Current: shift% use new path C→D, rest use A→B
        if rng.random() < shift:
            tool_seq_current = ["tool_c", "tool_d"]
        else:
            tool_seq_current = ["tool_a", "tool_b"]

        current_run = baseline_run.copy()
        current_run["id"] = f"current-{i}"
        current_run["deployment_version"] = "v2.0"
        current_run["tool_sequence"] = json.dumps(tool_seq_current)
        current_run["tool_call_count"] = len(tool_seq_current)
        current_run["started_at"] = base_time + timedelta(seconds=1000 + i)
        current_run["completed_at"] = base_time + timedelta(
            seconds=1000 + i + latency / 1000
        )
        current.append(current_run)

    return baseline, current


def latency_drift_pair(
    n: int = 200, shift_ms: int = 500, seed: int = 3
) -> tuple[list[dict], list[dict]]:
    """
    Generate runs with latency drift (bimodal distribution).

    Args:
        n: Number of runs per version
        shift_ms: Latency increase for half the current runs
        seed: Random seed

    Returns:
        (baseline_runs, current_runs) where current has increased latency
    """
    rng = get_rng(f"latency_drift:{seed}")

    baseline = []
    current = []

    base_time = datetime.utcnow()

    for i in range(n):
        baseline_latency = int(rng.normal(1000, 200))
        error_count = 1 if rng.random() < 0.02 else 0
        tool_seq = ["tool_a", "tool_b"]

        baseline_run = {
            "id": f"baseline-{i}",
            "session_id": "test-session",
            "deployment_version": "v1.0",
            "version_source": "tag",
            "environment": "production",
            "started_at": base_time + timedelta(seconds=i),
            "completed_at": base_time + timedelta(seconds=i + baseline_latency / 1000),
            "task_input_hash": f"input-{i % 10}",
            "tool_sequence": json.dumps(tool_seq),
            "tool_call_count": len(tool_seq),
            "output_length": int(rng.normal(300, 50)),
            "output_structure_hash": f"output-{i % 10}",
            "latency_ms": baseline_latency,
            "error_count": error_count,
            "retry_count": 0,
            "semantic_cluster": "cluster_0" if error_count == 0 else "cluster_error",
            "loop_count": 1,
            "time_to_first_tool_ms": int(baseline_latency * 0.1),
            "verbosity_ratio": 0.5,
            "prompt_tokens": 100,
            "completion_tokens": 50,
        }
        baseline.append(baseline_run)

        # Current: half have increased latency (bimodal)
        if i < n // 2:
            current_latency = baseline_latency + shift_ms
        else:
            current_latency = baseline_latency

        current_run = baseline_run.copy()
        current_run["id"] = f"current-{i}"
        current_run["deployment_version"] = "v2.0"
        current_run["latency_ms"] = current_latency
        current_run["started_at"] = base_time + timedelta(seconds=1000 + i)
        current_run["completed_at"] = base_time + timedelta(
            seconds=1000 + i + current_latency / 1000
        )
        current_run["time_to_first_tool_ms"] = int(current_latency * 0.1)
        current.append(current_run)

    return baseline, current


def error_rate_drift_pair(
    n: int = 200,
    baseline_rate: float = 0.02,
    current_rate: float = 0.08,
    seed: int = 4,
) -> tuple[list[dict], list[dict]]:
    """
    Generate runs with error rate drift.

    Args:
        n: Number of runs per version
        baseline_rate: Baseline error rate (0-1)
        current_rate: Current error rate (0-1)
        seed: Random seed

    Returns:
        (baseline_runs, current_runs) where current has higher error rate
    """
    rng = get_rng(f"error_drift:{seed}")

    baseline = []
    current = []

    base_time = datetime.utcnow()

    for i in range(n):
        latency = int(rng.normal(1000, 200))
        tool_seq = ["tool_a", "tool_b"]

        # Baseline error rate
        baseline_error = 1 if rng.random() < baseline_rate else 0

        baseline_run = {
            "id": f"baseline-{i}",
            "session_id": "test-session",
            "deployment_version": "v1.0",
            "version_source": "tag",
            "environment": "production",
            "started_at": base_time + timedelta(seconds=i),
            "completed_at": base_time + timedelta(seconds=i + latency / 1000),
            "task_input_hash": f"input-{i % 10}",
            "tool_sequence": json.dumps(tool_seq),
            "tool_call_count": len(tool_seq),
            "output_length": int(rng.normal(300, 50)),
            "output_structure_hash": f"output-{i % 10}",
            "latency_ms": latency,
            "error_count": baseline_error,
            "retry_count": 0,
            "semantic_cluster": "cluster_0" if baseline_error == 0 else "cluster_error",
            "loop_count": 1,
            "time_to_first_tool_ms": int(latency * 0.1),
            "verbosity_ratio": 0.5,
            "prompt_tokens": 100,
            "completion_tokens": 50,
        }
        baseline.append(baseline_run)

        # Current with higher error rate
        current_error = 1 if rng.random() < current_rate else 0

        current_run = baseline_run.copy()
        current_run["id"] = f"current-{i}"
        current_run["deployment_version"] = "v2.0"
        current_run["error_count"] = current_error
        current_run["semantic_cluster"] = (
            "cluster_0" if current_error == 0 else "cluster_error"
        )
        current_run["started_at"] = base_time + timedelta(seconds=1000 + i)
        current_run["completed_at"] = base_time + timedelta(
            seconds=1000 + i + latency / 1000
        )
        current.append(current_run)

    return baseline, current


def semantic_cluster_drift_pair(
    n: int = 200, seed: int = 5
) -> tuple[list[dict], list[dict]]:
    """
    Generate runs with semantic cluster drift (outcome distribution changes).

    Returns:
        (baseline_runs, current_runs) where current has different outcome distribution
    """
    rng = get_rng(f"semantic_drift:{seed}")

    baseline = []
    current = []

    base_time = datetime.utcnow()

    for i in range(n):
        latency = int(rng.normal(1000, 200))
        tool_seq = ["tool_a", "tool_b"]

        # Baseline: 80% resolved, 15% escalated, 5% error
        r = rng.random()
        if r < 0.80:
            baseline_cluster = "cluster_0"
            error_count = 0
        elif r < 0.95:
            baseline_cluster = "cluster_escalated"
            error_count = 0
        else:
            baseline_cluster = "cluster_error"
            error_count = 1

        baseline_run = {
            "id": f"baseline-{i}",
            "session_id": "test-session",
            "deployment_version": "v1.0",
            "version_source": "tag",
            "environment": "production",
            "started_at": base_time + timedelta(seconds=i),
            "completed_at": base_time + timedelta(seconds=i + latency / 1000),
            "task_input_hash": f"input-{i % 10}",
            "tool_sequence": json.dumps(tool_seq),
            "tool_call_count": len(tool_seq),
            "output_length": int(rng.normal(300, 50)),
            "output_structure_hash": f"output-{i % 10}",
            "latency_ms": latency,
            "error_count": error_count,
            "retry_count": 0,
            "semantic_cluster": baseline_cluster,
            "loop_count": 1,
            "time_to_first_tool_ms": int(latency * 0.1),
            "verbosity_ratio": 0.5,
            "prompt_tokens": 100,
            "completion_tokens": 50,
        }
        baseline.append(baseline_run)

        # Current: 60% resolved, 30% escalated, 10% error (more escalations)
        r = rng.random()
        if r < 0.60:
            current_cluster = "cluster_0"
            error_count = 0
        elif r < 0.90:
            current_cluster = "cluster_escalated"
            error_count = 0
        else:
            current_cluster = "cluster_error"
            error_count = 1

        current_run = baseline_run.copy()
        current_run["id"] = f"current-{i}"
        current_run["deployment_version"] = "v2.0"
        current_run["semantic_cluster"] = current_cluster
        current_run["error_count"] = error_count
        current_run["started_at"] = base_time + timedelta(seconds=1000 + i)
        current_run["completed_at"] = base_time + timedelta(
            seconds=1000 + i + latency / 1000
        )
        current.append(current_run)

    return baseline, current
