"""Tests for cold start problem solutions."""

import os
from unittest.mock import MagicMock, patch

import pytest


def test_render_progress_bar_zero_runs():
    """Progress bar renders correctly at 0%."""
    from driftbase.cli.cli_diagnose import _render_progress_bar

    bar = _render_progress_bar(0, 50, use_color=False)
    assert "0 / 50" in bar
    assert "(0%)" in bar
    assert "--------------------" in bar  # All empty


def test_render_progress_bar_30_percent():
    """Progress bar renders correctly at 30%."""
    from driftbase.cli.cli_diagnose import _render_progress_bar

    bar = _render_progress_bar(15, 50, use_color=False)
    assert "15 / 50" in bar
    assert "(30%)" in bar
    # 30% = 6 filled out of 20
    assert bar.count("#") == 6
    assert bar.count("-") == 14


def test_render_progress_bar_50_percent():
    """Progress bar renders correctly at 50%."""
    from driftbase.cli.cli_diagnose import _render_progress_bar

    bar = _render_progress_bar(25, 50, use_color=False)
    assert "25 / 50" in bar
    assert "(50%)" in bar
    assert bar.count("#") == 10
    assert bar.count("-") == 10


def test_render_progress_bar_75_percent():
    """Progress bar renders correctly at 75%."""
    from driftbase.cli.cli_diagnose import _render_progress_bar

    bar = _render_progress_bar(38, 50, use_color=False)
    assert "38 / 50" in bar
    # 38/50 = 76%
    assert "(76%)" in bar
    assert bar.count("#") == 15
    assert bar.count("-") == 5


def test_render_progress_bar_100_percent():
    """Progress bar renders correctly at 100%."""
    from driftbase.cli.cli_diagnose import _render_progress_bar

    bar = _render_progress_bar(50, 50, use_color=False)
    assert "50 / 50" in bar
    assert "(100%)" in bar
    assert bar.count("#") == 20
    assert bar.count("-") == 0


def test_render_progress_bar_colored():
    """Progress bar uses colored characters when use_color=True."""
    from driftbase.cli.cli_diagnose import _render_progress_bar

    bar = _render_progress_bar(25, 50, use_color=True)
    assert "█" in bar  # Filled character
    assert "░" in bar  # Empty character


def test_estimate_days_remaining_returns_none_with_insufficient_data():
    """Days remaining estimate returns None when rate cannot be calculated."""
    from driftbase.cli.cli_diagnose import _estimate_days_remaining

    mock_backend = MagicMock()
    mock_backend.get_all_runs.return_value = []

    result = _estimate_days_remaining(mock_backend, 10, 50)
    assert result is None


def test_langfuse_list_projects_returns_empty_on_error():
    """LangFuse list_projects() returns [] on error, never raises."""
    from driftbase.connectors.langfuse import LANGFUSE_AVAILABLE, LangFuseConnector

    if not LANGFUSE_AVAILABLE:
        pytest.skip("LangFuse not installed")

    with (
        patch.dict(
            os.environ,
            {
                "LANGFUSE_PUBLIC_KEY": "test-public",
                "LANGFUSE_SECRET_KEY": "test-secret",
            },
        ),
        patch("driftbase.connectors.langfuse.Langfuse") as mock_client,
    ):
        mock_client.return_value.get_traces.side_effect = Exception("API error")

        connector = LangFuseConnector()
        projects = connector.list_projects()

        assert projects == []


@patch("driftbase.cli.cli_diagnose.os.environ")
def test_diagnose_shows_langsmith_and_langfuse_in_suggestions(mock_environ):
    """Diagnose shows both LangSmith and LangFuse credentials in suggestions."""
    mock_environ.get.return_value = None  # No credentials set

    from driftbase.backends.factory import get_backend
    from driftbase.cli._deps import safe_import_rich_extended
    from driftbase.cli.cli_diagnose import _diagnose_behavioral_shift

    Console, _, _, _, _, _ = safe_import_rich_extended()
    console = Console()
    backend = get_backend()

    # Create mock runs (less than 50)
    mock_runs = [{"session_id": "test-agent", "id": f"run-{i}"} for i in range(12)]

    with (
        patch.object(backend, "get_all_runs", return_value=mock_runs),
        patch.object(console, "print") as mock_print,
    ):
        _diagnose_behavioral_shift(console, backend)

        # Check that the output mentions both services
        output = " ".join(str(call[0][0]) for call in mock_print.call_args_list)
        assert "LANGSMITH_API_KEY" in output
        assert "LANGFUSE_PUBLIC_KEY" in output or "LANGFUSE_SECRET_KEY" in output


def test_history_shows_progress_bar_with_insufficient_data():
    """History shows progress bar when run_count < 50."""
    from driftbase.cli.cli_history import _render_progress_bar

    bar = _render_progress_bar(15, 50, use_color=False)
    assert "15 / 50" in bar
    assert bar.count("#") > 0  # Some filled
    assert bar.count("-") > 0  # Some empty
