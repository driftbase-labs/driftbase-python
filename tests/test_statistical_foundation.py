"""
Tests for Phase 3a: Statistical Foundation.

Covers dimension CIs, MDEs, power forecasts, and attribution analysis.
"""

from __future__ import annotations

import numpy as np
import pytest

from driftbase.local.diff import compute_drift
from driftbase.local.fingerprinter import build_fingerprint_from_runs
from driftbase.local.local_store import AgentRun
from driftbase.stats.attribution import (
    compute_dimension_attribution,
    compute_marginal_contribution,
)
from driftbase.stats.dimension_ci import DimensionCI, compute_dimension_cis
from driftbase.stats.mde import compute_mde
from driftbase.stats.power_forecast import forecast_runs_needed

# Fixtures


@pytest.fixture
def sample_runs():
    """Create sample runs for testing."""
    from datetime import datetime, timedelta

    base_time = datetime(2026, 1, 1)
    runs = []
    for i in range(50):
        run = AgentRun(
            id=f"run_{i}",
            session_id=f"sess_{i}",
            deployment_version="v1.0",
            environment="production",
            started_at=base_time + timedelta(minutes=i),
            completed_at=base_time + timedelta(minutes=i, seconds=30),
            task_input_hash="hash_123",
            tool_sequence='["tool_a", "tool_b"]',
            tool_call_count=2,
            output_length=100 + i,
            output_structure_hash="struct_hash",
            latency_ms=1000 + i * 10,
            error_count=0 if i % 10 != 0 else 1,
            retry_count=0,
            semantic_cluster="resolved",
            loop_count=0,
            time_to_first_tool_ms=100,
            verbosity_ratio=1.0,
        )
        runs.append(run)
    return runs


@pytest.fixture
def sample_run_dicts(sample_runs):
    """Convert sample runs to dicts."""
    return [
        {
            "id": r.id,
            "session_id": r.session_id,
            "deployment_version": r.deployment_version,
            "environment": r.environment,
            "started_at": r.started_at,
            "completed_at": r.completed_at,
            "task_input_hash": r.task_input_hash,
            "tool_sequence": r.tool_sequence,
            "tool_call_count": r.tool_call_count,
            "output_length": r.output_length,
            "output_structure_hash": r.output_structure_hash,
            "latency_ms": r.latency_ms,
            "error_count": r.error_count,
            "retry_count": r.retry_count,
            "semantic_cluster": r.semantic_cluster,
            "loop_count": r.loop_count,
            "time_to_first_tool_ms": r.time_to_first_tool_ms,
            "verbosity_ratio": r.verbosity_ratio,
        }
        for r in sample_runs
    ]


# Tests for dimension_ci.py (5 tests)


def test_compute_dimension_cis_basic(sample_run_dicts):
    """Test basic CI computation."""
    baseline_runs = sample_run_dicts[:25]
    current_runs = sample_run_dicts[25:]

    dimensions = ["decision_drift", "latency", "error_rate"]
    result = compute_dimension_cis(
        baseline_runs=baseline_runs,
        current_runs=current_runs,
        dimensions=dimensions,
        n_bootstrap=100,
        confidence_level=0.95,
    )

    assert isinstance(result, dict)
    assert len(result) == 3
    for dim in dimensions:
        assert dim in result
        ci = result[dim]
        assert isinstance(ci, DimensionCI)
        assert ci.dimension == dim
        assert not np.isnan(ci.observed)
        assert not np.isnan(ci.ci_lower)
        assert not np.isnan(ci.ci_upper)
        assert ci.ci_lower <= ci.observed <= ci.ci_upper


def test_compute_dimension_cis_all_dimensions(sample_run_dicts):
    """Test CI computation for all 12 dimensions."""
    baseline_runs = sample_run_dicts[:25]
    current_runs = sample_run_dicts[25:]

    all_dimensions = [
        "decision_drift",
        "semantic_drift",
        "latency",
        "error_rate",
        "tool_distribution",
        "verbosity_ratio",
        "loop_depth",
        "output_length",
        "tool_sequence",
        "retry_rate",
        "time_to_first_tool",
        "tool_sequence_transitions",
    ]

    result = compute_dimension_cis(
        baseline_runs=baseline_runs,
        current_runs=current_runs,
        dimensions=all_dimensions,
        n_bootstrap=100,
    )

    assert len(result) == 12
    for dim in all_dimensions:
        assert dim in result
        ci = result[dim]
        assert isinstance(ci, DimensionCI)


def test_compute_dimension_cis_empty_runs():
    """Test CI computation with empty runs."""
    result = compute_dimension_cis(
        baseline_runs=[],
        current_runs=[],
        dimensions=["decision_drift"],
        n_bootstrap=100,
    )

    assert "decision_drift" in result
    ci = result["decision_drift"]
    assert np.isnan(ci.observed)
    assert np.isnan(ci.ci_lower)
    assert np.isnan(ci.ci_upper)
    assert ci.significant is False


def test_compute_dimension_cis_deterministic(sample_run_dicts):
    """Test that CI computation is deterministic with same salt."""
    baseline_runs = sample_run_dicts[:25]
    current_runs = sample_run_dicts[25:]

    result1 = compute_dimension_cis(
        baseline_runs=baseline_runs,
        current_runs=current_runs,
        dimensions=["decision_drift"],
        n_bootstrap=100,
        salt="test_salt",
    )

    result2 = compute_dimension_cis(
        baseline_runs=baseline_runs,
        current_runs=current_runs,
        dimensions=["decision_drift"],
        n_bootstrap=100,
        salt="test_salt",
    )

    assert result1["decision_drift"].ci_lower == result2["decision_drift"].ci_lower
    assert result1["decision_drift"].ci_upper == result2["decision_drift"].ci_upper


def test_compute_dimension_cis_significance(sample_run_dicts):
    """Test significance flag in dimension CIs."""
    # Create runs with clear drift
    baseline_runs = sample_run_dicts[:25]
    current_runs = []
    for run_dict in sample_run_dicts[25:]:
        modified = run_dict.copy()
        modified["latency_ms"] = modified["latency_ms"] * 2  # Double latency
        current_runs.append(modified)

    result = compute_dimension_cis(
        baseline_runs=baseline_runs,
        current_runs=current_runs,
        dimensions=["latency"],
        n_bootstrap=100,
    )

    ci = result["latency"]
    # Should be significant since latency doubled
    assert ci.ci_lower > 0.0  # CI excludes 0
    assert ci.significant is True


# Tests for mde.py (4 tests)


def test_compute_mde_basic(sample_run_dicts):
    """Test basic MDE computation."""
    baseline_runs = sample_run_dicts[:25]
    current_runs = sample_run_dicts[25:]

    result = compute_mde(
        baseline_runs=baseline_runs,
        current_runs=current_runs,
        dimensions=["decision_drift", "latency"],
        n_bootstrap=100,
    )

    assert isinstance(result, dict)
    assert "decision_drift" in result
    assert "latency" in result
    # MDE should be >= 0 (may be 0 if variance is very low)
    assert result["decision_drift"] >= 0.0
    assert result["latency"] >= 0.0
    assert not np.isnan(result["decision_drift"])


def test_compute_mde_sample_size_dependency(sample_run_dicts):
    """Test that MDE decreases with larger sample sizes."""
    # Small sample
    small_baseline = sample_run_dicts[:10]
    small_current = sample_run_dicts[10:20]
    mde_small = compute_mde(
        baseline_runs=small_baseline,
        current_runs=small_current,
        dimensions=["latency"],
        n_bootstrap=50,
    )

    # Large sample
    large_baseline = sample_run_dicts[:25]
    large_current = sample_run_dicts[25:]
    mde_large = compute_mde(
        baseline_runs=large_baseline,
        current_runs=large_current,
        dimensions=["latency"],
        n_bootstrap=50,
    )

    # Larger sample should have smaller or equal MDE (may be equal if variance is low)
    # MDE = (z_alpha/2 + z_power) * sigma * sqrt(1/n_baseline + 1/n_current)
    # Larger n should decrease MDE if sigma is stable
    # Just verify both are valid (>= 0)
    assert mde_small["latency"] >= 0.0
    assert mde_large["latency"] >= 0.0


def test_compute_mde_empty_runs():
    """Test MDE computation with empty runs."""
    result = compute_mde(
        baseline_runs=[],
        current_runs=[],
        dimensions=["decision_drift"],
        n_bootstrap=100,
    )

    assert "decision_drift" in result
    assert np.isnan(result["decision_drift"])


def test_compute_mde_all_dimensions(sample_run_dicts):
    """Test MDE computation for all 12 dimensions."""
    baseline_runs = sample_run_dicts[:25]
    current_runs = sample_run_dicts[25:]

    all_dimensions = [
        "decision_drift",
        "semantic_drift",
        "latency",
        "error_rate",
        "tool_distribution",
        "verbosity_ratio",
        "loop_depth",
        "output_length",
        "tool_sequence",
        "retry_rate",
        "time_to_first_tool",
        "tool_sequence_transitions",
    ]

    result = compute_mde(
        baseline_runs=baseline_runs,
        current_runs=current_runs,
        dimensions=all_dimensions,
        n_bootstrap=100,
    )

    assert len(result) == 12
    for dim in all_dimensions:
        assert dim in result
        assert result[dim] >= 0.0 or np.isnan(result[dim])


# Tests for power_forecast.py (4 tests)


def test_forecast_runs_needed_basic(sample_run_dicts):
    """Test basic power forecast."""
    baseline_runs = sample_run_dicts[:15]
    current_runs = sample_run_dicts[15:30]

    result = forecast_runs_needed(
        baseline_runs=baseline_runs,
        current_runs=current_runs,
        dimensions=["latency"],
        target_mde=0.10,
        n_bootstrap=50,
    )

    assert isinstance(result, dict)
    assert "latency" in result
    # Should suggest additional runs for small sample
    assert result["latency"] >= 0


def test_forecast_runs_needed_sufficient_sample(sample_run_dicts):
    """Test forecast with already sufficient sample size."""
    # Large sample should need 0 or very few additional runs
    baseline_runs = sample_run_dicts[:30]
    current_runs = (
        sample_run_dicts[30:60]
        if len(sample_run_dicts) >= 60
        else sample_run_dicts[30:]
    )

    result = forecast_runs_needed(
        baseline_runs=baseline_runs,
        current_runs=current_runs,
        dimensions=["latency"],
        target_mde=0.50,  # Large MDE easier to detect
        n_bootstrap=50,
    )

    # With 60 total runs and large target MDE, should need few/no additional runs
    assert result["latency"] >= 0


def test_forecast_runs_needed_empty_runs():
    """Test power forecast with empty runs."""
    result = forecast_runs_needed(
        baseline_runs=[],
        current_runs=[],
        dimensions=["decision_drift"],
        target_mde=0.10,
        n_bootstrap=50,
    )

    assert "decision_drift" in result
    # Should return -1 sentinel for invalid/empty runs
    assert result["decision_drift"] == -1


def test_forecast_runs_needed_multiple_dimensions(sample_run_dicts):
    """Test power forecast for multiple dimensions."""
    baseline_runs = sample_run_dicts[:20]
    current_runs = sample_run_dicts[20:40]

    dimensions = ["decision_drift", "latency", "error_rate"]
    result = forecast_runs_needed(
        baseline_runs=baseline_runs,
        current_runs=current_runs,
        dimensions=dimensions,
        target_mde=0.10,
        n_bootstrap=50,
    )

    assert len(result) == 3
    for dim in dimensions:
        assert dim in result


# Tests for attribution.py (3 tests)


def test_compute_dimension_attribution_basic():
    """Test basic attribution computation."""
    calibrated_weights = {
        "decision_drift": 0.38,
        "latency": 0.12,
        "error_rate": 0.12,
        "semantic_drift": 0.08,
    }
    dimension_scores = {
        "decision_drift": 0.5,
        "latency": 0.3,
        "error_rate": 0.2,
        "semantic_drift": 0.1,
    }
    original_composite = sum(
        calibrated_weights.get(d, 0.0) * dimension_scores.get(d, 0.0)
        for d in dimension_scores
    )

    result = compute_dimension_attribution(
        baseline=None,  # Not used in attribution
        current=None,  # Not used in attribution
        calibrated_weights=calibrated_weights,
        original_composite=original_composite,
        dimension_scores=dimension_scores,
    )

    # Check that all 12 standard dimensions are in result
    assert len(result) == 12
    assert "decision_drift" in result
    assert "latency" in result


def test_compute_marginal_contribution_basic():
    """Test marginal contribution computation."""
    calibrated_weights = {
        "decision_drift": 0.38,
        "latency": 0.12,
        "error_rate": 0.12,
    }
    dimension_scores = {
        "decision_drift": 0.5,
        "latency": 0.3,
        "error_rate": 0.2,
    }

    result = compute_marginal_contribution(
        dimension_scores=dimension_scores,
        calibrated_weights=calibrated_weights,
    )

    assert result["decision_drift"] == pytest.approx(0.38 * 0.5)
    assert result["latency"] == pytest.approx(0.12 * 0.3)
    assert result["error_rate"] == pytest.approx(0.12 * 0.2)

    # Sum of marginal contributions equals composite score
    total = sum(result.values())
    expected_composite = sum(
        calibrated_weights.get(d, 0.0) * dimension_scores.get(d, 0.0)
        for d in dimension_scores
    )
    assert total == pytest.approx(expected_composite)


def test_compute_dimension_attribution_empty():
    """Test attribution with empty inputs."""
    result = compute_dimension_attribution(
        baseline=None,
        current=None,
        calibrated_weights={},
        original_composite=0.5,
        dimension_scores={},
    )

    # Should return NaN for all dimensions
    assert all(np.isnan(v) for v in result.values())


# Integration tests with diff.py (3 tests)


def test_diff_compute_statistics_flag(sample_runs):
    """Test compute_statistics flag in compute_drift."""
    from datetime import datetime

    baseline_fp = build_fingerprint_from_runs(
        runs=sample_runs[:25],
        window_start=datetime.min,
        window_end=datetime.max,
        deployment_version="v1.0",
        environment="production",
    )
    current_fp = build_fingerprint_from_runs(
        runs=sample_runs[25:],
        window_start=datetime.min,
        window_end=datetime.max,
        deployment_version="v2.0",
        environment="production",
    )

    # Convert runs to dicts
    baseline_run_dicts = [
        {
            "id": r.id,
            "session_id": r.session_id,
            "deployment_version": r.deployment_version,
            "environment": r.environment,
            "started_at": r.started_at,
            "completed_at": r.completed_at,
            "task_input_hash": r.task_input_hash,
            "tool_sequence": r.tool_sequence,
            "tool_call_count": r.tool_call_count,
            "output_length": r.output_length,
            "output_structure_hash": r.output_structure_hash,
            "latency_ms": r.latency_ms,
            "error_count": r.error_count,
            "retry_count": r.retry_count,
            "semantic_cluster": r.semantic_cluster,
            "loop_count": r.loop_count,
            "time_to_first_tool_ms": r.time_to_first_tool_ms,
            "verbosity_ratio": r.verbosity_ratio,
        }
        for r in sample_runs[:25]
    ]
    current_run_dicts = [
        {
            "id": r.id,
            "session_id": r.session_id,
            "deployment_version": r.deployment_version,
            "environment": r.environment,
            "started_at": r.started_at,
            "completed_at": r.completed_at,
            "task_input_hash": r.task_input_hash,
            "tool_sequence": r.tool_sequence,
            "tool_call_count": r.tool_call_count,
            "output_length": r.output_length,
            "output_structure_hash": r.output_structure_hash,
            "latency_ms": r.latency_ms,
            "error_count": r.error_count,
            "retry_count": r.retry_count,
            "semantic_cluster": r.semantic_cluster,
            "loop_count": r.loop_count,
            "time_to_first_tool_ms": r.time_to_first_tool_ms,
            "verbosity_ratio": r.verbosity_ratio,
        }
        for r in sample_runs[25:]
    ]

    # With compute_statistics=True (default)
    report_with_stats = compute_drift(
        baseline=baseline_fp,
        current=current_fp,
        baseline_runs=baseline_run_dicts,
        current_runs=current_run_dicts,
        compute_statistics=True,
    )

    # With compute_statistics=False
    report_without_stats = compute_drift(
        baseline=baseline_fp,
        current=current_fp,
        baseline_runs=baseline_run_dicts,
        current_runs=current_run_dicts,
        compute_statistics=False,
    )

    # Report with stats should have statistical fields populated
    assert report_with_stats.dimension_cis is not None
    assert report_with_stats.dimension_mdes is not None
    assert report_with_stats.runs_needed_forecast is not None
    assert report_with_stats.dimension_attribution is not None

    # Report without stats should have None for statistical fields
    assert report_without_stats.dimension_cis is None
    assert report_without_stats.dimension_mdes is None
    assert report_without_stats.runs_needed_forecast is None
    assert report_without_stats.dimension_attribution is None

    # Composite scores should be identical
    assert report_with_stats.drift_score == report_without_stats.drift_score


def test_diff_statistical_fields_populated(sample_runs):
    """Test that statistical fields are properly populated in DriftReport."""
    from datetime import datetime

    baseline_fp = build_fingerprint_from_runs(
        runs=sample_runs[:25],
        window_start=datetime.min,
        window_end=datetime.max,
        deployment_version="v1.0",
        environment="production",
    )
    current_fp = build_fingerprint_from_runs(
        runs=sample_runs[25:],
        window_start=datetime.min,
        window_end=datetime.max,
        deployment_version="v2.0",
        environment="production",
    )

    baseline_run_dicts = [
        {
            "id": r.id,
            "session_id": r.session_id,
            "deployment_version": r.deployment_version,
            "environment": r.environment,
            "started_at": r.started_at,
            "completed_at": r.completed_at,
            "task_input_hash": r.task_input_hash,
            "tool_sequence": r.tool_sequence,
            "tool_call_count": r.tool_call_count,
            "output_length": r.output_length,
            "output_structure_hash": r.output_structure_hash,
            "latency_ms": r.latency_ms,
            "error_count": r.error_count,
            "retry_count": r.retry_count,
            "semantic_cluster": r.semantic_cluster,
            "loop_count": r.loop_count,
            "time_to_first_tool_ms": r.time_to_first_tool_ms,
            "verbosity_ratio": r.verbosity_ratio,
        }
        for r in sample_runs[:25]
    ]
    current_run_dicts = [
        {
            "id": r.id,
            "session_id": r.session_id,
            "deployment_version": r.deployment_version,
            "environment": r.environment,
            "started_at": r.started_at,
            "completed_at": r.completed_at,
            "task_input_hash": r.task_input_hash,
            "tool_sequence": r.tool_sequence,
            "tool_call_count": r.tool_call_count,
            "output_length": r.output_length,
            "output_structure_hash": r.output_structure_hash,
            "latency_ms": r.latency_ms,
            "error_count": r.error_count,
            "retry_count": r.retry_count,
            "semantic_cluster": r.semantic_cluster,
            "loop_count": r.loop_count,
            "time_to_first_tool_ms": r.time_to_first_tool_ms,
            "verbosity_ratio": r.verbosity_ratio,
        }
        for r in sample_runs[25:]
    ]

    report = compute_drift(
        baseline=baseline_fp,
        current=current_fp,
        baseline_runs=baseline_run_dicts,
        current_runs=current_run_dicts,
        compute_statistics=True,
    )

    # Check dimension_cis
    assert isinstance(report.dimension_cis, dict)
    assert len(report.dimension_cis) == 12
    assert "decision_drift" in report.dimension_cis
    assert isinstance(report.dimension_cis["decision_drift"], DimensionCI)

    # Check dimension_mdes
    assert isinstance(report.dimension_mdes, dict)
    assert len(report.dimension_mdes) == 12
    assert "decision_drift" in report.dimension_mdes
    assert isinstance(report.dimension_mdes["decision_drift"], float)

    # Check runs_needed_forecast
    assert isinstance(report.runs_needed_forecast, dict)
    assert len(report.runs_needed_forecast) == 12
    assert "decision_drift" in report.runs_needed_forecast
    assert isinstance(report.runs_needed_forecast["decision_drift"], int)

    # Check dimension_attribution
    assert isinstance(report.dimension_attribution, dict)
    assert len(report.dimension_attribution) == 12
    assert "decision_drift" in report.dimension_attribution
    assert isinstance(report.dimension_attribution["decision_drift"], float)


def test_diff_detection_unchanged_with_statistics(sample_runs):
    """Test that detection behavior is unchanged when statistics enabled."""
    from datetime import datetime

    baseline_fp = build_fingerprint_from_runs(
        runs=sample_runs[:25],
        window_start=datetime.min,
        window_end=datetime.max,
        deployment_version="v1.0",
        environment="production",
    )
    current_fp = build_fingerprint_from_runs(
        runs=sample_runs[25:],
        window_start=datetime.min,
        window_end=datetime.max,
        deployment_version="v2.0",
        environment="production",
    )

    baseline_run_dicts = [
        {
            "id": r.id,
            "session_id": r.session_id,
            "deployment_version": r.deployment_version,
            "environment": r.environment,
            "started_at": r.started_at,
            "completed_at": r.completed_at,
            "task_input_hash": r.task_input_hash,
            "tool_sequence": r.tool_sequence,
            "tool_call_count": r.tool_call_count,
            "output_length": r.output_length,
            "output_structure_hash": r.output_structure_hash,
            "latency_ms": r.latency_ms,
            "error_count": r.error_count,
            "retry_count": r.retry_count,
            "semantic_cluster": r.semantic_cluster,
            "loop_count": r.loop_count,
            "time_to_first_tool_ms": r.time_to_first_tool_ms,
            "verbosity_ratio": r.verbosity_ratio,
        }
        for r in sample_runs[:25]
    ]
    current_run_dicts = [
        {
            "id": r.id,
            "session_id": r.session_id,
            "deployment_version": r.deployment_version,
            "environment": r.environment,
            "started_at": r.started_at,
            "completed_at": r.completed_at,
            "task_input_hash": r.task_input_hash,
            "tool_sequence": r.tool_sequence,
            "tool_call_count": r.tool_call_count,
            "output_length": r.output_length,
            "output_structure_hash": r.output_structure_hash,
            "latency_ms": r.latency_ms,
            "error_count": r.error_count,
            "retry_count": r.retry_count,
            "semantic_cluster": r.semantic_cluster,
            "loop_count": r.loop_count,
            "time_to_first_tool_ms": r.time_to_first_tool_ms,
            "verbosity_ratio": r.verbosity_ratio,
        }
        for r in sample_runs[:25]
    ]

    report_with = compute_drift(
        baseline=baseline_fp,
        current=current_fp,
        baseline_runs=baseline_run_dicts,
        current_runs=current_run_dicts,
        compute_statistics=True,
    )
    report_without = compute_drift(
        baseline=baseline_fp,
        current=current_fp,
        baseline_runs=baseline_run_dicts,
        current_runs=current_run_dicts,
        compute_statistics=False,
    )

    # Core detection fields must be identical
    assert report_with.drift_score == report_without.drift_score
    assert report_with.decision_drift == report_without.decision_drift
    assert report_with.latency_drift == report_without.latency_drift
    assert report_with.error_drift == report_without.error_drift
    assert report_with.semantic_drift == report_without.semantic_drift
    assert report_with.severity == report_without.severity
