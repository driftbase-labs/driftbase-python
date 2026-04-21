"""
Tests for version_source three-way warning logic.

Verifies that diff reports handle version_source categories correctly:
- release/tag/env → confident (no warning)
- unknown → soft advisory (no tier downgrade)
- epoch → loud warning + tier downgrade
"""

from __future__ import annotations

from datetime import datetime, timedelta

from driftbase.local.diff import compute_drift
from driftbase.local.fingerprinter import build_fingerprint_from_runs
from driftbase.local.local_store import run_dict_to_agent_run


def _make_run(
    run_id: str,
    version: str,
    version_source: str,
    tool_sequence: str = '["tool_a"]',
    started_offset_hours: int = 0,
) -> dict:
    """Create a minimal run dict with specified version_source."""
    started = datetime.utcnow() - timedelta(hours=started_offset_hours)
    completed = started + timedelta(seconds=10)

    return {
        "id": run_id,
        "session_id": "test-agent",
        "deployment_version": version,
        "version_source": version_source,
        "environment": "production",
        "started_at": started,
        "completed_at": completed,
        "task_input_hash": "hash123",
        "tool_sequence": tool_sequence,
        "tool_call_count": 1,
        "output_length": 100,
        "output_structure_hash": "outhash",
        "latency_ms": 1000,
        "error_count": 0,
        "retry_count": 0,
        "semantic_cluster": "cluster_resolved",
        "ingestion_source": "connector",
    }


def test_confident_versions_no_warning():
    """
    All runs have confident version_source (release/tag/env).
    Should produce no warning and no tier downgrade.
    """
    # Create 60 baseline runs with "release" source
    baseline_dicts = [
        _make_run(f"b{i}", "v1.0", "release", started_offset_hours=i) for i in range(60)
    ]
    # Create 60 current runs with "tag" source
    current_dicts = [
        _make_run(f"c{i}", "v2.0", "tag", started_offset_hours=i) for i in range(60)
    ]

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

    report = compute_drift(baseline_fp, current_fp, baseline_dicts, current_dicts)

    # Should have no warnings
    assert len(report.warnings) == 0, f"Expected no warnings, got {report.warnings}"
    # Should be TIER3 (60 runs on each side)
    assert report.confidence_tier == "TIER3"


def test_unknown_versions_soft_advisory():
    """
    >50% of runs have unknown version_source (pre-existing data).
    Should produce soft advisory but no tier downgrade.
    """
    # Create 60 baseline runs with "unknown" source
    baseline_dicts = [
        _make_run(f"b{i}", "v1.0", "unknown", started_offset_hours=i) for i in range(60)
    ]
    # Create 60 current runs with "unknown" source
    current_dicts = [
        _make_run(f"c{i}", "v2.0", "unknown", started_offset_hours=i) for i in range(60)
    ]

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

    report = compute_drift(baseline_fp, current_fp, baseline_dicts, current_dicts)

    # Should have soft advisory warning
    assert len(report.warnings) == 1
    assert "predate version-source tracking" in report.warnings[0]
    assert "Re-sync from Langfuse" in report.warnings[0]
    # Should still be TIER3 (no downgrade for unknown)
    assert report.confidence_tier == "TIER3"


def test_epoch_versions_loud_warning_and_downgrade():
    """
    >50% of runs have epoch version_source.
    Should produce loud warning and downgrade tier.
    """
    # Create 60 baseline runs with "epoch" source
    baseline_dicts = [
        _make_run(f"b{i}", "epoch-2024-03-04", "epoch", started_offset_hours=i)
        for i in range(60)
    ]
    # Create 60 current runs with "epoch" source
    current_dicts = [
        _make_run(f"c{i}", "epoch-2024-03-11", "epoch", started_offset_hours=i)
        for i in range(60)
    ]

    baseline_runs = [run_dict_to_agent_run(d) for d in baseline_dicts]
    current_runs = [run_dict_to_agent_run(d) for d in current_dicts]

    window_start = min(r.started_at for r in baseline_runs + current_runs)
    window_end = max(r.completed_at for r in baseline_runs + current_runs)

    baseline_fp = build_fingerprint_from_runs(
        baseline_runs, window_start, window_end, "epoch-2024-03-04", "production"
    )
    current_fp = build_fingerprint_from_runs(
        current_runs, window_start, window_end, "epoch-2024-03-11", "production"
    )

    report = compute_drift(baseline_fp, current_fp, baseline_dicts, current_dicts)

    # Should have loud warning about epoch versions
    assert len(report.warnings) == 1
    assert "time-bucketed versions" in report.warnings[0]
    assert "Langfuse release field" in report.warnings[0]
    # Should be downgraded from TIER3 to TIER2
    assert report.confidence_tier == "TIER2"


def test_mixed_epoch_and_unknown_epoch_warning_wins():
    """
    Mix of >50% epoch + <50% unknown in baseline.
    Epoch warning should win (strongest applicable).
    """
    # Create 31 baseline runs with "epoch", 29 with "unknown" (51.67% epoch)
    baseline_dicts = [
        _make_run(f"b{i}", "epoch-2024-03-04", "epoch", started_offset_hours=i)
        for i in range(31)
    ] + [
        _make_run(f"b{i}", "epoch-2024-03-04", "unknown", started_offset_hours=i + 31)
        for i in range(29)
    ]
    # Create 60 current runs with "release" (confident)
    current_dicts = [
        _make_run(f"c{i}", "v2.0", "release", started_offset_hours=i) for i in range(60)
    ]

    baseline_runs = [run_dict_to_agent_run(d) for d in baseline_dicts]
    current_runs = [run_dict_to_agent_run(d) for d in current_dicts]

    window_start = min(r.started_at for r in baseline_runs + current_runs)
    window_end = max(r.completed_at for r in baseline_runs + current_runs)

    baseline_fp = build_fingerprint_from_runs(
        baseline_runs, window_start, window_end, "epoch-2024-03-04", "production"
    )
    current_fp = build_fingerprint_from_runs(
        current_runs, window_start, window_end, "v2.0", "production"
    )

    report = compute_drift(baseline_fp, current_fp, baseline_dicts, current_dicts)

    # Epoch warning should win (strongest)
    assert len(report.warnings) == 1
    assert "time-bucketed versions" in report.warnings[0]
    # Should be downgraded due to epoch presence
    assert report.confidence_tier == "TIER2"


def test_mixed_unknown_and_confident_no_warning():
    """
    Mix of 40% unknown + 60% confident.
    Unknown is below 50% threshold, so no warning.
    """
    # Create 24 baseline runs with "unknown", 36 with "release"
    baseline_dicts = [
        _make_run(f"b{i}", "v1.0", "unknown", started_offset_hours=i) for i in range(24)
    ] + [
        _make_run(f"b{i}", "v1.0", "release", started_offset_hours=i + 24)
        for i in range(36)
    ]
    # Create 60 current runs with "release"
    current_dicts = [
        _make_run(f"c{i}", "v2.0", "release", started_offset_hours=i) for i in range(60)
    ]

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

    report = compute_drift(baseline_fp, current_fp, baseline_dicts, current_dicts)

    # Should have no warnings (unknown below 50% threshold)
    assert len(report.warnings) == 0
    # Should be TIER3 (no downgrade)
    assert report.confidence_tier == "TIER3"
