#!/usr/bin/env python3
"""
Cross-process determinism test helper.

Generates synthetic fixtures, computes drift, outputs JSON for comparison.
Used by test_determinism.py to verify cross-process reproducibility.
"""

import json
import sys
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent.parent))

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


def run_fixture(fixture_name: str, seed: int) -> dict:
    """
    Generate fixture, compute drift, return result as JSON-serializable dict.

    Args:
        fixture_name: One of: no_drift, decision_drift, latency_drift,
                      error_rate_drift, semantic_cluster_drift
        seed: Random seed for generation

    Returns:
        Dict with drift_score and key dimensions
    """
    # Generate fixture
    if fixture_name == "no_drift":
        baseline_dicts, current_dicts = no_drift_pair(n=50, seed=seed)
    elif fixture_name == "decision_drift":
        baseline_dicts, current_dicts = decision_drift_pair(n=50, shift=0.3, seed=seed)
    elif fixture_name == "latency_drift":
        baseline_dicts, current_dicts = latency_drift_pair(
            n=50, shift_ms=500, seed=seed
        )
    elif fixture_name == "error_rate_drift":
        baseline_dicts, current_dicts = error_rate_drift_pair(
            n=50, baseline_rate=0.05, current_rate=0.25, seed=seed
        )
    elif fixture_name == "semantic_cluster_drift":
        baseline_dicts, current_dicts = semantic_cluster_drift_pair(n=50, seed=seed)
    else:
        raise ValueError(f"Unknown fixture: {fixture_name}")

    # Convert to AgentRun objects
    baseline_runs = [run_dict_to_agent_run(d) for d in baseline_dicts]
    current_runs = [run_dict_to_agent_run(d) for d in current_dicts]

    # Build fingerprints
    window_start = min(r.started_at for r in baseline_runs + current_runs)
    window_end = max(r.completed_at for r in baseline_runs + current_runs)

    baseline_fp = build_fingerprint_from_runs(
        baseline_runs, window_start, window_end, "v1.0", "production"
    )
    current_fp = build_fingerprint_from_runs(
        current_runs, window_start, window_end, "v2.0", "production"
    )

    # Compute drift (bootstrap disabled for determinism - passing None for raw dicts)
    report = compute_drift(baseline_fp, current_fp, None, None)

    # Return serializable result
    return {
        "fixture": fixture_name,
        "seed": seed,
        "drift_score": round(report.drift_score, 6),
        "decision_drift": round(report.decision_drift, 6),
        "latency_drift": round(report.latency_drift, 6),
        "error_drift": round(report.error_drift, 6),
        "semantic_drift": round(report.semantic_drift, 6),
        "severity": report.severity,
    }


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: run_synthetic_drift.py <fixture_name> <seed>", file=sys.stderr)
        sys.exit(1)

    fixture_name = sys.argv[1]
    seed = int(sys.argv[2])

    result = run_fixture(fixture_name, seed)
    print(json.dumps(result, indent=2))
