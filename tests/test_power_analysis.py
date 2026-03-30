"""Tests for adaptive power analysis functionality."""

import json

import numpy as np
import pytest

from driftbase.local.baseline_calibrator import compute_min_runs_needed
from driftbase.local.diff import compute_dimension_significance


def test_compute_min_runs_needed_consistent_agent():
    """Consistent agent (low std) hits the 30 floor - this is expected behavior."""
    # Create very consistent baseline data (sigma ~ 0.02)
    np.random.seed(42)
    baseline_dimension_scores = {
        "decision_drift": list(np.random.normal(0.1, 0.02, 50)),
        "latency_drift": list(np.random.normal(0.2, 0.02, 50)),
        "error_drift": list(np.random.normal(0.05, 0.02, 50)),
    }

    result = compute_min_runs_needed(
        baseline_dimension_scores=baseline_dimension_scores,
        use_case="GENERAL",
    )

    # Should compute successfully
    assert result["overall"] > 0
    assert "per_dimension" in result
    # With very low sigma (~0.02), formula produces n < 30, so we hit the floor
    assert result["overall"] == 30  # Floor for calibration
    assert 10 <= result["overall"] <= 200


def test_compute_min_runs_needed_noisy_agent():
    """Noisy agent (high std) should need significantly more runs than consistent agent."""
    # Create noisy baseline data (sigma ~ 0.25, realistic high variance)
    np.random.seed(42)
    baseline_dimension_scores = {
        "decision_drift": list(np.random.normal(0.1, 0.25, 50)),
        "latency_drift": list(np.random.normal(0.2, 0.25, 50)),
        "error_drift": list(np.random.normal(0.05, 0.25, 50)),
    }

    result = compute_min_runs_needed(
        baseline_dimension_scores=baseline_dimension_scores,
        use_case="GENERAL",
    )

    # Should compute successfully
    assert result["overall"] > 0
    # With high variance (sigma ~ 0.25), formula should produce n > 50
    assert result["overall"] > 50  # Should be well above the floor


def test_compute_min_runs_needed_financial_use_case():
    """FINANCIAL use case has smaller effect_size, so should need more runs."""
    # Use high variance (sigma ~ 0.20) so formula produces differentiated values
    np.random.seed(42)
    baseline_dimension_scores = {
        "decision_drift": list(np.random.normal(0.1, 0.20, 50)),
        "latency_drift": list(np.random.normal(0.2, 0.20, 50)),
    }

    financial_result = compute_min_runs_needed(
        baseline_dimension_scores=baseline_dimension_scores,
        use_case="FINANCIAL",
    )

    general_result = compute_min_runs_needed(
        baseline_dimension_scores=baseline_dimension_scores,
        use_case="GENERAL",
    )

    # FINANCIAL (effect_size=0.05) should need more runs than GENERAL (effect_size=0.10)
    assert financial_result["effect_size"] < general_result["effect_size"]
    # With smaller effect size, need more runs to detect drift
    assert financial_result["overall"] > general_result["overall"]


def test_compute_min_runs_needed_content_generation():
    """CONTENT_GENERATION has larger effect_size, so should need fewer runs."""
    # Use high variance (sigma ~ 0.20) so formula produces differentiated values
    np.random.seed(42)
    baseline_dimension_scores = {
        "decision_drift": list(np.random.normal(0.1, 0.20, 50)),
        "latency_drift": list(np.random.normal(0.2, 0.20, 50)),
    }

    content_result = compute_min_runs_needed(
        baseline_dimension_scores=baseline_dimension_scores,
        use_case="CONTENT_GENERATION",
    )

    general_result = compute_min_runs_needed(
        baseline_dimension_scores=baseline_dimension_scores,
        use_case="GENERAL",
    )

    # CONTENT_GENERATION (effect_size=0.15) should need fewer runs than GENERAL (effect_size=0.10)
    assert content_result["effect_size"] > general_result["effect_size"]
    assert content_result["overall"] < general_result["overall"]


def test_compute_min_runs_needed_insufficient_data():
    """With < 10 baseline runs, should fall back to default 50."""
    baseline_dimension_scores = {
        "decision_drift": [0.10, 0.12, 0.11],  # Only 3 samples
        "latency_drift": [0.15, 0.16, 0.14],
    }

    result = compute_min_runs_needed(
        baseline_dimension_scores=baseline_dimension_scores,
        use_case="GENERAL",
    )

    # Should fall back to default
    assert result["overall"] == 50
    # All per_dimension should be 50 (fallback)
    for dim_runs in result["per_dimension"].values():
        assert dim_runs == 50


def test_compute_min_runs_needed_never_raises():
    """compute_min_runs_needed should never raise on any input."""
    # Empty input
    result = compute_min_runs_needed({})
    assert result["overall"] == 50

    # Malformed input
    result = compute_min_runs_needed({"bad_dim": [None, None, None]})
    assert result["overall"] == 50

    # Zero variance (should return 10 per-dimension, 30 overall)
    baseline_dimension_scores = {
        "decision_drift": [0.10] * 20,  # No variance
    }
    result = compute_min_runs_needed(baseline_dimension_scores)
    assert result["per_dimension"]["decision_drift"] == 10
    assert result["overall"] == 30  # Overall floor


def test_compute_min_runs_needed_all_per_dimension_values_bounded():
    """All per_dimension values should be between 10 and 200."""
    np.random.seed(42)
    baseline_dimension_scores = {
        "decision_drift": list(np.random.normal(0.1, 0.05, 50)),
        "latency_drift": [0.001] * 15,  # Near-zero variance
        "error_drift": list(np.random.normal(0.1, 0.35, 50)),  # Very high variance
    }

    result = compute_min_runs_needed(
        baseline_dimension_scores=baseline_dimension_scores,
        use_case="GENERAL",
    )

    for dim, min_runs in result["per_dimension"].items():
        assert 10 <= min_runs <= 200, (
            f"Dimension {dim} has invalid min_runs: {min_runs}"
        )


def test_compute_dimension_significance_correct_status():
    """compute_dimension_significance should correctly classify each dimension."""
    baseline_runs = [{"id": str(i)} for i in range(50)]
    eval_runs = [{"id": str(i)} for i in range(50)]

    min_runs_per_dimension = {
        "decision_drift": 30,
        "latency_drift": 60,
        "error_drift": 10,
    }

    # With n=50:
    # decision_drift: 50 >= 30 → reliable
    # latency_drift: 50 < 60 → indicative (but >= 15)
    # error_drift: 50 >= 10 → reliable
    statuses = compute_dimension_significance(
        baseline_runs, eval_runs, min_runs_per_dimension
    )

    assert statuses["decision_drift"] == "reliable"
    assert statuses["latency_drift"] == "indicative"
    assert statuses["error_drift"] == "reliable"


def test_compute_dimension_significance_insufficient_data():
    """With n < 15, all dimensions should be insufficient."""
    baseline_runs = [{"id": str(i)} for i in range(10)]
    eval_runs = [{"id": str(i)} for i in range(10)]

    min_runs_per_dimension = {
        "decision_drift": 30,
        "latency_drift": 50,
    }

    statuses = compute_dimension_significance(
        baseline_runs, eval_runs, min_runs_per_dimension
    )

    assert statuses["decision_drift"] == "insufficient"
    assert statuses["latency_drift"] == "insufficient"


def test_partial_tier3_logic():
    """When 8+ dimensions are reliable, should trigger partial TIER3."""
    # Create a scenario where 9 of 12 dimensions are reliable
    baseline_runs = [{"id": str(i)} for i in range(45)]  # n=45
    eval_runs = [{"id": str(i)} for i in range(45)]

    # 9 dimensions need <= 45 runs (reliable)
    # 3 dimensions need > 45 runs (indicative)
    min_runs_per_dimension = {
        "decision_drift": 40,  # reliable
        "latency_drift": 35,  # reliable
        "error_drift": 30,  # reliable
        "semantic_drift": 38,  # reliable
        "verbosity_drift": 42,  # reliable
        "loop_depth_drift": 40,  # reliable
        "tool_sequence_drift": 45,  # reliable
        "retry_drift": 36,  # reliable
        "output_length_drift": 44,  # reliable
        "planning_latency_drift": 55,  # indicative (need 55, have 45)
        "output_drift": 60,  # indicative
        "tool_sequence_transitions_drift": 70,  # indicative
    }

    statuses = compute_dimension_significance(
        baseline_runs, eval_runs, min_runs_per_dimension
    )

    reliable_count = sum(1 for s in statuses.values() if s == "reliable")

    # Should have exactly 9 reliable dimensions
    assert reliable_count == 9
    # This should trigger partial TIER3 (>= 8 reliable)
    assert reliable_count >= 8


def test_power_analysis_integration_with_sqlite(tmp_path):
    """Test that power analysis results are cached and retrieved correctly."""
    from driftbase.backends.sqlite import SQLiteBackend

    # Create a temporary SQLite database
    db_path = str(tmp_path / "test.db")
    backend = SQLiteBackend(db_path)

    # Write a significance threshold
    agent_id = "test-agent"
    version = "v1.0"
    threshold_data = {
        "use_case": "FINANCIAL",
        "effect_size": 0.05,
        "overall": 75,
        "per_dimension": {
            "decision_drift": 70,
            "latency_drift": 75,
            "error_drift": 60,
        },
        "limiting_dimension": "latency_drift",
        "baseline_n_at_computation": 50,
    }

    backend.write_significance_threshold(agent_id, version, threshold_data)

    # Retrieve it
    retrieved = backend.get_significance_threshold(agent_id, version)

    assert retrieved is not None
    assert retrieved["use_case"] == "FINANCIAL"
    assert retrieved["effect_size"] == 0.05
    assert retrieved["overall"] == 75
    assert retrieved["per_dimension"]["decision_drift"] == 70
    assert retrieved["limiting_dimension"] == "latency_drift"
    assert retrieved["baseline_n_at_computation"] == 50


def test_power_analysis_cache_invalidation(tmp_path):
    """Test that cache is recomputed when baseline_n grows > 20%."""
    from driftbase.backends.sqlite import SQLiteBackend

    db_path = str(tmp_path / "test.db")
    backend = SQLiteBackend(db_path)

    agent_id = "test-agent"
    version = "v1.0"

    # Initial threshold with baseline_n = 50
    threshold_data_1 = {
        "use_case": "GENERAL",
        "effect_size": 0.10,
        "overall": 50,
        "per_dimension": {},
        "limiting_dimension": "",
        "baseline_n_at_computation": 50,
    }

    backend.write_significance_threshold(agent_id, version, threshold_data_1)

    # Try to write again with baseline_n = 55 (10% growth, should NOT overwrite)
    threshold_data_2 = {
        "use_case": "GENERAL",
        "effect_size": 0.10,
        "overall": 45,  # Different value
        "per_dimension": {},
        "limiting_dimension": "",
        "baseline_n_at_computation": 55,
    }

    backend.write_significance_threshold(agent_id, version, threshold_data_2)

    # Should still have the original value (no overwrite)
    retrieved = backend.get_significance_threshold(agent_id, version)
    assert retrieved["overall"] == 50  # Original value
    assert retrieved["baseline_n_at_computation"] == 50

    # Try to write again with baseline_n = 65 (30% growth, should overwrite)
    threshold_data_3 = {
        "use_case": "GENERAL",
        "effect_size": 0.10,
        "overall": 40,  # Different value
        "per_dimension": {},
        "limiting_dimension": "",
        "baseline_n_at_computation": 65,
    }

    backend.write_significance_threshold(agent_id, version, threshold_data_3)

    # Should now have the new value (overwritten)
    retrieved = backend.get_significance_threshold(agent_id, version)
    assert retrieved["overall"] == 40  # New value
    assert retrieved["baseline_n_at_computation"] == 65


def test_get_confidence_tier_with_custom_min_runs():
    """Test that get_confidence_tier respects custom min_runs_needed from power analysis."""
    from driftbase.local.diff import get_confidence_tier

    # Default behavior (min_runs_needed=50)
    assert get_confidence_tier(baseline_n=10, eval_n=10, min_runs_needed=50) == "TIER1"
    assert get_confidence_tier(baseline_n=20, eval_n=20, min_runs_needed=50) == "TIER2"
    assert get_confidence_tier(baseline_n=55, eval_n=55, min_runs_needed=50) == "TIER3"

    # Custom min_runs_needed=30 (from power analysis for consistent agent)
    assert get_confidence_tier(baseline_n=10, eval_n=10, min_runs_needed=30) == "TIER1"
    assert get_confidence_tier(baseline_n=20, eval_n=20, min_runs_needed=30) == "TIER2"
    assert get_confidence_tier(baseline_n=35, eval_n=35, min_runs_needed=30) == "TIER3"

    # Custom min_runs_needed=80 (from power analysis for noisy agent)
    assert get_confidence_tier(baseline_n=10, eval_n=10, min_runs_needed=80) == "TIER1"
    assert get_confidence_tier(baseline_n=20, eval_n=20, min_runs_needed=80) == "TIER2"
    assert (
        get_confidence_tier(baseline_n=50, eval_n=50, min_runs_needed=80) == "TIER2"
    )  # Still TIER2!
    assert get_confidence_tier(baseline_n=85, eval_n=85, min_runs_needed=80) == "TIER3"
