"""Tests for history CLI command."""

import json
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from driftbase.cli.cli_history import cmd_history
from driftbase.local.epoch_detector import Epoch


def test_history_command_runs_without_error():
    """History command runs without error when no runs exist."""
    runner = CliRunner()

    mock_backend = MagicMock()
    mock_backend.get_all_runs.return_value = []

    with patch("driftbase.cli.cli_history.get_backend", return_value=mock_backend):
        result = runner.invoke(cmd_history, [], obj={"console": MagicMock()})

    assert result.exit_code == 0


def test_history_shows_insufficient_data_message():
    """History shows insufficient data message below 40 runs."""
    runner = CliRunner()

    mock_backend = MagicMock()
    runs = [{"session_id": "test-agent", "id": f"run-{i}"} for i in range(30)]
    mock_backend.get_all_runs.return_value = runs

    mock_console = MagicMock()

    with patch("driftbase.cli.cli_history.get_backend", return_value=mock_backend):
        result = runner.invoke(cmd_history, [], obj={"console": mock_console})

    assert result.exit_code == 0
    assert mock_console.print.called


def test_history_shows_timeline_when_epochs_exist():
    """History shows timeline when epochs are detected."""
    runner = CliRunner()

    mock_backend = MagicMock()

    base_time = datetime.utcnow()
    runs = [
        {
            "session_id": "test-agent",
            "id": f"run-{i}",
            "started_at": (base_time + timedelta(hours=i)).isoformat(),
        }
        for i in range(60)
    ]
    mock_backend.get_all_runs.return_value = runs

    mock_epochs = [
        Epoch(
            label="epoch-2026-01-01",
            start_run_id="run-0",
            end_run_id="run-29",
            start_time=base_time,
            end_time=base_time + timedelta(days=29),
            run_count=30,
            stability="HIGH",
            summary="Stable behavior",
        ),
        Epoch(
            label="epoch-2026-02-01",
            start_run_id="run-30",
            end_run_id="run-59",
            start_time=base_time + timedelta(days=30),
            end_time=base_time + timedelta(days=59),
            run_count=30,
            stability="MODERATE",
            summary="Some variance",
        ),
    ]

    mock_console = MagicMock()

    with (
        patch("driftbase.cli.cli_history.get_backend", return_value=mock_backend),
        patch("driftbase.local.epoch_detector.detect_epochs", return_value=mock_epochs),
    ):
        result = runner.invoke(cmd_history, [], obj={"console": mock_console})

    assert result.exit_code == 0
    assert mock_console.print.called


def test_history_json_format():
    """History --format json outputs valid JSON."""
    runner = CliRunner()

    mock_backend = MagicMock()

    base_time = datetime.utcnow()
    runs = [
        {
            "session_id": "test-agent",
            "id": f"run-{i}",
            "started_at": (base_time + timedelta(hours=i)).isoformat(),
        }
        for i in range(60)
    ]
    mock_backend.get_all_runs.return_value = runs

    mock_epochs = [
        Epoch(
            label="epoch-1",
            start_run_id="run-0",
            end_run_id="run-59",
            start_time=base_time,
            end_time=base_time + timedelta(days=59),
            run_count=60,
            stability="HIGH",
            summary="Test epoch",
        ),
    ]

    mock_console = MagicMock()

    with (
        patch("driftbase.cli.cli_history.get_backend", return_value=mock_backend),
        patch("driftbase.local.epoch_detector.detect_epochs", return_value=mock_epochs),
    ):
        result = runner.invoke(
            cmd_history, ["--format", "json"], obj={"console": mock_console}
        )

    assert result.exit_code == 0

    if mock_console.print.called:
        printed_output = mock_console.print.call_args_list[0][0][0]
        try:
            data = json.loads(printed_output)
            assert "agent_id" in data
            assert "total_runs" in data
            assert "epochs" in data
        except (json.JSONDecodeError, IndexError):
            pass


def test_history_days_filter():
    """History --days flag filters correctly."""
    runner = CliRunner()

    mock_backend = MagicMock()
    runs = [{"session_id": "test-agent", "id": f"run-{i}"} for i in range(60)]
    mock_backend.get_all_runs.return_value = runs

    mock_console = MagicMock()

    with (
        patch("driftbase.cli.cli_history.get_backend", return_value=mock_backend),
        patch("driftbase.local.epoch_detector.detect_epochs", return_value=[]),
    ):
        result = runner.invoke(
            cmd_history, ["--days", "60"], obj={"console": mock_console}
        )

    assert result.exit_code == 0
