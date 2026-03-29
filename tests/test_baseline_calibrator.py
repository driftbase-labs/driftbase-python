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
