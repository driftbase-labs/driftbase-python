"""
Tests for Phase 5: Real Signal Gains

Covers:
- Bigram tool sequence transition detection
- EMD-based latency distribution comparison
- Per-cluster drift analysis
- Integration with existing drift detection
"""

from __future__ import annotations

import json

import pytest

from driftbase.cli.cli_diff import fingerprint_from_runs
from driftbase.local.diff import compute_drift
from driftbase.local.task_clustering import (
    ClusterDriftResult,
    cluster_runs_by_task,
    compute_per_cluster_drift,
)
from driftbase.stats.emd import compute_latency_emd, compute_latency_emd_signal
from driftbase.stats.ngrams import (
    compute_bigram_distribution,
    compute_bigram_jsd,
    compute_bigrams,
)
from tests.fixtures.synthetic.generators import (
    bimodal_latency_drift_pair,
    no_drift_pair,
    single_cluster_drift_pair,
    tool_order_drift_pair,
)


class TestBigrams:
    """Tests for bigram extraction and JSD computation."""

    def test_compute_bigrams_basic(self) -> None:
        """Test basic bigram extraction."""
        tool_seq = '["tool_a", "tool_b", "tool_c"]'
        bigrams = compute_bigrams(tool_seq)
        assert bigrams == [("tool_a", "tool_b"), ("tool_b", "tool_c")]

    def test_compute_bigrams_single_tool(self) -> None:
        """Test bigram extraction with single tool (no bigrams)."""
        tool_seq = '["tool_a"]'
        bigrams = compute_bigrams(tool_seq)
        assert bigrams == []

    def test_compute_bigrams_empty(self) -> None:
        """Test bigram extraction with empty sequence."""
        assert compute_bigrams("[]") == []
        assert compute_bigrams("") == []
        assert compute_bigrams(None) == []

    def test_compute_bigram_distribution(self) -> None:
        """Test bigram frequency distribution."""
        sequences = [
            '["a", "b", "c"]',
            '["a", "b", "c"]',
            '["a", "c", "b"]',
        ]
        dist = compute_bigram_distribution(sequences)
        # Expected: (a,b): 2/6, (b,c): 2/6, (a,c): 1/6, (c,b): 1/6
        assert "('a', 'b')" in dist
        assert "('b', 'c')" in dist
        assert "('a', 'c')" in dist
        assert "('c', 'b')" in dist
        assert abs(dist["('a', 'b')"] - 2 / 6) < 0.01
        assert abs(dist["('b', 'c')"] - 2 / 6) < 0.01

    def test_compute_bigram_jsd(self) -> None:
        """Test JSD computation on bigram distributions."""
        # Identical distributions
        dist1 = {"('a', 'b')": 0.5, "('b', 'c')": 0.5}
        dist2 = {"('a', 'b')": 0.5, "('b', 'c')": 0.5}
        jsd = compute_bigram_jsd(dist1, dist2)
        assert jsd < 0.01  # Should be ~0 for identical

        # Different distributions
        dist3 = {"('a', 'c')": 0.5, "('c', 'b')": 0.5}
        jsd = compute_bigram_jsd(dist1, dist3)
        assert jsd > 0.5  # Should be high for completely different


class TestEMD:
    """Tests for EMD latency distribution comparison."""

    def test_compute_latency_emd_identical(self) -> None:
        """Test EMD with identical latency distributions."""
        baseline = [
            {"latency_ms": 1000},
            {"latency_ms": 1100},
            {"latency_ms": 900},
        ]
        current = [
            {"latency_ms": 1000},
            {"latency_ms": 1100},
            {"latency_ms": 900},
        ]
        emd = compute_latency_emd(baseline, current)
        assert emd < 10  # Should be very small for identical

    def test_compute_latency_emd_shifted(self) -> None:
        """Test EMD with shifted latency distribution."""
        baseline = [{"latency_ms": 1000} for _ in range(100)]
        current = [{"latency_ms": 2000} for _ in range(100)]  # 2x slower
        emd = compute_latency_emd(baseline, current)
        assert emd > 900  # Should be large for 1000ms shift

    def test_compute_latency_emd_signal(self) -> None:
        """Test EMD signal normalization."""
        baseline = [{"latency_ms": 1000} for _ in range(100)]
        current = [{"latency_ms": 2000} for _ in range(100)]
        signal = compute_latency_emd_signal(baseline, current)
        assert 0.0 <= signal <= 1.0
        assert signal > 0.7  # Should be high signal for 1000ms shift

    def test_emd_detects_bimodal_shift(self) -> None:
        """Test that EMD catches bimodal latency shifts."""
        baseline, current = bimodal_latency_drift_pair(n=200, seed=11)
        emd = compute_latency_emd(baseline, current)
        signal = compute_latency_emd_signal(baseline, current)
        assert emd > 200  # Should detect the shift
        assert signal > 0.3  # Should generate signal


class TestClustering:
    """Tests for task clustering."""

    def test_cluster_runs_by_task_basic(self) -> None:
        """Test basic clustering by (first_tool, input_length_bucket)."""
        runs = [
            {
                "tool_sequence": '["tool_a", "tool_b"]',
                "raw_prompt": "x" * 50,
            },  # tool_a:0-100
            {
                "tool_sequence": '["tool_a", "tool_c"]',
                "raw_prompt": "x" * 80,
            },  # tool_a:0-100
            {
                "tool_sequence": '["tool_b", "tool_d"]',
                "raw_prompt": "x" * 200,
            },  # tool_b:100-500
        ]
        clusters = cluster_runs_by_task(runs, max_clusters=5)
        assert "tool_a:0-100" in clusters
        assert "tool_b:100-500" in clusters
        assert len(clusters["tool_a:0-100"]) == 2
        assert len(clusters["tool_b:100-500"]) == 1

    def test_cluster_runs_max_clusters(self) -> None:
        """Test max_clusters limit."""
        runs = [
            {"tool_sequence": f'["tool_{i}"]', "raw_prompt": "x" * 50}
            for i in range(10)
        ]
        clusters = cluster_runs_by_task(runs, max_clusters=3)
        assert len(clusters) <= 3  # Should keep only top 3

    def test_compute_per_cluster_drift_no_common(self) -> None:
        """Test per-cluster drift with no common clusters."""
        baseline = [{"tool_sequence": '["tool_a"]', "raw_prompt": "x" * 50}] * 20
        current = [{"tool_sequence": '["tool_b"]', "raw_prompt": "x" * 200}] * 20
        results = compute_per_cluster_drift(baseline, current)
        assert results == []  # No common clusters

    def test_compute_per_cluster_drift_insufficient_data(self) -> None:
        """Test per-cluster drift with insufficient data per cluster."""
        baseline = [{"tool_sequence": '["tool_a"]', "raw_prompt": "x" * 50}] * 5
        current = [{"tool_sequence": '["tool_a"]', "raw_prompt": "x" * 50}] * 5
        results = compute_per_cluster_drift(baseline, current)
        assert results == []  # < 10 runs per cluster

    def test_single_cluster_drift_detection(self) -> None:
        """Test detection of drift in only one cluster."""
        baseline, current = single_cluster_drift_pair(n=300, seed=12)
        results = compute_per_cluster_drift(baseline, current, max_clusters=5)

        # Should find 3 clusters
        assert len(results) >= 1

        # Results should be sorted by drift score (descending)
        for i in range(len(results) - 1):
            assert results[i].drift_score >= results[i + 1].drift_score

        # First result should be the drifting cluster (tool_a)
        assert "tool_a" in results[0].cluster_id or "tool_a" in results[0].cluster_label


class TestIntegration:
    """Integration tests for new signals with existing drift detection."""

    def test_tool_order_drift_detected_by_bigrams(self) -> None:
        """Test that tool order changes are caught by bigram detection."""
        baseline, current = tool_order_drift_pair(n=200, seed=10)
        baseline_fp = fingerprint_from_runs(baseline, "v1", "production")
        current_fp = fingerprint_from_runs(current, "v2", "production")

        assert baseline_fp is not None
        assert current_fp is not None

        # Check bigram distributions differ
        baseline_bigrams = json.loads(baseline_fp.bigram_distribution or "{}")
        current_bigrams = json.loads(current_fp.bigram_distribution or "{}")

        # Baseline should have (a,b) and (b,c)
        # Current should have (a,c) and (c,b)
        assert "('tool_a', 'tool_b')" in baseline_bigrams
        assert "('tool_a', 'tool_c')" in current_bigrams

        report = compute_drift(
            baseline_fp,
            current_fp,
            baseline_runs=baseline,
            current_runs=current,
        )

        # Should detect drift via tool_sequence_transitions_drift
        assert report.tool_sequence_transitions_drift > 0.3

    def test_bimodal_latency_detected_by_emd(self) -> None:
        """Test that bimodal latency shifts are caught by EMD."""
        baseline, current = bimodal_latency_drift_pair(n=200, seed=11)
        baseline_fp = fingerprint_from_runs(baseline, "v1", "production")
        current_fp = fingerprint_from_runs(current, "v2", "production")

        assert baseline_fp is not None
        assert current_fp is not None

        report = compute_drift(
            baseline_fp,
            current_fp,
            baseline_runs=baseline,
            current_runs=current,
        )

        # latency_drift should be elevated due to EMD blend
        assert report.latency_drift > 0.2

    def test_no_drift_invariant_maintained(self) -> None:
        """Critical: no_drift fixture must stay < 0.05 with new signals."""
        baseline, current = no_drift_pair(n=200, seed=1)
        baseline_fp = fingerprint_from_runs(baseline, "v1", "production")
        current_fp = fingerprint_from_runs(current, "v2", "production")

        assert baseline_fp is not None
        assert current_fp is not None

        report = compute_drift(
            baseline_fp,
            current_fp,
            baseline_runs=baseline,
            current_runs=current,
        )

        # CRITICAL INVARIANT: no_drift must stay < 0.05
        assert report.drift_score < 0.05, (
            f"no_drift fixture triggered false positive: {report.drift_score:.4f} >= 0.05"
        )
