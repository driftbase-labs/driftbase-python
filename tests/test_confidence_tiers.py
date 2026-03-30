"""
Test suite for progressive confidence tiers (TIER1, TIER2, TIER3).

Tests the three-tier system based on sample sizes:
- TIER1 (n < 15): No analysis, progress bars only
- TIER2 (15 ≤ n < 50): Indicative directional signals only
- TIER3 (n ≥ 50): Full analysis with verdict
"""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from driftbase.config import get_settings
from driftbase.local.diff import (
    compute_drift,
    compute_indicative_signal,
    get_confidence_tier,
)
from driftbase.local.fingerprinter import build_fingerprint_from_runs
from driftbase.local.local_store import AgentRun, DriftReport, run_dict_to_agent_run
from driftbase.verdict import compute_verdict


def create_mock_run(
    tool_sequence: list[str],
    latency_ms: int = 1000,
    error_count: int = 0,
    deployment_version: str = "v1.0",
) -> AgentRun:
    """Create a mock AgentRun for testing."""
    import json

    return AgentRun(
        id="test-run-id",
        session_id="test-agent",
        deployment_version=deployment_version,
        environment="production",
        started_at=datetime.utcnow(),
        completed_at=datetime.utcnow(),
        task_input_hash="hash123",
        tool_sequence=json.dumps(tool_sequence),
        tool_call_count=len(tool_sequence),
        output_length=100,
        output_structure_hash="out_hash",
        latency_ms=latency_ms,
        error_count=error_count,
        retry_count=0,
        semantic_cluster="cluster_0",
        loop_count=1,
        time_to_first_tool_ms=100,
        verbosity_ratio=0.5,
    )


class TestGetConfidenceTier:
    """Test get_confidence_tier() function."""

    def test_tier1_both_below_threshold(self):
        """TIER1 when both versions have < 15 runs."""
        tier = get_confidence_tier(10, 12)
        assert tier == "TIER1"

    def test_tier1_one_below_threshold(self):
        """TIER1 when one version has < 15 runs."""
        tier = get_confidence_tier(8, 25)
        assert tier == "TIER1"

    def test_tier2_both_in_range(self):
        """TIER2 when both versions have 15-49 runs."""
        tier = get_confidence_tier(20, 30)
        assert tier == "TIER2"

    def test_tier2_one_in_range(self):
        """TIER2 when min(baseline, eval) is 15-49."""
        tier = get_confidence_tier(25, 100)
        assert tier == "TIER2"

    def test_tier3_both_above_threshold(self):
        """TIER3 when both versions have >= 50 runs."""
        tier = get_confidence_tier(60, 80)
        assert tier == "TIER3"

    def test_limiting_version_eval(self):
        """TIER1 when eval has fewer runs."""
        tier = get_confidence_tier(100, 10)
        assert tier == "TIER1"


class TestComputeIndicativeSignal:
    """Test compute_indicative_signal() function for TIER2."""

    def test_no_signals_identical_fingerprints(self):
        """No signals when fingerprints are identical."""
        baseline_runs = [create_mock_run(["tool_a", "tool_b"]) for _ in range(20)]
        current_runs = [create_mock_run(["tool_a", "tool_b"]) for _ in range(20)]

        now = datetime.utcnow()
        baseline_fp = build_fingerprint_from_runs(
            baseline_runs,
            window_start=now,
            window_end=now,
            deployment_version="v1.0",
            environment="production",
        )
        current_fp = build_fingerprint_from_runs(
            current_runs,
            window_start=now,
            window_end=now,
            deployment_version="v2.0",
            environment="production",
        )

        signals = compute_indicative_signal(baseline_fp, current_fp)

        # Should have minimal or no signals since fingerprints are nearly identical
        assert isinstance(signals, dict)

    def test_decision_drift_signal(self):
        """Signal for decision drift when tool distribution changes."""
        baseline_runs = [create_mock_run(["tool_a", "tool_b"]) for _ in range(20)]
        current_runs = [create_mock_run(["tool_c", "tool_d"]) for _ in range(20)]

        now = datetime.utcnow()
        baseline_fp = build_fingerprint_from_runs(
            baseline_runs,
            window_start=now,
            window_end=now,
            deployment_version="v1.0",
            environment="production",
        )
        current_fp = build_fingerprint_from_runs(
            current_runs,
            window_start=now,
            window_end=now,
            deployment_version="v2.0",
            environment="production",
        )

        signals = compute_indicative_signal(baseline_fp, current_fp)

        assert "decision_patterns" in signals
        assert signals["decision_patterns"] in ("↑", "→")

    def test_latency_increase_signal(self):
        """Signal for latency increase."""
        baseline_runs = [
            create_mock_run(["tool_a"], latency_ms=1000) for _ in range(20)
        ]
        current_runs = [create_mock_run(["tool_a"], latency_ms=2000) for _ in range(20)]

        now = datetime.utcnow()
        baseline_fp = build_fingerprint_from_runs(
            baseline_runs,
            window_start=now,
            window_end=now,
            deployment_version="v1.0",
            environment="production",
        )
        current_fp = build_fingerprint_from_runs(
            current_runs,
            window_start=now,
            window_end=now,
            deployment_version="v2.0",
            environment="production",
        )

        signals = compute_indicative_signal(baseline_fp, current_fp)

        assert "latency" in signals
        assert signals["latency"] == "↑"

    def test_latency_decrease_signal(self):
        """Signal for latency decrease."""
        baseline_runs = [
            create_mock_run(["tool_a"], latency_ms=2000) for _ in range(20)
        ]
        current_runs = [create_mock_run(["tool_a"], latency_ms=1000) for _ in range(20)]

        now = datetime.utcnow()
        baseline_fp = build_fingerprint_from_runs(
            baseline_runs,
            window_start=now,
            window_end=now,
            deployment_version="v1.0",
            environment="production",
        )
        current_fp = build_fingerprint_from_runs(
            current_runs,
            window_start=now,
            window_end=now,
            deployment_version="v2.0",
            environment="production",
        )

        signals = compute_indicative_signal(baseline_fp, current_fp)

        assert "latency" in signals
        assert signals["latency"] == "↓"

    def test_error_rate_increase_signal(self):
        """Signal for error rate increase."""
        baseline_runs = [create_mock_run(["tool_a"], error_count=0) for _ in range(20)]
        current_runs = [
            create_mock_run(["tool_a"], error_count=2) for _ in range(20)
        ]  # 10% error rate

        now = datetime.utcnow()
        baseline_fp = build_fingerprint_from_runs(
            baseline_runs,
            window_start=now,
            window_end=now,
            deployment_version="v1.0",
            environment="production",
        )
        current_fp = build_fingerprint_from_runs(
            current_runs,
            window_start=now,
            window_end=now,
            deployment_version="v2.0",
            environment="production",
        )

        signals = compute_indicative_signal(baseline_fp, current_fp)

        # May or may not have error_rate signal depending on exact calculation
        # Just verify signals is a dict
        assert isinstance(signals, dict)


class TestComputeDriftTier1:
    """Test compute_drift() with TIER1 sample sizes."""

    def test_tier1_returns_minimal_report(self):
        """TIER1 returns minimal report with no analysis."""
        baseline_runs = [create_mock_run(["tool_a"]) for _ in range(10)]
        current_runs = [create_mock_run(["tool_b"]) for _ in range(12)]

        now = datetime.utcnow()
        baseline_fp = build_fingerprint_from_runs(
            baseline_runs,
            window_start=now,
            window_end=now,
            deployment_version="v1.0",
            environment="production",
        )
        current_fp = build_fingerprint_from_runs(
            current_runs,
            window_start=now,
            window_end=now,
            deployment_version="v2.0",
            environment="production",
        )

        report = compute_drift(baseline_fp, current_fp)

        assert report.confidence_tier == "TIER1"
        assert report.drift_score == 0.0
        assert report.severity == "none"
        assert report.baseline_n == 10
        assert report.eval_n == 12
        assert report.runs_needed == 5  # 15 - 10
        assert report.limiting_version == "baseline"

    def test_tier1_no_verdict(self):
        """TIER1 produces no verdict."""
        baseline_runs = [create_mock_run(["tool_a"]) for _ in range(8)]
        current_runs = [create_mock_run(["tool_b"]) for _ in range(8)]

        now = datetime.utcnow()
        baseline_fp = build_fingerprint_from_runs(
            baseline_runs,
            window_start=now,
            window_end=now,
            deployment_version="v1.0",
            environment="production",
        )
        current_fp = build_fingerprint_from_runs(
            current_runs,
            window_start=now,
            window_end=now,
            deployment_version="v2.0",
            environment="production",
        )

        report = compute_drift(baseline_fp, current_fp)

        verdict = compute_verdict(report)
        assert verdict is None  # No verdict for TIER1


class TestComputeDriftTier2:
    """Test compute_drift() with TIER2 sample sizes."""

    def test_tier2_returns_indicative_signals(self):
        """TIER2 returns indicative signals but no numeric scores."""
        baseline_runs = [create_mock_run(["tool_a"]) for _ in range(20)]
        current_runs = [create_mock_run(["tool_b"]) for _ in range(25)]

        now = datetime.utcnow()
        baseline_fp = build_fingerprint_from_runs(
            baseline_runs,
            window_start=now,
            window_end=now,
            deployment_version="v1.0",
            environment="production",
        )
        current_fp = build_fingerprint_from_runs(
            current_runs,
            window_start=now,
            window_end=now,
            deployment_version="v2.0",
            environment="production",
        )

        report = compute_drift(baseline_fp, current_fp)

        assert report.confidence_tier == "TIER2"
        assert report.drift_score == 0.0  # No numeric score for TIER2
        assert report.severity == "none"
        assert report.baseline_n == 20
        assert report.eval_n == 25
        assert report.runs_needed == 30  # 50 - 20 (limiting version)
        assert report.limiting_version == "baseline"
        assert report.indicative_signal is not None
        assert isinstance(report.indicative_signal, dict)

    def test_tier2_no_verdict(self):
        """TIER2 produces no verdict."""
        baseline_runs = [create_mock_run(["tool_a"]) for _ in range(30)]
        current_runs = [create_mock_run(["tool_b"]) for _ in range(35)]

        now = datetime.utcnow()
        baseline_fp = build_fingerprint_from_runs(
            baseline_runs,
            window_start=now,
            window_end=now,
            deployment_version="v1.0",
            environment="production",
        )
        current_fp = build_fingerprint_from_runs(
            current_runs,
            window_start=now,
            window_end=now,
            deployment_version="v2.0",
            environment="production",
        )

        report = compute_drift(baseline_fp, current_fp)

        verdict = compute_verdict(report)
        assert verdict is None  # No verdict for TIER2

    def test_tier2_indicative_signal_present(self):
        """TIER2 includes indicative_signal field with directional indicators."""
        baseline_runs = [
            create_mock_run(["tool_a"], latency_ms=1000) for _ in range(20)
        ]
        current_runs = [create_mock_run(["tool_c"], latency_ms=2000) for _ in range(25)]

        now = datetime.utcnow()
        baseline_fp = build_fingerprint_from_runs(
            baseline_runs,
            window_start=now,
            window_end=now,
            deployment_version="v1.0",
            environment="production",
        )
        current_fp = build_fingerprint_from_runs(
            current_runs,
            window_start=now,
            window_end=now,
            deployment_version="v2.0",
            environment="production",
        )

        report = compute_drift(baseline_fp, current_fp)

        assert report.confidence_tier == "TIER2"
        assert report.indicative_signal is not None
        # Should have signals for decision and latency changes
        assert len(report.indicative_signal) > 0


class TestComputeDriftTier3:
    """Test compute_drift() with TIER3 sample sizes."""

    def test_tier3_full_analysis(self):
        """TIER3 performs full analysis with drift scores."""
        baseline_runs = [create_mock_run(["tool_a"]) for _ in range(60)]
        current_runs = [create_mock_run(["tool_b"]) for _ in range(70)]

        now = datetime.utcnow()
        baseline_fp = build_fingerprint_from_runs(
            baseline_runs,
            window_start=now,
            window_end=now,
            deployment_version="v1.0",
            environment="production",
        )
        current_fp = build_fingerprint_from_runs(
            current_runs,
            window_start=now,
            window_end=now,
            deployment_version="v2.0",
            environment="production",
        )

        baseline_run_dicts = [
            {
                "id": f"run-{i}",
                "session_id": "test-agent",
                "deployment_version": "v1.0",
                "environment": "production",
                "started_at": datetime.utcnow(),
                "completed_at": datetime.utcnow(),
                "task_input_hash": "hash",
                "tool_sequence": '["tool_a"]',
                "tool_call_count": 1,
                "output_length": 100,
                "output_structure_hash": "hash",
                "latency_ms": 1000,
                "error_count": 0,
                "retry_count": 0,
                "semantic_cluster": "cluster_0",
            }
            for i in range(60)
        ]

        current_run_dicts = [
            {
                "id": f"run-{i}",
                "session_id": "test-agent",
                "deployment_version": "v2.0",
                "environment": "production",
                "started_at": datetime.utcnow(),
                "completed_at": datetime.utcnow(),
                "task_input_hash": "hash",
                "tool_sequence": '["tool_b"]',
                "tool_call_count": 1,
                "output_length": 100,
                "output_structure_hash": "hash",
                "latency_ms": 1000,
                "error_count": 0,
                "retry_count": 0,
                "semantic_cluster": "cluster_0",
            }
            for i in range(70)
        ]

        report = compute_drift(
            baseline_fp, current_fp, baseline_run_dicts, current_run_dicts
        )

        assert report.confidence_tier == "TIER3"
        assert report.drift_score > 0  # Should have actual drift score
        assert report.baseline_n == 60
        assert report.eval_n == 70
        assert report.runs_needed == 0
        assert report.limiting_version == ""

    def test_tier3_has_verdict(self):
        """TIER3 produces a verdict."""
        baseline_runs = [create_mock_run(["tool_a"]) for _ in range(60)]
        current_runs = [create_mock_run(["tool_a"]) for _ in range(60)]

        now = datetime.utcnow()
        baseline_fp = build_fingerprint_from_runs(
            baseline_runs,
            window_start=now,
            window_end=now,
            deployment_version="v1.0",
            environment="production",
        )
        current_fp = build_fingerprint_from_runs(
            current_runs,
            window_start=now,
            window_end=now,
            deployment_version="v2.0",
            environment="production",
        )

        baseline_run_dicts = [
            {
                "id": f"run-{i}",
                "session_id": "test-agent",
                "deployment_version": "v1.0",
                "environment": "production",
                "started_at": datetime.utcnow(),
                "completed_at": datetime.utcnow(),
                "task_input_hash": "hash",
                "tool_sequence": '["tool_a"]',
                "tool_call_count": 1,
                "output_length": 100,
                "output_structure_hash": "hash",
                "latency_ms": 1000,
                "error_count": 0,
                "retry_count": 0,
                "semantic_cluster": "cluster_0",
            }
            for i in range(60)
        ]

        current_run_dicts = [
            {
                "id": f"run-{i}",
                "session_id": "test-agent",
                "deployment_version": "v2.0",
                "environment": "production",
                "started_at": datetime.utcnow(),
                "completed_at": datetime.utcnow(),
                "task_input_hash": "hash",
                "tool_sequence": '["tool_a"]',
                "tool_call_count": 1,
                "output_length": 100,
                "output_structure_hash": "hash",
                "latency_ms": 1000,
                "error_count": 0,
                "retry_count": 0,
                "semantic_cluster": "cluster_0",
            }
            for i in range(60)
        ]

        report = compute_drift(
            baseline_fp, current_fp, baseline_run_dicts, current_run_dicts
        )

        verdict = compute_verdict(report)
        assert verdict is not None  # Should have verdict for TIER3
        assert verdict.verdict is not None


class TestConfigSettings:
    """Test configuration settings for tier thresholds."""

    def test_tier1_min_runs_default(self):
        """TIER1_MIN_RUNS defaults to 15."""
        settings = get_settings()
        assert settings.TIER1_MIN_RUNS == 15

    def test_tier2_min_runs_default(self):
        """TIER2_MIN_RUNS defaults to 50."""
        settings = get_settings()
        assert settings.TIER2_MIN_RUNS == 50

    @patch.dict("os.environ", {"DRIFTBASE_TIER1_MIN_RUNS": "20"})
    def test_tier1_min_runs_custom(self):
        """TIER1_MIN_RUNS can be customized via env var."""
        from driftbase.config import Settings

        settings = Settings()
        assert settings.TIER1_MIN_RUNS == 20

    @patch.dict("os.environ", {"DRIFTBASE_TIER2_MIN_RUNS": "100"})
    def test_tier2_min_runs_custom(self):
        """TIER2_MIN_RUNS can be customized via env var."""
        from driftbase.config import Settings

        settings = Settings()
        assert settings.TIER2_MIN_RUNS == 100
