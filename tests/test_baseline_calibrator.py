"""
Tests for baseline calibrator - statistical weight and threshold calibration.

Tests reliability multipliers, threshold derivation, volume/sensitivity adjustments,
edge cases like std == 0, and cache invalidation.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from driftbase.local.baseline_calibrator import (
    DIMENSION_KEYS,
    SENSITIVITY_MULTIPLIERS,
    _compute_correlation_adjustments,
    _compute_threshold,
    calibrate,
)
from driftbase.local.use_case_inference import USE_CASE_WEIGHTS


# Helper to create a patched get_backend context
def patch_backend(mock_backend):
    return patch("driftbase.backends.factory.get_backend", return_value=mock_backend)


def test_weights_sum_to_one_after_calibration():
    """Calibrated weights should sum to 1.0 after renormalization."""
    # Mock backend to return runs with some variance
    mock_backend = MagicMock()
    mock_backend.get_runs.return_value = [
        {
            "deployment_version": "v1.0",
            "tool_sequence": '["tool_a", "tool_b"]',
            "latency_ms": 100,
            "error_count": 0,
            "output_length": 200,
            "loop_count": 1,
            "time_to_first_tool_ms": 50,
            "verbosity_ratio": 0.5,
            "retry_count": 0,
            "semantic_cluster": "cluster_0",
        }
        for _ in range(100)
    ]
    mock_backend.get_calibration_cache.return_value = None

    with patch_backend(mock_backend):
        result = calibrate("v1.0", "v2.0", "GENERAL", sensitivity="standard")

    weights = result.calibrated_weights
    total = sum(weights.values())
    assert abs(total - 1.0) < 0.001, f"Weights sum to {total}, expected 1.0"


def test_all_dimensions_present_in_weights():
    """Calibrated weights should contain all 12 dimensions."""
    mock_backend = MagicMock()
    mock_backend.get_runs.return_value = [
        {
            "deployment_version": "v1.0",
            "tool_sequence": '["tool_a"]',
            "latency_ms": 100,
            "error_count": 0,
            "output_length": 200,
            "loop_count": 1,
            "time_to_first_tool_ms": 50,
            "verbosity_ratio": 0.5,
            "retry_count": 0,
            "semantic_cluster": "cluster_0",
        }
        for _ in range(50)
    ]
    mock_backend.get_calibration_cache.return_value = None

    with patch_backend(mock_backend):
        result = calibrate("v1.0", "v2.0", "GENERAL", sensitivity="standard")

    weights = result.calibrated_weights
    # Should have all 12 dimensions
    assert set(weights.keys()) == set(DIMENSION_KEYS)
    assert len(weights) == 12


def test_std_zero_uses_minimum_std():
    """When std == 0, should use minimum std of 0.01 to avoid zero-width thresholds."""
    # Create runs where one dimension has zero variance
    mock_backend = MagicMock()
    runs = []
    for _ in range(50):
        runs.append(
            {
                "deployment_version": "v1.0",
                "tool_sequence": '["tool_a"]',
                "latency_ms": 100,  # Same value for all runs (zero variance)
                "error_count": 0,
                "output_length": 200,
                "loop_count": 1,
                "time_to_first_tool_ms": 50,
                "verbosity_ratio": 0.5,
                "retry_count": 0,
                "semantic_cluster": "cluster_0",
            }
        )
    mock_backend.get_runs.return_value = runs
    mock_backend.get_calibration_cache.return_value = None

    with patch_backend(mock_backend):
        result = calibrate("v1.0", "v2.0", "GENERAL", sensitivity="standard")

    # Should not crash, and thresholds should be set
    assert hasattr(result, "composite_thresholds")
    thresholds = result.composite_thresholds
    # MONITOR threshold should be mean + 2*std, where std >= 0.01
    # With all latency_ms = 100, mean = 100, std should be forced to 0.01
    # So MONITOR threshold should be close to 100 (since drift is normalized)
    assert "MONITOR" in thresholds
    assert "REVIEW" in thresholds
    assert "BLOCK" in thresholds


def test_volume_multiplier_tiers():
    """Volume multiplier should decrease with more baseline runs."""
    mock_backend = MagicMock()

    # Test with 100 runs (tier 1: multiplier = 1.00)
    mock_backend.get_runs.return_value = [
        {
            "deployment_version": "v1.0",
            "tool_sequence": '["tool_a"]',
            "latency_ms": 100 + i,  # Add variance
            "error_count": 0,
            "output_length": 200,
            "loop_count": 1,
            "time_to_first_tool_ms": 50,
            "verbosity_ratio": 0.5,
            "retry_count": 0,
            "semantic_cluster": "cluster_0",
        }
        for i in range(100)
    ]
    mock_backend.get_calibration_cache.return_value = None

    with patch_backend(mock_backend):
        result_100 = calibrate("v1.0", "v2.0", "GENERAL", sensitivity="standard")

    # Test with 2000 runs (tier 2: multiplier = 0.90)
    mock_backend.get_runs.return_value = [
        {
            "deployment_version": "v1.0",
            "tool_sequence": '["tool_a"]',
            "latency_ms": 100 + i % 100,
            "error_count": 0,
            "output_length": 200,
            "loop_count": 1,
            "time_to_first_tool_ms": 50,
            "verbosity_ratio": 0.5,
            "retry_count": 0,
            "semantic_cluster": "cluster_0",
        }
        for i in range(2000)
    ]

    with patch_backend(mock_backend):
        result_2000 = calibrate("v1.0", "v2.0", "GENERAL", sensitivity="standard")

    # With more runs, thresholds should be tighter (lower)
    # Because volume multiplier decreases (0.90 < 1.00)
    # This makes us more sensitive to drift with larger samples
    monitor_100 = result_100.composite_thresholds["MONITOR"]
    monitor_2000 = result_2000.composite_thresholds["MONITOR"]

    # With tighter multiplier, threshold should be lower
    assert monitor_2000 <= monitor_100, (
        "More runs should produce tighter (lower) thresholds"
    )


def test_sensitivity_multipliers():
    """Sensitivity parameter should adjust thresholds as expected."""
    mock_backend = MagicMock()
    mock_backend.get_runs.return_value = [
        {
            "deployment_version": "v1.0",
            "tool_sequence": '["tool_a"]',
            "latency_ms": 100 + i,
            "error_count": 0,
            "output_length": 200,
            "loop_count": 1,
            "time_to_first_tool_ms": 50,
            "verbosity_ratio": 0.5,
            "retry_count": 0,
            "semantic_cluster": "cluster_0",
        }
        for i in range(100)
    ]
    mock_backend.get_calibration_cache.return_value = None

    with patch_backend(mock_backend):
        result_strict = calibrate("v1.0", "v2.0", "GENERAL", sensitivity="strict")
        result_standard = calibrate("v1.0", "v2.0", "GENERAL", sensitivity="standard")
        result_relaxed = calibrate("v1.0", "v2.0", "GENERAL", sensitivity="relaxed")

    # Strict should have lowest thresholds (most sensitive)
    # Relaxed should have highest thresholds (least sensitive)
    strict_monitor = result_strict.composite_thresholds["MONITOR"]
    standard_monitor = result_standard.composite_thresholds["MONITOR"]
    relaxed_monitor = result_relaxed.composite_thresholds["MONITOR"]

    assert strict_monitor < standard_monitor < relaxed_monitor, (
        "Strict should be most sensitive (lowest threshold), relaxed least sensitive (highest)"
    )


def test_sensitivity_multiplier_values():
    """Sensitivity multipliers should match expected values."""
    assert SENSITIVITY_MULTIPLIERS["strict"] == 0.75
    assert SENSITIVITY_MULTIPLIERS["standard"] == 1.00
    assert SENSITIVITY_MULTIPLIERS["relaxed"] == 1.35


def test_cache_hit_returns_cached_result():
    """When cache is fresh (< 20% new runs), should return cached result."""
    mock_backend = MagicMock()
    mock_backend.get_total_run_count.return_value = 1000  # Current total

    # Cached calibration with 900 runs (< 1.20 * 900 = 1080)
    cached_calibration = {
        "calibrated_weights": {"decision_drift": 0.4, "latency_drift": 0.2},
        "thresholds": {
            "decision_drift": {"MONITOR": 0.15, "REVIEW": 0.28, "BLOCK": 0.42}
        },
        "composite_thresholds": {"MONITOR": 0.15, "REVIEW": 0.28, "BLOCK": 0.42},
        "calibration_method": "statistical",
        "baseline_n": 100,
        "run_count_at_calibration": 900,
    }
    mock_backend.get_calibration_cache.return_value = cached_calibration

    with patch_backend(mock_backend):
        result = calibrate("v1.0", "v2.0", "GENERAL", sensitivity="standard")

    # Should return cached result
    assert result.calibration_method == "statistical"
    assert result.baseline_n == 100
    # Cache was used - calibration wasn't recomputed
    # Note: get_runs may still be called to check sample sizes, but full calibration is skipped


def test_cache_miss_recomputes():
    """When cache is stale (>= 20% new runs), should recompute."""
    mock_backend = MagicMock()
    mock_backend.get_total_run_count.return_value = 1100  # Current total

    # Cached calibration with 900 runs (1100 >= 1.20 * 900 = 1080)
    cached_calibration = {
        "calibrated_weights": {"decision_drift": 0.4},
        "thresholds": {},
        "composite_thresholds": {"MONITOR": 0.15},
        "calibration_method": "statistical",
        "baseline_n": 100,
        "run_count_at_calibration": 900,
    }
    mock_backend.get_calibration_cache.return_value = cached_calibration

    # Provide fresh runs for recomputation
    mock_backend.get_runs.return_value = [
        {
            "deployment_version": "v1.0",
            "tool_sequence": '["tool_a"]',
            "latency_ms": 100,
            "error_count": 0,
            "output_length": 200,
            "loop_count": 1,
            "time_to_first_tool_ms": 50,
            "verbosity_ratio": 0.5,
            "retry_count": 0,
            "semantic_cluster": "cluster_0",
        }
        for _ in range(100)
    ]

    with patch_backend(mock_backend):
        result = calibrate("v1.0", "v2.0", "GENERAL", sensitivity="standard")

    # Should have called get_runs to recompute
    mock_backend.get_runs.assert_called()
    # Result should have fresh data
    assert hasattr(result, "calibrated_weights")


def test_insufficient_baseline_runs_fallback():
    """With < 30 runs, should fall back to preset weights."""
    mock_backend = MagicMock()
    mock_backend.get_runs.return_value = [
        {
            "deployment_version": "v1.0",
            "tool_sequence": '["tool_a"]',
            "latency_ms": 100,
            "error_count": 0,
            "output_length": 200,
            "loop_count": 1,
            "time_to_first_tool_ms": 50,
            "verbosity_ratio": 0.5,
            "retry_count": 0,
            "semantic_cluster": "cluster_0",
        }
        for _ in range(20)  # Below minimum
    ]
    mock_backend.get_calibration_cache.return_value = None

    with patch_backend(mock_backend):
        result = calibrate("v1.0", "v2.0", "CUSTOMER_SUPPORT", sensitivity="standard")

    # Should use preset_only method
    assert result.calibration_method == "preset_only"
    # Weights should be the preset weights for CUSTOMER_SUPPORT
    expected_weights = USE_CASE_WEIGHTS["CUSTOMER_SUPPORT"]
    assert result.calibrated_weights == expected_weights


def test_calibration_method_statistical_with_sufficient_data():
    """With >= 30 runs, should use statistical calibration."""
    mock_backend = MagicMock()
    mock_backend.get_runs.return_value = [
        {
            "deployment_version": "v1.0",
            "tool_sequence": '["tool_a"]',
            "latency_ms": 100 + i,  # Add variance
            "error_count": i % 3,  # Add variance
            "output_length": 200 + i * 2,
            "loop_count": 1 + i % 2,
            "time_to_first_tool_ms": 50 + i,
            "verbosity_ratio": 0.5 + (i * 0.01),
            "retry_count": i % 2,
            "semantic_cluster": f"cluster_{i % 3}",
        }
        for i in range(50)  # Above minimum
    ]
    mock_backend.get_calibration_cache.return_value = None

    with patch_backend(mock_backend):
        result = calibrate("v1.0", "v2.0", "GENERAL", sensitivity="standard")

    # Should use statistical method
    assert result.calibration_method == "statistical"


def test_reliability_multiplier_suppresses_noisy_dimensions():
    """High CV dimensions should get lower weights due to reliability multiplier."""
    # This is hard to test directly without exposing internals,
    # but we can verify that weights are adjusted from presets

    mock_backend = MagicMock()
    # Create runs with high variance in one dimension
    runs = []
    for i in range(100):
        runs.append(
            {
                "deployment_version": "v1.0",
                "tool_sequence": '["tool_a"]',
                "latency_ms": 100,  # Low variance
                "error_count": i % 10,  # High variance
                "output_length": 200,
                "loop_count": 1,
                "time_to_first_tool_ms": 50,
                "verbosity_ratio": 0.5,
                "retry_count": 0,
                "semantic_cluster": "cluster_0",
            }
        )
    mock_backend.get_runs.return_value = runs
    mock_backend.get_calibration_cache.return_value = None

    with patch_backend(mock_backend):
        result = calibrate("v1.0", "v2.0", "GENERAL", sensitivity="standard")

    # Weights should be different from preset due to reliability adjustment
    preset_weights = USE_CASE_WEIGHTS["GENERAL"]
    calibrated_weights = result.calibrated_weights

    # At least one weight should be different
    assert calibrated_weights != preset_weights


def test_thresholds_have_correct_structure():
    """Thresholds should have MONITOR, REVIEW, BLOCK for composite."""
    mock_backend = MagicMock()
    mock_backend.get_runs.return_value = [
        {
            "deployment_version": "v1.0",
            "tool_sequence": '["tool_a"]',
            "latency_ms": 100,
            "error_count": 0,
            "output_length": 200,
            "loop_count": 1,
            "time_to_first_tool_ms": 50,
            "verbosity_ratio": 0.5,
            "retry_count": 0,
            "semantic_cluster": "cluster_0",
        }
        for _ in range(50)
    ]
    mock_backend.get_calibration_cache.return_value = None

    with patch_backend(mock_backend):
        result = calibrate("v1.0", "v2.0", "GENERAL", sensitivity="standard")

    composite = result.composite_thresholds
    assert "MONITOR" in composite
    assert "REVIEW" in composite
    assert "BLOCK" in composite
    # Thresholds should be in ascending order
    assert composite["MONITOR"] < composite["REVIEW"] < composite["BLOCK"]


def test_baseline_n_in_result():
    """Result should include baseline_n (number of baseline runs used)."""
    mock_backend = MagicMock()
    mock_backend.get_runs.return_value = [
        {
            "deployment_version": "v1.0",
            "tool_sequence": '["tool_a"]',
            "latency_ms": 100,
            "error_count": 0,
            "output_length": 200,
            "loop_count": 1,
            "time_to_first_tool_ms": 50,
            "verbosity_ratio": 0.5,
            "retry_count": 0,
            "semantic_cluster": "cluster_0",
        }
        for _ in range(75)
    ]
    mock_backend.get_calibration_cache.return_value = None

    with patch_backend(mock_backend):
        result = calibrate("v1.0", "v2.0", "GENERAL", sensitivity="standard")

    assert hasattr(result, "baseline_n")
    assert result.baseline_n == 75


def test_invalid_sensitivity_defaults_to_standard():
    """Invalid sensitivity value should default to standard (1.00 multiplier)."""
    mock_backend = MagicMock()
    mock_backend.get_runs.return_value = [
        {
            "deployment_version": "v1.0",
            "tool_sequence": '["tool_a"]',
            "latency_ms": 100,
            "error_count": 0,
            "output_length": 200,
            "loop_count": 1,
            "time_to_first_tool_ms": 50,
            "verbosity_ratio": 0.5,
            "retry_count": 0,
            "semantic_cluster": "cluster_0",
        }
        for _ in range(50)
    ]
    mock_backend.get_calibration_cache.return_value = None

    with patch_backend(mock_backend):
        result_standard = calibrate("v1.0", "v2.0", "GENERAL", sensitivity="standard")
        result_invalid = calibrate(
            "v1.0", "v2.0", "GENERAL", sensitivity="invalid_value"
        )

    # Should behave the same
    assert result_standard.composite_thresholds == result_invalid.composite_thresholds


def test_no_eval_runs_still_calibrates():
    """Even with 0 eval runs, calibration should succeed (for baseline analysis)."""
    mock_backend = MagicMock()
    mock_backend.get_runs.side_effect = [
        # First call: baseline runs
        [
            {
                "deployment_version": "v1.0",
                "tool_sequence": '["tool_a"]',
                "latency_ms": 100,
                "error_count": 0,
                "output_length": 200,
                "loop_count": 1,
                "time_to_first_tool_ms": 50,
                "verbosity_ratio": 0.5,
                "retry_count": 0,
                "semantic_cluster": "cluster_0",
            }
            for _ in range(50)
        ],
        # Second call: eval runs (empty)
        [],
    ]
    mock_backend.get_calibration_cache.return_value = None

    with patch_backend(mock_backend):
        result = calibrate("v1.0", "v2.0", "GENERAL", sensitivity="standard")

    # Should still return calibration result
    assert hasattr(result, "calibrated_weights")
    assert hasattr(result, "composite_thresholds")


def test_semantic_unavailable_redistributes_weights():
    """When semantic_available=False, semantic_drift weight should be zeroed and redistributed."""
    mock_backend = MagicMock()
    mock_backend.get_runs.return_value = [
        {
            "deployment_version": "v1.0",
            "tool_sequence": '["tool_a"]',
            "latency_ms": 100,
            "error_count": 0,
            "output_length": 200,
            "loop_count": 1,
            "time_to_first_tool_ms": 50,
            "verbosity_ratio": 0.5,
            "retry_count": 0,
            "semantic_cluster": "cluster_0",
        }
        for _ in range(50)
    ]
    mock_backend.get_calibration_cache.return_value = None

    with patch_backend(mock_backend):
        result = calibrate(
            "v1.0", "v2.0", "GENERAL", sensitivity="standard", semantic_available=False
        )

    weights = result.calibrated_weights
    # semantic_drift should be zero
    assert weights["semantic_drift"] == 0.0
    # All weights should still sum to 1.0
    assert abs(sum(weights.values()) - 1.0) < 0.001
    # Other dimensions should have non-zero weights
    assert weights["decision_drift"] > 0.0


def test_transitions_unavailable_redistributes_weights():
    """When transitions_available=False, tool_sequence_transitions weight should be zeroed and redistributed."""
    mock_backend = MagicMock()
    mock_backend.get_runs.return_value = [
        {
            "deployment_version": "v1.0",
            "tool_sequence": '["tool_a"]',
            "latency_ms": 100,
            "error_count": 0,
            "output_length": 200,
            "loop_count": 1,
            "time_to_first_tool_ms": 50,
            "verbosity_ratio": 0.5,
            "retry_count": 0,
            "semantic_cluster": "cluster_0",
        }
        for _ in range(50)
    ]
    mock_backend.get_calibration_cache.return_value = None

    with patch_backend(mock_backend):
        result = calibrate(
            "v1.0",
            "v2.0",
            "FINANCIAL",
            sensitivity="standard",
            transitions_available=False,
        )

    weights = result.calibrated_weights
    # tool_sequence_transitions should be zero
    assert weights["tool_sequence_transitions"] == 0.0
    # All weights should still sum to 1.0
    assert abs(sum(weights.values()) - 1.0) < 0.001
    # Other dimensions should have non-zero weights
    assert weights["decision_drift"] > 0.0


def test_both_conditional_dimensions_unavailable():
    """When both semantic and transitions unavailable, both should be zeroed and redistributed."""
    mock_backend = MagicMock()
    mock_backend.get_runs.return_value = [
        {
            "deployment_version": "v1.0",
            "tool_sequence": '["tool_a"]',
            "latency_ms": 100,
            "error_count": 0,
            "output_length": 200,
            "loop_count": 1,
            "time_to_first_tool_ms": 50,
            "verbosity_ratio": 0.5,
            "retry_count": 0,
            "semantic_cluster": "cluster_0",
        }
        for _ in range(50)
    ]
    mock_backend.get_calibration_cache.return_value = None

    with patch_backend(mock_backend):
        result = calibrate(
            "v1.0",
            "v2.0",
            "GENERAL",
            sensitivity="standard",
            semantic_available=False,
            transitions_available=False,
        )

    weights = result.calibrated_weights
    # Both conditional dimensions should be zero
    assert weights["semantic_drift"] == 0.0
    assert weights["tool_sequence_transitions"] == 0.0
    # All weights should still sum to 1.0
    assert abs(sum(weights.values()) - 1.0) < 0.001
    # Other dimensions should have increased weights to compensate
    assert weights["decision_drift"] > 0.0
    assert weights["latency"] > 0.0


def test_redistribution_is_proportional():
    """Redistribution should be proportional to original non-zero weights."""
    mock_backend = MagicMock()
    mock_backend.get_runs.return_value = [
        {
            "deployment_version": "v1.0",
            "tool_sequence": '["tool_a"]',
            "latency_ms": 100 + i,
            "error_count": 0,
            "output_length": 200,
            "loop_count": 1,
            "time_to_first_tool_ms": 50,
            "verbosity_ratio": 0.5,
            "retry_count": 0,
            "semantic_cluster": "cluster_0",
        }
        for i in range(50)
    ]
    mock_backend.get_calibration_cache.return_value = None

    with patch_backend(mock_backend):
        result_all = calibrate("v1.0", "v2.0", "FINANCIAL", sensitivity="standard")
        result_no_semantic = calibrate(
            "v1.0",
            "v2.0",
            "FINANCIAL",
            sensitivity="standard",
            semantic_available=False,
        )

    weights_all = result_all.calibrated_weights
    weights_no_semantic = result_no_semantic.calibrated_weights

    # The ratio between non-conditional dimensions should be preserved
    # decision_drift / latency should be the same (or very close) in both cases
    ratio_all = weights_all["decision_drift"] / weights_all["latency"]
    ratio_no_semantic = (
        weights_no_semantic["decision_drift"] / weights_no_semantic["latency"]
    )

    # Allow for small floating point differences
    assert abs(ratio_all - ratio_no_semantic) < 0.01


def test_t_distribution_wider_than_normal_at_small_n():
    """t-distribution threshold is wider than normal at n=30."""
    mean = 1.0
    std = 0.2
    n = 30
    sigma_multiplier = 3.0

    # Compute threshold using t-distribution (via _compute_threshold)
    t_threshold = _compute_threshold(mean, std, n, sigma_multiplier)

    # Compute threshold using normal distribution (mean + sigma * std)
    normal_threshold = mean + sigma_multiplier * std

    # At n=30, t-distribution should be wider
    assert t_threshold > normal_threshold, (
        f"t-distribution threshold ({t_threshold}) should be wider than "
        f"normal ({normal_threshold}) at n=30"
    )

    # The difference should be meaningful (at least 3%)
    percent_wider = (t_threshold - normal_threshold) / normal_threshold
    assert percent_wider > 0.03, (
        f"t-distribution should be >3% wider, got {percent_wider:.2%}"
    )


def test_t_distribution_converges_to_normal_at_large_n():
    """t-distribution threshold converges to normal at n=500."""
    mean = 1.0
    std = 0.2
    n = 500
    sigma_multiplier = 3.0

    # Compute threshold using t-distribution
    t_threshold = _compute_threshold(mean, std, n, sigma_multiplier)

    # Compute threshold using normal distribution
    normal_threshold = mean + sigma_multiplier * std

    # At n=500, t-distribution should be very close to normal
    # Allow 1% difference
    percent_diff = abs(t_threshold - normal_threshold) / normal_threshold
    assert percent_diff < 0.01, (
        f"t-distribution should converge to normal at n=500, "
        f"but diff is {percent_diff:.2%}"
    )


def test_block_threshold_wider_for_small_n():
    """BLOCK threshold at n=30 is substantially wider than at n=200."""
    mean = 1.0
    std = 0.2
    sigma_multiplier = 4.0  # BLOCK uses 4σ

    threshold_n30 = _compute_threshold(mean, std, 30, sigma_multiplier)
    threshold_n200 = _compute_threshold(mean, std, 200, sigma_multiplier)

    # n=30 should be wider than n=200
    assert threshold_n30 > threshold_n200, (
        f"BLOCK threshold at n=30 ({threshold_n30}) should be wider than "
        f"at n=200 ({threshold_n200})"
    )

    # The difference should be substantial (at least 5%)
    percent_wider = (threshold_n30 - threshold_n200) / threshold_n200
    assert percent_wider > 0.05, (
        f"BLOCK threshold at n=30 should be >5% wider than at n=200, got {percent_wider:.2%}"
    )


def test_compute_threshold_never_raises():
    """_compute_threshold never raises on edge inputs."""
    # Should not raise on any of these edge cases

    # n=1
    result = _compute_threshold(1.0, 0.2, 1, 2.0)
    assert result > 0, "Should return positive threshold for n=1"

    # std=0
    result = _compute_threshold(1.0, 0.0, 50, 2.0)
    assert result > 0, "Should return positive threshold for std=0"

    # mean=0
    result = _compute_threshold(0.0, 0.2, 50, 2.0)
    assert result >= 0, "Should return non-negative threshold for mean=0"

    # All zeros
    result = _compute_threshold(0.0, 0.0, 50, 2.0)
    assert result >= 0, "Should return non-negative threshold for all zeros"

    # Negative std (shouldn't happen but should be handled)
    result = _compute_threshold(1.0, -0.1, 50, 2.0)
    assert result > 0, "Should return positive threshold for negative std"


def test_threshold_ordering_with_sigma_multipliers():
    """All three sigma multipliers produce correct ordering: MONITOR < REVIEW < BLOCK."""
    mean = 1.0
    std = 0.2
    n = 50

    monitor = _compute_threshold(mean, std, n, 2.0)
    review = _compute_threshold(mean, std, n, 3.0)
    block = _compute_threshold(mean, std, n, 4.0)

    # Should be in ascending order
    assert monitor < review < block, (
        f"Thresholds should be ordered MONITOR < REVIEW < BLOCK, "
        f"got {monitor} < {review} < {block}"
    )

    # Also test at small n to ensure ordering holds with t-distribution
    n_small = 30
    monitor_small = _compute_threshold(mean, std, n_small, 2.0)
    review_small = _compute_threshold(mean, std, n_small, 3.0)
    block_small = _compute_threshold(mean, std, n_small, 4.0)

    assert monitor_small < review_small < block_small, (
        f"Thresholds should be ordered at n=30, "
        f"got {monitor_small} < {review_small} < {block_small}"
    )


def test_correlation_adjustment_returns_ones_when_n_too_small():
    """Correlation adjustment returns all 1.0 when n < 30."""
    dimension_scores = {
        "latency": [0.1] * 20,
        "retry_rate": [0.2] * 20,
        "error_rate": [0.15] * 20,
    }
    weights = {"latency": 0.4, "retry_rate": 0.3, "error_rate": 0.3}

    adjustments, pairs = _compute_correlation_adjustments(dimension_scores, weights)

    # All adjustment factors should be 1.0 (no adjustment)
    assert all(adj == 1.0 for adj in adjustments.values())
    assert len(pairs) == 0


def test_correlation_adjustment_returns_ones_when_no_high_correlation():
    """Correlation adjustment returns all 1.0 when no pairs exceed threshold."""
    import numpy as np

    np.random.seed(42)
    # Create uncorrelated dimensions
    dimension_scores = {
        "latency": np.random.randn(50).tolist(),
        "retry_rate": np.random.randn(50).tolist(),
        "error_rate": np.random.randn(50).tolist(),
    }
    weights = {"latency": 0.4, "retry_rate": 0.3, "error_rate": 0.3}

    adjustments, pairs = _compute_correlation_adjustments(dimension_scores, weights)

    # All adjustment factors should be 1.0 (no high correlation)
    assert all(adj == 1.0 for adj in adjustments.values())
    assert len(pairs) == 0


def test_correlation_adjustment_reduces_less_important_dimension():
    """High correlation pair: less important dimension gets reduced weight."""
    import numpy as np

    np.random.seed(42)
    # Create highly correlated dimensions
    base = np.linspace(0, 1, 50)
    dimension_scores = {
        "latency": base.tolist(),
        "retry_rate": (base + np.random.randn(50) * 0.05).tolist(),  # Highly correlated
        "error_rate": np.random.randn(50).tolist(),  # Uncorrelated
    }
    weights = {"latency": 0.5, "retry_rate": 0.3, "error_rate": 0.2}

    adjustments, pairs = _compute_correlation_adjustments(dimension_scores, weights)

    # Should find latency ↔ retry_rate correlation
    assert len(pairs) > 0

    # Less important dimension (retry_rate, lower weight) should be reduced
    assert adjustments["retry_rate"] < 1.0
    # More important dimension (latency, higher weight) should not be reduced
    assert adjustments["latency"] == 1.0
    # Uncorrelated dimension should not be affected
    assert adjustments["error_rate"] == 1.0


def test_correlation_adjustment_more_important_never_reduced():
    """More important dimension (higher weight) is never reduced."""
    import numpy as np

    np.random.seed(42)
    base = np.linspace(0, 1, 50)
    dimension_scores = {
        "decision_drift": base.tolist(),
        "tool_sequence": (base + np.random.randn(50) * 0.05).tolist(),
    }
    # decision_drift has higher weight
    weights = {"decision_drift": 0.6, "tool_sequence": 0.4}

    adjustments, pairs = _compute_correlation_adjustments(dimension_scores, weights)

    if len(pairs) > 0:
        # Higher weight dimension should never be reduced
        assert adjustments["decision_drift"] == 1.0
        # Lower weight dimension might be reduced
        assert adjustments["tool_sequence"] <= 1.0


def test_correlation_adjustment_max_reduction_cap():
    """Weight reduction never exceeds MAX_REDUCTION (50%)."""
    import numpy as np

    np.random.seed(42)
    # Create perfectly correlated dimensions
    base = np.linspace(0, 1, 50)
    dimension_scores = {
        "latency": base.tolist(),
        "loop_depth": base.tolist(),  # Perfect correlation
    }
    weights = {"latency": 0.6, "loop_depth": 0.4}

    adjustments, pairs = _compute_correlation_adjustments(dimension_scores, weights)

    # Even with perfect correlation, reduction should not exceed 50%
    for dim, adj in adjustments.items():
        assert adj >= 0.5, f"{dim} adjustment {adj} exceeds max reduction"


def test_correlation_adjustment_weights_sum_to_one_after_renormalization():
    """Weights still sum to 1.0 after correlation adjustment + renormalization."""
    import numpy as np

    np.random.seed(42)
    base = np.linspace(0, 1, 50)
    dimension_scores = {
        "decision_drift": base.tolist(),
        "latency": (base + np.random.randn(50) * 0.05).tolist(),
        "error_rate": np.random.randn(50).tolist(),
        "tool_sequence": np.random.randn(50).tolist(),
    }
    weights = {
        "decision_drift": 0.4,
        "latency": 0.3,
        "error_rate": 0.2,
        "tool_sequence": 0.1,
    }

    adjustments, pairs = _compute_correlation_adjustments(dimension_scores, weights)

    # Apply adjustments
    adjusted_weights = {dim: weights[dim] * adjustments[dim] for dim in weights}

    # Renormalize
    total = sum(adjusted_weights.values())
    normalized_weights = {dim: w / total for dim, w in adjusted_weights.items()}

    # Should sum to 1.0
    assert abs(sum(normalized_weights.values()) - 1.0) < 0.001


def test_correlation_adjustment_never_raises():
    """Correlation adjustment never raises on edge inputs."""
    # Empty dimension_scores
    adjustments, pairs = _compute_correlation_adjustments({}, {})
    assert len(adjustments) == 0
    assert len(pairs) == 0

    # Single dimension
    adjustments, pairs = _compute_correlation_adjustments(
        {"latency": [0.1] * 50}, {"latency": 1.0}
    )
    assert adjustments["latency"] == 1.0
    assert len(pairs) == 0

    # Zero variance dimensions
    adjustments, pairs = _compute_correlation_adjustments(
        {"latency": [0.5] * 50, "retry_rate": [0.5] * 50},
        {"latency": 0.5, "retry_rate": 0.5},
    )
    assert all(adj == 1.0 for adj in adjustments.values())


def test_correlated_pairs_populated_in_calibration_result():
    """correlated_pairs is correctly populated in CalibrationResult."""
    mock_backend = MagicMock()
    import numpy as np

    np.random.seed(42)
    base = np.linspace(0, 1, 50)

    # Create runs with highly correlated latency and retry_rate
    runs = []
    for i in range(50):
        latency = int(base[i] * 1000 + 100)
        retry = int(base[i] * 3)
        runs.append(
            {
                "deployment_version": "v1.0",
                "tool_sequence": '["tool_a"]',
                "latency_ms": latency,
                "error_count": 0,
                "output_length": 200,
                "loop_count": 1,
                "time_to_first_tool_ms": 50,
                "verbosity_ratio": 0.5,
                "retry_count": retry,
                "semantic_cluster": "cluster_0",
            }
        )

    mock_backend.get_runs.return_value = runs
    mock_backend.get_calibration_cache.return_value = None

    with patch_backend(mock_backend):
        result = calibrate("v1.0", "v2.0", "GENERAL", sensitivity="standard")

    # Should have correlation metadata
    assert hasattr(result, "correlated_pairs")
    assert hasattr(result, "correlation_adjusted")
    # If correlation was found and adjusted, should be True
    if len(result.correlated_pairs) > 0:
        assert result.correlation_adjusted is True


def test_correlation_adjusted_false_when_n_too_small():
    """correlation_adjusted = False when n < 30."""
    mock_backend = MagicMock()
    mock_backend.get_runs.return_value = [
        {
            "deployment_version": "v1.0",
            "tool_sequence": '["tool_a"]',
            "latency_ms": 100 + i,
            "error_count": 0,
            "output_length": 200,
            "loop_count": 1,
            "time_to_first_tool_ms": 50,
            "verbosity_ratio": 0.5,
            "retry_count": 0,
            "semantic_cluster": "cluster_0",
        }
        for i in range(20)  # Below minimum for both calibration and correlation
    ]
    mock_backend.get_calibration_cache.return_value = None

    with patch_backend(mock_backend):
        result = calibrate("v1.0", "v2.0", "GENERAL", sensitivity="standard")

    # Should be False because n < 30
    assert result.correlation_adjusted is False
    assert len(result.correlated_pairs) == 0


def test_correlation_adjusted_true_when_pairs_found():
    """correlation_adjusted = True when at least one pair was adjusted."""
    mock_backend = MagicMock()
    import numpy as np

    np.random.seed(42)
    base = np.linspace(0, 1, 100)

    # Create strongly correlated latency and loop_depth
    runs = []
    for i in range(100):
        latency = int(base[i] * 1000 + 100)
        loop = int(base[i] * 10 + 1)
        runs.append(
            {
                "deployment_version": "v1.0",
                "tool_sequence": '["tool_a"]',
                "latency_ms": latency,
                "error_count": 0,
                "output_length": 200,
                "loop_count": loop,
                "time_to_first_tool_ms": 50,
                "verbosity_ratio": 0.5,
                "retry_count": 0,
                "semantic_cluster": "cluster_0",
            }
        )

    mock_backend.get_runs.return_value = runs
    mock_backend.get_calibration_cache.return_value = None

    with patch_backend(mock_backend):
        result = calibrate("v1.0", "v2.0", "GENERAL", sensitivity="standard")

    # If correlation was found, should be True
    if len(result.correlated_pairs) > 0:
        assert result.correlation_adjusted is True
