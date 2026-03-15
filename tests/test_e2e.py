"""
E2E tests for bootstrap confidence interval in drift reports.
"""

from __future__ import annotations

import time
import unittest
from datetime import datetime, timezone
from uuid import uuid4

from driftbase.cli.cli_diff import fingerprint_from_runs
from driftbase.local.diff import compute_drift


def _make_run_dict(
    version: str,
    tool_sequence: str = '["tool_a","tool_b"]',
    env: str = "production",
) -> dict:
    """Minimal run dict for fingerprinting."""
    now = datetime.now(timezone.utc)
    return {
        "id": str(uuid4()),
        "session_id": str(uuid4()),
        "deployment_version": version,
        "environment": env,
        "started_at": now,
        "completed_at": now,
        "task_input_hash": "abc",
        "tool_sequence": tool_sequence,
        "tool_call_count": 2,
        "output_length": 10,
        "output_structure_hash": "out",
        "latency_ms": 100,
        "error_count": 0,
        "retry_count": 0,
        "semantic_cluster": "cluster_none",
    }


def _make_run_dicts(
    version: str, n: int, tool_sequences: list[str] | None = None
) -> list[dict]:
    """Create n run dicts for a version. If tool_sequences provided, cycle through them."""
    if tool_sequences is None:
        tool_sequences = ['["tool_a","tool_b"]', '["tool_a"]', '["tool_b","tool_a"]']
    return [
        _make_run_dict(version, tool_sequence=tool_sequences[i % len(tool_sequences)])
        for i in range(n)
    ]


class TestBootstrapE2E(unittest.TestCase):
    """Bootstrap CI and sample-size warning assertions."""

    def test_bootstrap_confidence_interval_60_runs(self) -> None:
        """With 60 runs per version: CI fields set, point in interval, no sample warning, <500ms."""
        baseline_run_dicts = _make_run_dicts("v1", 60)
        current_run_dicts = _make_run_dicts("v2", 60)
        baseline_fp = fingerprint_from_runs(baseline_run_dicts, "v1", "production")
        current_fp = fingerprint_from_runs(current_run_dicts, "v2", "production")
        self.assertIsNotNone(baseline_fp)
        self.assertIsNotNone(current_fp)

        t0 = time.perf_counter()
        report = compute_drift(
            baseline_fp,
            current_fp,
            baseline_runs=baseline_run_dicts,
            current_runs=current_run_dicts,
        )
        elapsed = time.perf_counter() - t0

        self.assertIsNotNone(report.drift_score_lower)
        self.assertIsNotNone(report.drift_score_upper)
        self.assertIsInstance(report.drift_score_lower, float)
        self.assertIsInstance(report.drift_score_upper, float)
        self.assertLessEqual(
            report.drift_score_lower,
            report.drift_score,
            "drift_score_lower should be <= point estimate",
        )
        self.assertGreaterEqual(
            report.drift_score_upper,
            report.drift_score,
            "drift_score_upper should be >= point estimate",
        )
        self.assertEqual(report.confidence_interval_pct, 95)
        self.assertEqual(report.bootstrap_iterations, 500)
        self.assertFalse(
            report.sample_size_warning,
            "With 60 runs per version, sample_size_warning should be False",
        )
        self.assertLess(
            elapsed,
            0.5,
            f"Bootstrap should complete in under 500ms, took {elapsed:.2f}s",
        )

    def test_bootstrap_sample_size_warning_15_runs(self) -> None:
        """With 15 runs per version: sample_size_warning is True."""
        baseline_run_dicts = _make_run_dicts("v1", 15)
        current_run_dicts = _make_run_dicts("v2", 15)
        baseline_fp = fingerprint_from_runs(baseline_run_dicts, "v1", "production")
        current_fp = fingerprint_from_runs(current_run_dicts, "v2", "production")
        self.assertIsNotNone(baseline_fp)
        self.assertIsNotNone(current_fp)

        report = compute_drift(
            baseline_fp,
            current_fp,
            baseline_runs=baseline_run_dicts,
            current_runs=current_run_dicts,
        )

        self.assertTrue(
            report.sample_size_warning,
            "With 15 runs per version, sample_size_warning should be True",
        )
        self.assertEqual(report.confidence_interval_pct, 95)
        self.assertEqual(report.bootstrap_iterations, 500)


if __name__ == "__main__":
    unittest.main()
