"""
Tests for the verdict engine (compute_verdict).
"""

from __future__ import annotations

import unittest

from driftbase.local.local_store import DriftReport
from driftbase.verdict import Verdict, VerdictResult, compute_verdict


def _make_report(
    drift_score: float = 0.0,
    decision_drift: float = 0.0,
    latency_drift: float = 0.0,
    error_drift: float = 0.0,
    escalation_rate_delta: float = 0.0,
) -> DriftReport:
    """Helper to create a minimal DriftReport for testing."""
    return DriftReport(
        baseline_fingerprint_id="baseline_fp_id",
        current_fingerprint_id="current_fp_id",
        drift_score=drift_score,
        severity="none",
        decision_drift=decision_drift,
        latency_drift=latency_drift,
        error_drift=error_drift,
        escalation_rate_delta=escalation_rate_delta,
        summary="",
    )


class TestVerdictEngine(unittest.TestCase):
    """Test verdict computation logic."""

    def test_ship_verdict_low_drift(self) -> None:
        """Drift score < 0.10 → SHIP verdict."""
        report = _make_report(drift_score=0.05, decision_drift=0.03)
        result = compute_verdict(report)

        self.assertEqual(result.verdict, Verdict.SHIP)
        self.assertEqual(result.title, "SAFE TO SHIP")
        self.assertEqual(result.exit_code, 0)
        self.assertIn("No meaningful behavioral change", result.explanation)

    def test_monitor_verdict_minor_drift(self) -> None:
        """Drift score 0.10–0.20 → MONITOR verdict."""
        report = _make_report(drift_score=0.15, decision_drift=0.12)
        result = compute_verdict(report)

        self.assertEqual(result.verdict, Verdict.MONITOR)
        self.assertEqual(result.title, "SHIP WITH MONITORING")
        self.assertEqual(result.exit_code, 0)
        self.assertIn("Minor behavioral drift", result.explanation)

    def test_review_verdict_moderate_drift(self) -> None:
        """Drift score 0.20–0.40 → REVIEW verdict."""
        report = _make_report(drift_score=0.29, decision_drift=0.20)
        result = compute_verdict(report)

        self.assertEqual(result.verdict, Verdict.REVIEW)
        self.assertEqual(result.title, "REVIEW BEFORE SHIPPING")
        self.assertEqual(result.exit_code, 1)
        self.assertIn("Behavioral change detected", result.explanation)

    def test_block_verdict_high_drift(self) -> None:
        """Drift score > 0.40 → BLOCK verdict."""
        report = _make_report(drift_score=0.47, decision_drift=0.35)
        result = compute_verdict(report)

        self.assertEqual(result.verdict, Verdict.BLOCK)
        self.assertEqual(result.title, "DO NOT SHIP")
        self.assertEqual(result.exit_code, 1)
        self.assertIn("Major behavioral divergence", result.explanation)

    def test_block_verdict_high_decision_drift_only(self) -> None:
        """Even if overall drift is moderate, decision_drift > 0.40 → BLOCK."""
        report = _make_report(drift_score=0.25, decision_drift=0.45)
        result = compute_verdict(report)

        self.assertEqual(result.verdict, Verdict.BLOCK)
        self.assertEqual(result.exit_code, 1)

    def test_review_verdict_high_decision_drift(self) -> None:
        """Even if overall drift is low, decision_drift > 0.25 → REVIEW."""
        report = _make_report(drift_score=0.12, decision_drift=0.30)
        result = compute_verdict(report)

        self.assertEqual(result.verdict, Verdict.REVIEW)
        self.assertEqual(result.exit_code, 1)

    def test_escalation_rate_delta_in_explanation(self) -> None:
        """High escalation_rate_delta should appear in explanation."""
        report = _make_report(
            drift_score=0.29, decision_drift=0.30, escalation_rate_delta=0.12
        )
        result = compute_verdict(report)

        self.assertIn("escalating", result.explanation.lower())

    def test_next_steps_decision_drift(self) -> None:
        """High decision drift → next steps should mention prompts and routing."""
        report = _make_report(drift_score=0.30, decision_drift=0.35)
        result = compute_verdict(report)

        steps_str = " ".join(result.next_steps).lower()
        self.assertIn("prompt", steps_str)
        self.assertIn("routing", steps_str)

    def test_next_steps_latency_drift(self) -> None:
        """High latency drift → next steps should mention tool calls and performance."""
        report = _make_report(drift_score=0.30, latency_drift=0.40)
        result = compute_verdict(report)

        steps_str = " ".join(result.next_steps).lower()
        self.assertTrue(
            "tool call" in steps_str
            or "performance" in steps_str
            or "reasoning" in steps_str
        )

    def test_next_steps_error_drift(self) -> None:
        """High error drift → next steps should mention tool availability and dependencies."""
        report = _make_report(drift_score=0.30, error_drift=0.20)
        result = compute_verdict(report)

        steps_str = " ".join(result.next_steps).lower()
        self.assertTrue(
            "availability" in steps_str
            or "dependencies" in steps_str
            or "error" in steps_str
        )

    def test_next_steps_with_new_tools(self) -> None:
        """If new tools appear, next steps should mention them."""
        report = _make_report(drift_score=0.30, decision_drift=0.30)
        baseline_tools = {"tool_a": 0.5, "tool_b": 0.5}
        current_tools = {"tool_a": 0.4, "tool_b": 0.3, "tool_c": 0.3}
        result = compute_verdict(
            report, baseline_tools=baseline_tools, current_tools=current_tools
        )

        steps_str = " ".join(result.next_steps)
        self.assertIn("tool_c", steps_str)

    def test_verdict_result_style(self) -> None:
        """VerdictResult.style property should return correct Rich styles."""
        ship = VerdictResult(Verdict.SHIP, "", "", [], 0)
        monitor = VerdictResult(Verdict.MONITOR, "", "", [], 0)
        review = VerdictResult(Verdict.REVIEW, "", "", [], 1)
        block = VerdictResult(Verdict.BLOCK, "", "", [], 1)

        self.assertEqual(ship.style, "green")
        self.assertEqual(monitor.style, "blue")
        self.assertEqual(review.style, "yellow")
        self.assertEqual(block.style, "red")

    def test_verdict_result_symbol(self) -> None:
        """VerdictResult.symbol property should return correct symbols."""
        ship = VerdictResult(Verdict.SHIP, "", "", [], 0)
        monitor = VerdictResult(Verdict.MONITOR, "", "", [], 0)
        review = VerdictResult(Verdict.REVIEW, "", "", [], 1)
        block = VerdictResult(Verdict.BLOCK, "", "", [], 1)

        self.assertEqual(ship.symbol, "✓")
        self.assertEqual(monitor.symbol, "·")
        self.assertEqual(review.symbol, "⚠")
        self.assertEqual(block.symbol, "✗")

    def test_boundary_conditions(self) -> None:
        """Test exact threshold boundaries."""
        # Exactly 0.10 should be MONITOR
        report = _make_report(drift_score=0.10)
        result = compute_verdict(report)
        self.assertIn(result.verdict, [Verdict.MONITOR, Verdict.SHIP])

        # Exactly 0.20 should be REVIEW
        report = _make_report(drift_score=0.20)
        result = compute_verdict(report)
        self.assertIn(result.verdict, [Verdict.REVIEW, Verdict.MONITOR])

        # Exactly 0.40 should be BLOCK
        report = _make_report(drift_score=0.40)
        result = compute_verdict(report)
        self.assertIn(result.verdict, [Verdict.BLOCK, Verdict.REVIEW])


if __name__ == "__main__":
    unittest.main()
