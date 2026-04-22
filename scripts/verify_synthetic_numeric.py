#!/usr/bin/env python3
"""
Cross-version numerical verification for Phase 2a schema refactor.

Compares drift computation on synthetic fixtures to verify behavioral equivalence.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent.parent / "tests"))

from driftbase.local.diff import compute_drift
from driftbase.local.fingerprinter import build_fingerprint_from_runs
from driftbase.local.local_store import run_dict_to_agent_run
from fixtures.synthetic.generators import (
    decision_drift_pair,
    error_rate_drift_pair,
    latency_drift_pair,
    no_drift_pair,
    semantic_cluster_drift_pair,
)


def main():
    """Run synthetic drift suite with bootstrap disabled for deterministic comparison."""
    results = {}

    # Test 1: No drift
    baseline_dicts, current_dicts = no_drift_pair(n=100, seed=42)
    baseline_runs = [run_dict_to_agent_run(d) for d in baseline_dicts]
    current_runs = [run_dict_to_agent_run(d) for d in current_dicts]
    window_start = min(r.started_at for r in baseline_runs + current_runs)
    window_end = max(r.completed_at for r in baseline_runs + current_runs)
    baseline_fp = build_fingerprint_from_runs(
        baseline_runs, window_start, window_end, "v1.0", "production"
    )
    current_fp = build_fingerprint_from_runs(
        current_runs, window_start, window_end, "v2.0", "production"
    )
    report = compute_drift(baseline_fp, current_fp, None, None)
    baseline_n = getattr(baseline_fp, "run_count", None) or getattr(
        baseline_fp, "sample_count", 0
    )
    current_n = getattr(current_fp, "run_count", None) or getattr(
        current_fp, "sample_count", 0
    )
    results["no_drift"] = {
        "composite_score": round(report.drift_score, 6),
        "severity": report.severity,
        "baseline_n": baseline_n,
        "current_n": current_n,
        "dimensions": {
            "decision_drift": round(report.decision_drift, 6),
            "error_drift": round(report.error_drift, 6),
            "latency_drift": round(report.latency_drift, 6),
            "loop_depth_drift": round(report.loop_depth_drift, 6),
            "output_drift": round(report.verbosity_drift, 6),
            "output_length_drift": round(report.output_length_drift, 6),
            "planning_latency_drift": round(report.planning_latency_drift, 6),
            "retry_drift": round(report.retry_drift, 6),
            "semantic_drift": round(report.semantic_drift, 6),
            "tool_sequence_drift": round(report.tool_sequence_drift, 6),
            "tool_sequence_transitions_drift": round(
                report.tool_sequence_transitions_drift, 6
            ),
            "verbosity_drift": round(report.verbosity_drift, 6),
        },
    }

    # Test 2: Decision drift
    baseline_dicts, current_dicts = decision_drift_pair(n=100, shift=0.3, seed=42)
    baseline_runs = [run_dict_to_agent_run(d) for d in baseline_dicts]
    current_runs = [run_dict_to_agent_run(d) for d in current_dicts]
    window_start = min(r.started_at for r in baseline_runs + current_runs)
    window_end = max(r.completed_at for r in baseline_runs + current_runs)
    baseline_fp = build_fingerprint_from_runs(
        baseline_runs, window_start, window_end, "v1.0", "production"
    )
    current_fp = build_fingerprint_from_runs(
        current_runs, window_start, window_end, "v2.0", "production"
    )
    report = compute_drift(baseline_fp, current_fp, None, None)
    baseline_n = getattr(baseline_fp, "run_count", None) or getattr(
        baseline_fp, "sample_count", 0
    )
    current_n = getattr(current_fp, "run_count", None) or getattr(
        current_fp, "sample_count", 0
    )
    results["decision_drift"] = {
        "composite_score": round(report.drift_score, 6),
        "severity": report.severity,
        "baseline_n": baseline_n,
        "current_n": current_n,
        "dimensions": {
            "decision_drift": round(report.decision_drift, 6),
            "error_drift": round(report.error_drift, 6),
            "latency_drift": round(report.latency_drift, 6),
            "loop_depth_drift": round(report.loop_depth_drift, 6),
            "output_drift": round(report.verbosity_drift, 6),
            "output_length_drift": round(report.output_length_drift, 6),
            "planning_latency_drift": round(report.planning_latency_drift, 6),
            "retry_drift": round(report.retry_drift, 6),
            "semantic_drift": round(report.semantic_drift, 6),
            "tool_sequence_drift": round(report.tool_sequence_drift, 6),
            "tool_sequence_transitions_drift": round(
                report.tool_sequence_transitions_drift, 6
            ),
            "verbosity_drift": round(report.verbosity_drift, 6),
        },
    }

    # Test 3: Latency drift
    baseline_dicts, current_dicts = latency_drift_pair(n=100, shift_ms=500, seed=42)
    baseline_runs = [run_dict_to_agent_run(d) for d in baseline_dicts]
    current_runs = [run_dict_to_agent_run(d) for d in current_dicts]
    window_start = min(r.started_at for r in baseline_runs + current_runs)
    window_end = max(r.completed_at for r in baseline_runs + current_runs)
    baseline_fp = build_fingerprint_from_runs(
        baseline_runs, window_start, window_end, "v1.0", "production"
    )
    current_fp = build_fingerprint_from_runs(
        current_runs, window_start, window_end, "v2.0", "production"
    )
    report = compute_drift(baseline_fp, current_fp, None, None)
    baseline_n = getattr(baseline_fp, "run_count", None) or getattr(
        baseline_fp, "sample_count", 0
    )
    current_n = getattr(current_fp, "run_count", None) or getattr(
        current_fp, "sample_count", 0
    )
    results["latency_drift"] = {
        "composite_score": round(report.drift_score, 6),
        "severity": report.severity,
        "baseline_n": baseline_n,
        "current_n": current_n,
        "dimensions": {
            "decision_drift": round(report.decision_drift, 6),
            "error_drift": round(report.error_drift, 6),
            "latency_drift": round(report.latency_drift, 6),
            "loop_depth_drift": round(report.loop_depth_drift, 6),
            "output_drift": round(report.verbosity_drift, 6),
            "output_length_drift": round(report.output_length_drift, 6),
            "planning_latency_drift": round(report.planning_latency_drift, 6),
            "retry_drift": round(report.retry_drift, 6),
            "semantic_drift": round(report.semantic_drift, 6),
            "tool_sequence_drift": round(report.tool_sequence_drift, 6),
            "tool_sequence_transitions_drift": round(
                report.tool_sequence_transitions_drift, 6
            ),
            "verbosity_drift": round(report.verbosity_drift, 6),
        },
    }

    # Test 4: Error rate drift
    baseline_dicts, current_dicts = error_rate_drift_pair(
        n=100, baseline_rate=0.05, current_rate=0.25, seed=42
    )
    baseline_runs = [run_dict_to_agent_run(d) for d in baseline_dicts]
    current_runs = [run_dict_to_agent_run(d) for d in current_dicts]
    window_start = min(r.started_at for r in baseline_runs + current_runs)
    window_end = max(r.completed_at for r in baseline_runs + current_runs)
    baseline_fp = build_fingerprint_from_runs(
        baseline_runs, window_start, window_end, "v1.0", "production"
    )
    current_fp = build_fingerprint_from_runs(
        current_runs, window_start, window_end, "v2.0", "production"
    )
    report = compute_drift(baseline_fp, current_fp, None, None)
    baseline_n = getattr(baseline_fp, "run_count", None) or getattr(
        baseline_fp, "sample_count", 0
    )
    current_n = getattr(current_fp, "run_count", None) or getattr(
        current_fp, "sample_count", 0
    )
    results["error_rate_drift"] = {
        "composite_score": round(report.drift_score, 6),
        "severity": report.severity,
        "baseline_n": baseline_n,
        "current_n": current_n,
        "dimensions": {
            "decision_drift": round(report.decision_drift, 6),
            "error_drift": round(report.error_drift, 6),
            "latency_drift": round(report.latency_drift, 6),
            "loop_depth_drift": round(report.loop_depth_drift, 6),
            "output_drift": round(report.verbosity_drift, 6),
            "output_length_drift": round(report.output_length_drift, 6),
            "planning_latency_drift": round(report.planning_latency_drift, 6),
            "retry_drift": round(report.retry_drift, 6),
            "semantic_drift": round(report.semantic_drift, 6),
            "tool_sequence_drift": round(report.tool_sequence_drift, 6),
            "tool_sequence_transitions_drift": round(
                report.tool_sequence_transitions_drift, 6
            ),
            "verbosity_drift": round(report.verbosity_drift, 6),
        },
    }

    # Test 5: Semantic cluster drift
    baseline_dicts, current_dicts = semantic_cluster_drift_pair(n=100, seed=42)
    baseline_runs = [run_dict_to_agent_run(d) for d in baseline_dicts]
    current_runs = [run_dict_to_agent_run(d) for d in current_dicts]
    window_start = min(r.started_at for r in baseline_runs + current_runs)
    window_end = max(r.completed_at for r in baseline_runs + current_runs)
    baseline_fp = build_fingerprint_from_runs(
        baseline_runs, window_start, window_end, "v1.0", "production"
    )
    current_fp = build_fingerprint_from_runs(
        current_runs, window_start, window_end, "v2.0", "production"
    )
    report = compute_drift(baseline_fp, current_fp, None, None)
    baseline_n = getattr(baseline_fp, "run_count", None) or getattr(
        baseline_fp, "sample_count", 0
    )
    current_n = getattr(current_fp, "run_count", None) or getattr(
        current_fp, "sample_count", 0
    )
    results["semantic_cluster_drift"] = {
        "composite_score": round(report.drift_score, 6),
        "severity": report.severity,
        "baseline_n": baseline_n,
        "current_n": current_n,
        "dimensions": {
            "decision_drift": round(report.decision_drift, 6),
            "error_drift": round(report.error_drift, 6),
            "latency_drift": round(report.latency_drift, 6),
            "loop_depth_drift": round(report.loop_depth_drift, 6),
            "output_drift": round(report.verbosity_drift, 6),
            "output_length_drift": round(report.output_length_drift, 6),
            "planning_latency_drift": round(report.planning_latency_drift, 6),
            "retry_drift": round(report.retry_drift, 6),
            "semantic_drift": round(report.semantic_drift, 6),
            "tool_sequence_drift": round(report.tool_sequence_drift, 6),
            "tool_sequence_transitions_drift": round(
                report.tool_sequence_transitions_drift, 6
            ),
            "verbosity_drift": round(report.verbosity_drift, 6),
        },
    }

    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
