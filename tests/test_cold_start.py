"""Tests for cold start problem solutions."""

import os
from unittest.mock import MagicMock, patch

import pytest


def test_render_progress_bar_zero_runs():
    """Progress bar renders correctly at 0%."""
    from driftbase.cli.cli_diagnose import _render_progress_bar

    bar = _render_progress_bar(0, 40, use_color=False)
    assert "0 / 40" in bar
    assert "(0%)" in bar
    assert "--------------------" in bar  # All empty


def test_render_progress_bar_30_percent():
    """Progress bar renders correctly at 30%."""
    from driftbase.cli.cli_diagnose import _render_progress_bar

    bar = _render_progress_bar(12, 40, use_color=False)
    assert "12 / 40" in bar
    assert "(30%)" in bar
    # 30% = 6 filled out of 20
    assert bar.count("#") == 6
    assert bar.count("-") == 14


def test_render_progress_bar_50_percent():
    """Progress bar renders correctly at 50%."""
    from driftbase.cli.cli_diagnose import _render_progress_bar

    bar = _render_progress_bar(20, 40, use_color=False)
    assert "20 / 40" in bar
    assert "(50%)" in bar
    assert bar.count("#") == 10
    assert bar.count("-") == 10


def test_render_progress_bar_75_percent():
    """Progress bar renders correctly at 75%."""
    from driftbase.cli.cli_diagnose import _render_progress_bar

    bar = _render_progress_bar(30, 40, use_color=False)
    assert "30 / 40" in bar
    assert "(75%)" in bar
    assert bar.count("#") == 15
    assert bar.count("-") == 5


def test_render_progress_bar_100_percent():
    """Progress bar renders correctly at 100%."""
    from driftbase.cli.cli_diagnose import _render_progress_bar

    bar = _render_progress_bar(40, 40, use_color=False)
    assert "40 / 40" in bar
    assert "(100%)" in bar
    assert bar.count("#") == 20
    assert bar.count("-") == 0


def test_render_progress_bar_colored():
    """Progress bar uses colored characters when use_color=True."""
    from driftbase.cli.cli_diagnose import _render_progress_bar

    bar = _render_progress_bar(20, 40, use_color=True)
    assert "█" in bar  # Filled character
    assert "░" in bar  # Empty character


def test_estimate_days_remaining_returns_none_with_insufficient_data():
    """Days remaining estimate returns None when rate cannot be calculated."""
    from driftbase.cli.cli_diagnose import _estimate_days_remaining

    mock_backend = MagicMock()
    mock_backend.get_all_runs.return_value = []

    result = _estimate_days_remaining(mock_backend, 10, 40)
    assert result is None


def test_langsmith_list_projects_returns_empty_on_error():
    """LangSmith list_projects() returns [] on error, never raises."""
    from driftbase.connectors.langsmith import LANGSMITH_AVAILABLE, LangSmithConnector

    if not LANGSMITH_AVAILABLE:
        pytest.skip("LangSmith not installed")

    with (
        patch.dict(os.environ, {"LANGSMITH_API_KEY": "test-key"}),
        patch("driftbase.connectors.langsmith.LangSmithClient") as mock_client,
    ):
        mock_client.return_value.list_projects.side_effect = Exception("API error")

        connector = LangSmithConnector()
        projects = connector.list_projects()

        assert projects == []


def test_langsmith_list_projects_returns_sorted_by_run_count():
    """LangSmith list_projects() returns sorted list by run_count desc."""
    from driftbase.connectors.langsmith import LANGSMITH_AVAILABLE, LangSmithConnector

    if not LANGSMITH_AVAILABLE:
        pytest.skip("LangSmith not installed")

    with (
        patch.dict(os.environ, {"LANGSMITH_API_KEY": "test-key"}),
        patch("driftbase.connectors.langsmith.LangSmithClient") as mock_client,
    ):
        # Mock projects
        proj1 = MagicMock()
        proj1.name = "project-a"
        proj1.run_count = 100

        proj2 = MagicMock()
        proj2.name = "project-b"
        proj2.run_count = 500

        proj3 = MagicMock()
        proj3.name = "project-c"
        proj3.run_count = 50

        mock_client.return_value.list_projects.return_value = [proj1, proj2, proj3]
        mock_client.return_value.list_runs.return_value = []

        connector = LangSmithConnector()
        projects = connector.list_projects()

        # Should be sorted descending by run_count
        assert len(projects) == 3
        assert projects[0]["name"] == "project-b"
        assert projects[0]["run_count"] == 500
        assert projects[1]["name"] == "project-a"
        assert projects[2]["name"] == "project-c"


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

    # Create mock runs (less than 40)
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
    """History shows progress bar when run_count < 40."""
    from driftbase.cli.cli_history import _render_progress_bar

    bar = _render_progress_bar(15, 40, use_color=False)
    assert "15 / 40" in bar
    assert bar.count("#") > 0  # Some filled
    assert bar.count("-") > 0  # Some empty
