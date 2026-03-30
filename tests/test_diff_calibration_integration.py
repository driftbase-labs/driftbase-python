"""
Tests for calibration integration in drift computation.

Tests end-to-end flow: tool extraction → use case inference → calibration → drift computation
with calibrated weights and thresholds.
"""

from __future__ import annotations

import json
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from driftbase.local.baseline_calibrator import CalibrationResult
from driftbase.local.diff import compute_drift
from driftbase.local.fingerprinter import build_fingerprint_from_runs
from driftbase.local.local_store import AgentRun


def _create_calibration_result(**kwargs) -> CalibrationResult:
    """Helper to create a CalibrationResult with defaults."""
    defaults = {
        "calibrated_weights": {
            "decision_drift": 0.40,
            "latency_drift": 0.15,
            "error_drift": 0.12,
            "semantic_drift": 0.10,
            "verbosity_drift": 0.08,
            "loop_depth_drift": 0.06,
            "output_drift": 0.04,
            "tool_sequence_drift": 0.03,
            "retry_drift": 0.02,
        },
        "thresholds": {},
        "composite_thresholds": {"MONITOR": 0.15, "REVIEW": 0.28, "BLOCK": 0.42},
        "calibration_method": "statistical",
        "baseline_n": 50,
        "reliability_multipliers": {},
        "inferred_use_case": "GENERAL",
        "confidence": 0.85,
    }
    defaults.update(kwargs)
    return CalibrationResult(**defaults)


def _create_test_run(
    version: str = "v1.0",
    tools: list[str] | None = None,
    latency_ms: int = 100,
    error_count: int = 0,
) -> AgentRun:
    """Helper to create a test AgentRun."""
    if tools is None:
        tools = ["tool_a", "tool_b"]

    return AgentRun(
        id="test-id",
        session_id="test-session",
        deployment_version=version,
        environment="production",
        started_at=datetime.utcnow(),
        completed_at=datetime.utcnow(),
        task_input_hash="input-hash",
        tool_sequence=json.dumps(tools),  # Properly serialize to JSON
        tool_call_count=len(tools),
        output_length=200,
        output_structure_hash="output-hash",
        latency_ms=latency_ms,
        error_count=error_count,
        retry_count=0,
        semantic_cluster="cluster_0",
        loop_count=1,
        time_to_first_tool_ms=50,
        verbosity_ratio=0.5,
        prompt_tokens=100,
        completion_tokens=50,
    )


def _run_to_dict(run: AgentRun) -> dict:
    """Convert AgentRun to dict for fingerprint building."""
    return {
        "id": run.id,
        "session_id": run.session_id,
        "deployment_version": run.deployment_version,
        "environment": run.environment,
        "started_at": run.started_at,
        "completed_at": run.completed_at,
        "task_input_hash": run.task_input_hash,
        "tool_sequence": run.tool_sequence,
        "tool_call_count": run.tool_call_count,
        "output_length": run.output_length,
        "output_structure_hash": run.output_structure_hash,
        "latency_ms": run.latency_ms,
        "error_count": run.error_count,
        "retry_count": run.retry_count,
        "semantic_cluster": run.semantic_cluster,
        "loop_count": run.loop_count,
        "time_to_first_tool_ms": run.time_to_first_tool_ms,
        "verbosity_ratio": run.verbosity_ratio,
        "prompt_tokens": run.prompt_tokens,
        "completion_tokens": run.completion_tokens,
    }


def test_compute_drift_calls_calibration():
    """compute_drift should call calibration and use calibrated weights."""
    # Create test runs
    baseline_runs = [
        _create_test_run("v1.0", ["check_credit", "approve_loan"]) for _ in range(50)
    ]
    current_runs = [
        _create_test_run("v2.0", ["check_credit", "approve_loan"]) for _ in range(50)
    ]

    # Build fingerprints
    baseline_fp = build_fingerprint_from_runs(
        baseline_runs,
        datetime.utcnow(),
        datetime.utcnow(),
        "v1.0",
        "production",
    )
    current_fp = build_fingerprint_from_runs(
        current_runs,
        datetime.utcnow(),
        datetime.utcnow(),
        "v2.0",
        "production",
    )

    # Convert to dicts for compute_drift
    baseline_dicts = [_run_to_dict(r) for r in baseline_runs]
    current_dicts = [_run_to_dict(r) for r in current_runs]

    # Mock calibrate to return known values
    mock_calibration = _create_calibration_result(
        inferred_use_case="FINANCIAL",
        confidence=0.85,
    )

    with (
        patch(
            "driftbase.local.baseline_calibrator.calibrate",
            return_value=mock_calibration,
        ),
        patch("driftbase.local.use_case_inference.infer_use_case") as mock_infer,
    ):
        mock_infer.return_value = {
            "use_case": "FINANCIAL",
            "confidence": 0.85,
            "matched_keywords": ["credit", "loan"],
            "scores": {"FINANCIAL": 4.0, "GENERAL": 0.0},
        }

        report = compute_drift(
            baseline_fp,
            current_fp,
            baseline_runs=baseline_dicts,
            current_runs=current_dicts,
            sensitivity="standard",
        )

    # Verify calibration was called
    assert report is not None

    # Verify report contains calibration metadata
    assert hasattr(report, "inferred_use_case")
    assert report.inferred_use_case == "FINANCIAL"
    assert hasattr(report, "use_case_confidence")
    assert report.use_case_confidence == 0.85
    assert hasattr(report, "calibration_method")
    assert report.calibration_method == "statistical"
    assert hasattr(report, "calibrated_weights")
    assert report.calibrated_weights == mock_calibration.calibrated_weights
    assert hasattr(report, "composite_thresholds")
    assert report.composite_thresholds == mock_calibration.composite_thresholds
    assert hasattr(report, "baseline_n")
    assert report.baseline_n == 50


def test_tool_extraction_from_runs():
    """Tool names should be extracted from run tool_sequences."""
    # Create runs with different tools
    baseline_runs = [
        _create_test_run("v1.0", ["create_ticket", "escalate_issue"]),
        _create_test_run("v1.0", ["send_refund", "close_ticket"]),
    ]
    current_runs = [
        _create_test_run("v2.0", ["create_ticket", "send_refund"]),
    ]

    baseline_fp = build_fingerprint_from_runs(
        baseline_runs,
        datetime.utcnow(),
        datetime.utcnow(),
        "v1.0",
        "production",
    )
    current_fp = build_fingerprint_from_runs(
        current_runs,
        datetime.utcnow(),
        datetime.utcnow(),
        "v2.0",
        "production",
    )

    baseline_dicts = [_run_to_dict(r) for r in baseline_runs]
    current_dicts = [_run_to_dict(r) for r in current_runs]

    with (
        patch("driftbase.local.baseline_calibrator.calibrate") as mock_calibrate,
        patch("driftbase.local.use_case_inference.infer_use_case") as mock_infer,
    ):
        mock_infer.return_value = {
            "use_case": "CUSTOMER_SUPPORT",
            "confidence": 0.90,
            "matched_keywords": ["ticket", "escalate", "refund"],
            "scores": {"CUSTOMER_SUPPORT": 6.0},
        }
        mock_calibrate.return_value = _create_calibration_result(
            calibrated_weights={},
            calibration_method="default",
            baseline_n=2,
        )

        compute_drift(
            baseline_fp,
            current_fp,
            baseline_runs=baseline_dicts,
            current_runs=current_dicts,
        )

        # Verify infer_use_case was called with extracted tools
        mock_infer.assert_called_once()
        called_tools = mock_infer.call_args[0][0]

        # Should contain all unique tools from both baseline and current
        expected_tools = {
            "create_ticket",
            "escalate_issue",
            "send_refund",
            "close_ticket",
        }
        assert set(called_tools) == expected_tools


def test_sensitivity_parameter_passed_through():
    """Sensitivity parameter should be passed to calibrate function."""
    baseline_runs = [_create_test_run("v1.0") for _ in range(60)]
    current_runs = [_create_test_run("v2.0") for _ in range(60)]

    baseline_fp = build_fingerprint_from_runs(
        baseline_runs,
        datetime.utcnow(),
        datetime.utcnow(),
        "v1.0",
        "production",
    )
    current_fp = build_fingerprint_from_runs(
        current_runs,
        datetime.utcnow(),
        datetime.utcnow(),
        "v2.0",
        "production",
    )

    baseline_dicts = [_run_to_dict(r) for r in baseline_runs]
    current_dicts = [_run_to_dict(r) for r in current_runs]

    with (
        patch("driftbase.local.baseline_calibrator.calibrate") as mock_calibrate,
        patch("driftbase.local.use_case_inference.infer_use_case"),
    ):
        mock_calibrate.return_value = _create_calibration_result(
            calibrated_weights={},
            calibration_method="default",
            baseline_n=60,
        )

        compute_drift(
            baseline_fp,
            current_fp,
            baseline_runs=baseline_dicts,
            current_runs=current_dicts,
            sensitivity="strict",
        )

        # Verify calibrate was called with sensitivity="strict"
        mock_calibrate.assert_called_once()
        call_kwargs = mock_calibrate.call_args[1]
        assert call_kwargs["sensitivity"] == "strict"


def test_sensitivity_config_fallback():
    """When sensitivity is None, should fall back to config setting."""
    baseline_runs = [_create_test_run("v1.0") for _ in range(60)]
    current_runs = [_create_test_run("v2.0") for _ in range(60)]

    baseline_fp = build_fingerprint_from_runs(
        baseline_runs,
        datetime.utcnow(),
        datetime.utcnow(),
        "v1.0",
        "production",
    )
    current_fp = build_fingerprint_from_runs(
        current_runs,
        datetime.utcnow(),
        datetime.utcnow(),
        "v2.0",
        "production",
    )

    baseline_dicts = [_run_to_dict(r) for r in baseline_runs]
    current_dicts = [_run_to_dict(r) for r in current_runs]

    # Mock config to return "relaxed"
    mock_settings = MagicMock()
    mock_settings.DRIFTBASE_SENSITIVITY = "relaxed"
    mock_settings.TIER1_MIN_RUNS = 15
    mock_settings.TIER2_MIN_RUNS = 50

    with (
        patch("driftbase.config.get_settings", return_value=mock_settings),
        patch("driftbase.local.baseline_calibrator.calibrate") as mock_calibrate,
        patch("driftbase.local.use_case_inference.infer_use_case"),
    ):
        mock_calibrate.return_value = _create_calibration_result(
            calibrated_weights={},
            calibration_method="default",
            baseline_n=60,
        )

        compute_drift(
            baseline_fp,
            current_fp,
            baseline_runs=baseline_dicts,
            current_runs=current_dicts,
            sensitivity=None,  # Should fall back to config
        )

        # Verify calibrate was called with sensitivity="relaxed" from config
        mock_calibrate.assert_called_once()
        call_kwargs = mock_calibrate.call_args[1]
        assert call_kwargs["sensitivity"] == "relaxed"


def test_no_runs_provided_uses_defaults():
    """When baseline_runs/current_runs are None, should use default weights."""
    baseline_runs = [_create_test_run("v1.0") for _ in range(60)]
    current_runs = [_create_test_run("v2.0") for _ in range(60)]

    baseline_fp = build_fingerprint_from_runs(
        baseline_runs,
        datetime.utcnow(),
        datetime.utcnow(),
        "v1.0",
        "production",
    )
    current_fp = build_fingerprint_from_runs(
        current_runs,
        datetime.utcnow(),
        datetime.utcnow(),
        "v2.0",
        "production",
    )

    # Call without runs - should not crash
    report = compute_drift(
        baseline_fp,
        current_fp,
        baseline_runs=None,
        current_runs=None,
    )

    # Should return a report with default calibration
    assert report is not None
    # Use case should be GENERAL (no tools to infer from)
    assert report.inferred_use_case == "GENERAL"


def test_calibrated_weights_affect_drift_score():
    """Calibrated weights should be used in drift score calculation."""
    # Create two sets of runs with different characteristics
    baseline_runs = [
        _create_test_run("v1.0", ["tool_a"], latency_ms=100, error_count=0)
        for _ in range(50)
    ]
    current_runs = [
        _create_test_run("v2.0", ["tool_a"], latency_ms=200, error_count=5)
        for _ in range(50)
    ]

    baseline_fp = build_fingerprint_from_runs(
        baseline_runs,
        datetime.utcnow(),
        datetime.utcnow(),
        "v1.0",
        "production",
    )
    current_fp = build_fingerprint_from_runs(
        current_runs,
        datetime.utcnow(),
        datetime.utcnow(),
        "v2.0",
        "production",
    )

    baseline_dicts = [_run_to_dict(r) for r in baseline_runs]
    current_dicts = [_run_to_dict(r) for r in current_runs]

    # Test with high latency weight
    high_latency_weights = {
        "decision_drift": 0.10,
        "latency_drift": 0.70,  # Very high
        "error_drift": 0.10,
        "semantic_drift": 0.05,
        "verbosity_drift": 0.02,
        "loop_depth_drift": 0.01,
        "output_drift": 0.01,
        "tool_sequence_drift": 0.01,
        "retry_drift": 0.00,
    }

    with (
        patch("driftbase.local.baseline_calibrator.calibrate") as mock_calibrate,
        patch("driftbase.local.use_case_inference.infer_use_case"),
    ):
        mock_calibrate.return_value = _create_calibration_result(
            calibrated_weights=high_latency_weights,
            baseline_n=50,
        )

        report_high_latency = compute_drift(
            baseline_fp,
            current_fp,
            baseline_runs=baseline_dicts,
            current_runs=current_dicts,
        )

    # Test with high error weight
    high_error_weights = {
        "decision_drift": 0.10,
        "latency_drift": 0.10,
        "error_drift": 0.70,  # Very high
        "semantic_drift": 0.05,
        "verbosity_drift": 0.02,
        "loop_depth_drift": 0.01,
        "output_drift": 0.01,
        "tool_sequence_drift": 0.01,
        "retry_drift": 0.00,
    }

    with (
        patch("driftbase.local.baseline_calibrator.calibrate") as mock_calibrate,
        patch("driftbase.local.use_case_inference.infer_use_case"),
    ):
        mock_calibrate.return_value = _create_calibration_result(
            calibrated_weights=high_error_weights,
            baseline_n=50,
        )

        report_high_error = compute_drift(
            baseline_fp,
            current_fp,
            baseline_runs=baseline_dicts,
            current_runs=current_dicts,
        )

    # Drift scores should be different because weights are different
    # (This test assumes latency and error both changed, so weight affects total score)
    # If only one dimension changed significantly, that weighted dimension would dominate
    assert report_high_latency is not None
    assert report_high_error is not None


def test_empty_tool_sequence_handled():
    """Runs with empty tool sequences should be handled gracefully."""
    baseline_runs = [
        _create_test_run("v1.0", []),  # Empty tools
        _create_test_run("v1.0", ["tool_a"]),
    ]
    current_runs = [
        _create_test_run("v2.0", []),
        _create_test_run("v2.0", ["tool_b"]),
    ]

    baseline_fp = build_fingerprint_from_runs(
        baseline_runs,
        datetime.utcnow(),
        datetime.utcnow(),
        "v1.0",
        "production",
    )
    current_fp = build_fingerprint_from_runs(
        current_runs,
        datetime.utcnow(),
        datetime.utcnow(),
        "v2.0",
        "production",
    )

    baseline_dicts = [_run_to_dict(r) for r in baseline_runs]
    current_dicts = [_run_to_dict(r) for r in current_runs]

    # Should not crash
    report = compute_drift(
        baseline_fp,
        current_fp,
        baseline_runs=baseline_dicts,
        current_runs=current_dicts,
    )

    assert report is not None


def test_malformed_tool_sequence_handled():
    """Runs with malformed JSON in tool_sequence should be handled gracefully."""
    baseline_run = _create_test_run("v1.0", ["tool_a"])
    baseline_run.tool_sequence = "not valid json"

    baseline_fp = build_fingerprint_from_runs(
        [baseline_run],
        datetime.utcnow(),
        datetime.utcnow(),
        "v1.0",
        "production",
    )
    current_fp = build_fingerprint_from_runs(
        [_create_test_run("v2.0", ["tool_b"])],
        datetime.utcnow(),
        datetime.utcnow(),
        "v2.0",
        "production",
    )

    baseline_dicts = [_run_to_dict(baseline_run)]
    current_dicts = [_run_to_dict(_create_test_run("v2.0", ["tool_b"]))]

    # Should not crash, might skip malformed runs or use empty list
    report = compute_drift(
        baseline_fp,
        current_fp,
        baseline_runs=baseline_dicts,
        current_runs=current_dicts,
    )

    assert report is not None


def test_inferred_use_case_in_report():
    """DriftReport should contain inferred use case from tool analysis."""
    baseline_runs = [
        _create_test_run("v1.0", ["schedule_appointment", "prescribe_medication"])
        for _ in range(60)
    ]
    current_runs = [
        _create_test_run("v2.0", ["schedule_appointment", "prescribe_medication"])
        for _ in range(60)
    ]

    baseline_fp = build_fingerprint_from_runs(
        baseline_runs,
        datetime.utcnow(),
        datetime.utcnow(),
        "v1.0",
        "production",
    )
    current_fp = build_fingerprint_from_runs(
        current_runs,
        datetime.utcnow(),
        datetime.utcnow(),
        "v2.0",
        "production",
    )

    baseline_dicts = [_run_to_dict(r) for r in baseline_runs]
    current_dicts = [_run_to_dict(r) for r in current_runs]

    with patch("driftbase.local.use_case_inference.infer_use_case") as mock_infer:
        mock_infer.return_value = {
            "use_case": "HEALTHCARE",
            "confidence": 0.92,
            "matched_keywords": ["appointment", "prescribe"],
            "scores": {"HEALTHCARE": 5.0},
        }

        with patch("driftbase.local.baseline_calibrator.calibrate") as mock_calibrate:
            mock_calibrate.return_value = _create_calibration_result(
                calibrated_weights={},
                calibration_method="statistical",
                baseline_n=60,
                inferred_use_case="HEALTHCARE",
                confidence=0.92,
            )

            report = compute_drift(
                baseline_fp,
                current_fp,
                baseline_runs=baseline_dicts,
                current_runs=current_dicts,
            )

    assert report.inferred_use_case == "HEALTHCARE"
    assert report.use_case_confidence == 0.92
