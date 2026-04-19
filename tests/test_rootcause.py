"""
Tests for root cause pinpointing functionality.
"""

import os
import tempfile
from datetime import datetime

import pytest

from driftbase.backends.sqlite import SQLiteBackend
from driftbase.local.local_store import DriftReport
from driftbase.local.rootcause import RootCauseReport, correlate_drift_with_changes


class TestCorrelateNoChanges:
    """Tests for correlation when no change events exist."""

    def test_no_change_events_returns_empty_report(self):
        """No change events → RootCauseReport with has_changes=False."""
        report = DriftReport()
        report.decision_drift = 0.5
        report.error_drift = 0.3

        change_events = {"v1": [], "v2": []}
        drifted_dimensions = ["decision_drift", "error_drift"]

        result = correlate_drift_with_changes(report, change_events, drifted_dimensions)

        assert result.has_changes is False
        assert result.winner is None
        assert result.winner_confidence is None
        assert result.suggested_action is not None  # Should suggest recording changes


class TestCorrelateHighConfidence:
    """Tests for correlation with high confidence match."""

    def test_model_version_change_all_dims_correlate_high_confidence(self):
        """Model version change, all drifted dims correlate → HIGH confidence."""
        report = DriftReport()
        report.decision_drift = 0.5
        report.error_drift = 0.3

        change_events = {
            "v1": [
                {
                    "change_type": "model_version",
                    "current": "gpt-4o-2024-03",
                    "previous": None,
                }
            ],
            "v2": [
                {
                    "change_type": "model_version",
                    "current": "gpt-4o-2024-11",
                    "previous": None,
                }
            ],
        }

        # Both dimensions correlate with model_version
        drifted_dimensions = ["decision_drift", "error_drift"]

        result = correlate_drift_with_changes(report, change_events, drifted_dimensions)

        assert result.has_changes is True
        assert result.winner == "model_version"
        assert result.winner_confidence == "HIGH"
        assert result.winner_score == 1.0  # 2/2 dimensions
        assert result.winner_previous == "gpt-4o-2024-03"
        assert result.winner_current == "gpt-4o-2024-11"
        assert set(result.affected_dimensions) == {"decision_drift", "error_drift"}


class TestCorrelateMediumConfidence:
    """Tests for correlation with medium confidence match."""

    def test_prompt_hash_change_partial_correlation_medium_confidence(self):
        """Prompt hash change, partial correlation → MEDIUM confidence."""
        report = DriftReport()
        report.decision_drift = 0.5
        report.latency_drift = 0.3  # Doesn't correlate with prompt_hash

        change_events = {
            "v1": [
                {
                    "change_type": "prompt_hash",
                    "current": "sha256:abc123",
                    "previous": None,
                }
            ],
            "v2": [
                {
                    "change_type": "prompt_hash",
                    "current": "sha256:def456",
                    "previous": None,
                }
            ],
        }

        drifted_dimensions = ["decision_drift", "latency_drift"]

        result = correlate_drift_with_changes(report, change_events, drifted_dimensions)

        assert result.has_changes is True
        assert result.winner == "prompt_hash"
        assert result.winner_confidence == "MEDIUM"  # score = 0.5 (1/2)
        assert 0.45 < result.winner_score < 0.55
        assert "decision_drift" in result.affected_dimensions
        assert "latency_drift" not in result.affected_dimensions


class TestCorrelateNoDrift:
    """Tests for correlation when change recorded but no drift."""

    def test_change_recorded_but_no_drift_unlikely(self):
        """Change recorded but no drift detected → UNLIKELY for all."""
        report = DriftReport()
        report.decision_drift = 0.0  # No drift

        change_events = {
            "v1": [
                {
                    "change_type": "model_version",
                    "current": "gpt-4o-2024-03",
                }
            ],
            "v2": [
                {
                    "change_type": "model_version",
                    "current": "gpt-4o-2024-11",
                }
            ],
        }

        drifted_dimensions = []  # No drifted dimensions

        result = correlate_drift_with_changes(report, change_events, drifted_dimensions)

        assert result.has_changes is True
        assert result.winner is None or result.winner_confidence == "UNLIKELY"


class TestCorrelateMultipleChanges:
    """Tests for correlation with multiple changes."""

    def test_multiple_changes_correct_winner_selected(self):
        """Multiple changes recorded, correct winner selected."""
        report = DriftReport()
        report.decision_drift = 0.5
        report.latency_drift = 0.3

        change_events = {
            "v1": [
                {
                    "change_type": "model_version",
                    "current": "gpt-4o-2024-03",
                },
                {
                    "change_type": "rag_snapshot",
                    "current": "snapshot-old",
                },
            ],
            "v2": [
                {
                    "change_type": "model_version",
                    "current": "gpt-4o-2024-11",
                },
                {
                    "change_type": "rag_snapshot",
                    "current": "snapshot-new",
                },
            ],
        }

        # Both dims correlate better with model_version than rag_snapshot
        drifted_dimensions = ["decision_drift", "latency_drift"]

        result = correlate_drift_with_changes(report, change_events, drifted_dimensions)

        assert result.has_changes is True
        assert result.winner == "model_version"  # Better correlation
        assert "rag_snapshot" in result.all_scores


class TestCorrelateRuledOut:
    """Tests for ruled out changes."""

    def test_ruled_out_list_correct_when_change_identical(self):
        """Ruled out list correct when change is identical between versions."""
        report = DriftReport()
        report.decision_drift = 0.5

        change_events = {
            "v1": [
                {
                    "change_type": "model_version",
                    "current": "gpt-4o-2024-11",
                },
                {
                    "change_type": "prompt_hash",
                    "current": "sha256:abc123",
                },
            ],
            "v2": [
                {
                    "change_type": "model_version",
                    "current": "gpt-4o-2024-11",  # Same as v1
                },
                {
                    "change_type": "prompt_hash",
                    "current": "sha256:def456",  # Different from v1
                },
            ],
        }

        drifted_dimensions = ["decision_drift"]

        result = correlate_drift_with_changes(report, change_events, drifted_dimensions)

        assert "model_version" in result.ruled_out
        assert "prompt_hash" not in result.ruled_out


class TestSuggestedAction:
    """Tests for suggested action content."""

    def test_suggested_action_contains_v1_v2_values_for_model_version(self):
        """Suggested action contains v1/v2 values for model_version winner."""
        report = DriftReport()
        report.decision_drift = 0.5

        change_events = {
            "v1": [
                {
                    "change_type": "model_version",
                    "current": "gpt-4o-2024-03",
                }
            ],
            "v2": [
                {
                    "change_type": "model_version",
                    "current": "gpt-4o-2024-11",
                }
            ],
        }

        drifted_dimensions = ["decision_drift"]

        result = correlate_drift_with_changes(report, change_events, drifted_dimensions)

        assert result.suggested_action is not None
        assert "gpt-4o-2024-03" in result.suggested_action
        assert "gpt-4o-2024-11" in result.suggested_action


class TestDatabaseRoundTrip:
    """Tests for database operations."""

    def test_write_and_get_change_events(self):
        """write_change_event + get_change_events: SQLite round-trip."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            backend = SQLiteBackend(db_path)

            event = {
                "agent_id": "test_agent",
                "version": "v1.0",
                "change_type": "model_version",
                "previous": "gpt-4o-2024-03",
                "current": "gpt-4o-2024-11",
                "source": "decorator",
            }

            backend.write_change_event(event)
            events = backend.get_change_events("test_agent", "v1.0")

            assert len(events) == 1
            assert events[0]["agent_id"] == "test_agent"
            assert events[0]["version"] == "v1.0"
            assert events[0]["change_type"] == "model_version"
            assert events[0]["current"] == "gpt-4o-2024-11"

    def test_unique_constraint_second_write_logs_warning(self):
        """UNIQUE constraint: second write for same agent+version+change_type logs warning."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            backend = SQLiteBackend(db_path)

            event1 = {
                "agent_id": "test_agent",
                "version": "v1.0",
                "change_type": "model_version",
                "current": "gpt-4o-2024-03",
                "source": "decorator",
            }

            event2 = {
                "agent_id": "test_agent",
                "version": "v1.0",
                "change_type": "model_version",
                "current": "gpt-4o-2024-11",  # Different value
                "source": "decorator",
            }

            backend.write_change_event(event1)
            backend.write_change_event(event2)  # Should log warning, not overwrite

            events = backend.get_change_events("test_agent", "v1.0")

            assert len(events) == 1
            assert events[0]["current"] == "gpt-4o-2024-03"  # First value kept


class TestRollbackSuggestion:
    """Tests for rollback suggestion functionality."""

    def test_no_baseline_returns_none(self):
        """No baseline version → returns None."""
        from driftbase.local.rootcause import get_rollback_suggestion

        result = get_rollback_suggestion(
            agent_id="test_agent",
            eval_version="v2.0",
            current_verdict="BLOCK",
            baseline_version=None,
            baseline_run_count=100,
        )

        assert result is None

    def test_block_verdict_with_sufficient_runs_returns_suggestion(self):
        """BLOCK verdict with baseline >= 30 runs → returns suggestion."""
        from driftbase.local.rootcause import get_rollback_suggestion

        result = get_rollback_suggestion(
            agent_id="test_agent",
            eval_version="v2.0",
            current_verdict="BLOCK",
            baseline_version="v1.0",
            baseline_run_count=50,
        )

        assert result is not None
        assert result.suggested_version == "v1.0"
        assert result.suggested_version_verdict == "SHIP"
        assert result.suggested_version_runs == 50
        assert "v1.0" in result.reason
        assert "50 runs" in result.reason

    def test_review_verdict_with_sufficient_runs_returns_suggestion(self):
        """REVIEW verdict with baseline >= 30 runs → returns suggestion."""
        from driftbase.local.rootcause import get_rollback_suggestion

        result = get_rollback_suggestion(
            agent_id="test_agent",
            eval_version="v2.0",
            current_verdict="REVIEW",
            baseline_version="v1.0",
            baseline_run_count=100,
        )

        assert result is not None
        assert result.suggested_version == "v1.0"

    def test_insufficient_runs_returns_none(self):
        """BLOCK verdict with baseline < 30 runs → returns None."""
        from driftbase.local.rootcause import get_rollback_suggestion

        result = get_rollback_suggestion(
            agent_id="test_agent",
            eval_version="v2.0",
            current_verdict="BLOCK",
            baseline_version="v1.0",
            baseline_run_count=20,  # < 30
        )

        assert result is None

    def test_monitor_verdict_returns_none(self):
        """MONITOR verdict → returns None (only BLOCK/REVIEW triggers)."""
        from driftbase.local.rootcause import get_rollback_suggestion

        result = get_rollback_suggestion(
            agent_id="test_agent",
            eval_version="v2.0",
            current_verdict="MONITOR",
            baseline_version="v1.0",
            baseline_run_count=100,
        )

        assert result is None

    def test_ship_verdict_returns_none(self):
        """SHIP verdict → returns None."""
        from driftbase.local.rootcause import get_rollback_suggestion

        result = get_rollback_suggestion(
            agent_id="test_agent",
            eval_version="v2.0",
            current_verdict="SHIP",
            baseline_version="v1.0",
            baseline_run_count=100,
        )

        assert result is None

    def test_same_version_returns_none(self):
        """Baseline same as eval version → returns None."""
        from driftbase.local.rootcause import get_rollback_suggestion

        result = get_rollback_suggestion(
            agent_id="test_agent",
            eval_version="v1.0",
            current_verdict="BLOCK",
            baseline_version="v1.0",  # Same
            baseline_run_count=100,
        )

        assert result is None

    def test_never_raises_on_malformed_input(self):
        """Never raises on any input including empty/malformed data."""
        from driftbase.local.rootcause import get_rollback_suggestion

        # Try various malformed inputs
        result = get_rollback_suggestion(
            agent_id="",
            eval_version="",
            current_verdict="INVALID",
            baseline_version="v1.0",
            baseline_run_count=-1,
        )
        assert result is None  # Should not raise

        result = get_rollback_suggestion(
            agent_id="test",
            eval_version="v2.0",
            current_verdict="BLOCK",
            baseline_version="",
            baseline_run_count=100,
        )
        assert result is None  # Should not raise
