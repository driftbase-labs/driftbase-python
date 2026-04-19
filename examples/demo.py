#!/usr/bin/env python3
"""
Driftbase Demo - Generate synthetic agent runs and detect drift

This demo shows how Driftbase detects behavioral drift across 9 dimensions
without requiring a real Langfuse account. It generates synthetic agent runs
for two versions and compares them.

Usage:
    python examples/demo.py
"""

import json
import random
from datetime import datetime, timedelta
from pathlib import Path

from driftbase.backends.sqlite import SQLiteBackend
from driftbase.local.diff import DRIFT_DIMENSIONS, compute_drift
from driftbase.local.local_store import run_dict_to_agent_run
from driftbase.verdict import Verdict, compute_verdict


def generate_synthetic_run(
    version: str, run_id: int, drift_factor: float = 0.0
) -> dict:
    """
    Generate a synthetic agent run with realistic behavioral properties.

    Args:
        version: Version identifier (e.g., "v1.0" or "v2.0")
        run_id: Unique run identifier
        drift_factor: Amount of drift to introduce (0.0 = no drift, 1.0 = maximum drift)

    Returns:
        Dictionary representing an agent run
    """
    base_tools = ["web_search", "calculator", "database_query", "api_call"]

    # Base behavior
    base_latency = 850
    base_output_length = 420
    base_tool_count = 2
    base_error_rate = 0.02

    # Apply drift
    latency = int(base_latency * (1 + drift_factor * 0.5))
    output_length = int(base_output_length * (1 + drift_factor * 0.7))
    tool_count = max(1, int(base_tool_count * (1 + drift_factor * 0.6)))
    has_error = random.random() < (base_error_rate + drift_factor * 0.08)

    # Generate tool sequence
    tools_used = random.choices(base_tools, k=tool_count)
    tool_sequence = json.dumps(tools_used)

    # Semantic cluster (escalation rate increases with drift)
    escalation_probability = 0.05 + drift_factor * 0.15
    if random.random() < escalation_probability:
        semantic_cluster = "escalated"
    elif has_error:
        semantic_cluster = "error"
    else:
        semantic_cluster = "resolved"

    # Generate run timestamp
    started_at = datetime.utcnow() - timedelta(hours=random.randint(1, 72))
    completed_at = started_at + timedelta(milliseconds=latency)

    return {
        "id": f"{version}-run-{run_id}",
        "session_id": "demo-agent",
        "deployment_version": version,
        "environment": "production",
        "started_at": started_at.isoformat(),
        "completed_at": completed_at.isoformat(),
        "task_input_hash": f"hash-{run_id % 20}",
        "tool_sequence": tool_sequence,
        "tool_call_count": tool_count,
        "output_length": output_length,
        "output_structure_hash": f"struct-{random.choice(['a', 'b', 'c'])}",
        "latency_ms": latency,
        "error_count": 1 if has_error else 0,
        "retry_count": 1 if has_error and random.random() < 0.5 else 0,
        "semantic_cluster": semantic_cluster,
        "raw_prompt": f"Sample task input {run_id}",
        "raw_output": f"Sample agent response with length {output_length}",
        "loop_count": random.randint(1, 4),
        "time_to_first_tool_ms": random.randint(100, 400),
        "verbosity_ratio": random.uniform(0.8, 1.2),
        "prompt_tokens": random.randint(50, 200),
        "completion_tokens": output_length // 4,
    }


def main():
    """Generate synthetic data and run drift detection."""
    print("=" * 70)
    print("DRIFTBASE DEMO - Behavioral Drift Detection")
    print("=" * 70)
    print()
    print("Generating synthetic agent runs...")
    print()

    # Create a temporary database
    db_path = Path.home() / ".driftbase" / "demo.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)

    # Clean up old demo data
    if db_path.exists():
        db_path.unlink()

    backend = SQLiteBackend(str(db_path))

    # Generate v1.0 runs (baseline - no drift)
    print("Generating v1.0 baseline runs...")
    v1_runs = []
    for i in range(25):
        run = generate_synthetic_run("v1.0", i, drift_factor=0.0)
        backend.write_run(run)
        v1_runs.append(run)

    # Generate v2.0 runs (with drift)
    print("Generating v2.0 runs with behavioral drift...")
    v2_runs = []
    for i in range(25):
        run = generate_synthetic_run("v2.0", i + 100, drift_factor=0.45)
        backend.write_run(run)
        v2_runs.append(run)

    print()
    print(f"✓ Generated {len(v1_runs)} runs for v1.0 (baseline)")
    print(f"✓ Generated {len(v2_runs)} runs for v2.0 (with drift)")
    print()

    # Convert to AgentRun objects
    v1_agent_runs = [run_dict_to_agent_run(r) for r in v1_runs]
    v2_agent_runs = [run_dict_to_agent_run(r) for r in v2_runs]

    # Compute drift
    print("Computing drift across 9 behavioral dimensions...")
    print()
    report = compute_drift(
        v1_agent_runs, v2_agent_runs, version_a="v1.0", version_b="v2.0"
    )

    # Display results
    print("─" * 70)
    print(f"DRIFT REPORT: {report.version_a} → {report.version_b}")
    print("─" * 70)
    print(
        f"Runs analyzed: {report.run_count_a} baseline / {report.run_count_b} current"
    )
    print()
    print("Dimension Breakdown:")
    print()

    for dim in DRIFT_DIMENSIONS:
        score = report.dimension_scores.get(dim, 0.0)
        bar_length = int(score * 40)
        bar = "█" * bar_length + "░" * (40 - bar_length)

        if score >= 0.3:
            signal = "HIGH"
            color = "\033[91m"  # Red
        elif score >= 0.1:
            signal = "MODERATE"
            color = "\033[93m"  # Yellow
        else:
            signal = "OK"
            color = "\033[92m"  # Green

        reset = "\033[0m"
        dim_display = dim.replace("_", " ").title().ljust(32)
        score_pct = f"{score * 100:5.1f}%"

        print(f"  {dim_display} {bar} {color}{score_pct} {signal}{reset}")

    print()
    print("─" * 70)
    print(f"Overall Drift Score: {report.overall_drift_score * 100:.1f}%")
    print(f"Severity: {report.severity.upper()}")
    print()

    # Compute and display verdict
    verdict_result = compute_verdict(report)

    if verdict_result:
        verdict_colors = {
            Verdict.SHIP: "\033[92m",  # Green
            Verdict.MONITOR: "\033[94m",  # Blue
            Verdict.REVIEW: "\033[93m",  # Yellow
            Verdict.BLOCK: "\033[91m",  # Red
        }
        color = verdict_colors.get(verdict_result.verdict, "")
        reset = "\033[0m"

        print(f"Verdict: {color}{verdict_result.verdict.name}{reset}")
        print(f"Reason: {verdict_result.explanation}")
        print()

        if verdict_result.next_steps:
            print("Next Steps:")
            for step in verdict_result.next_steps:
                print(f"  • {step}")
            print()

    print("─" * 70)
    print()
    print(f"Demo database saved to: {db_path}")
    print()
    print("To explore this data further, run:")
    print(f"  export DRIFTBASE_DB_PATH={db_path}")
    print("  driftbase diff v1.0 v2.0")
    print()
    print("Learn more at https://driftbase.io")
    print()


if __name__ == "__main__":
    main()
