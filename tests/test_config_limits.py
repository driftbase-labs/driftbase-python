"""
Tests for unified configuration limits across engine and CLI paths.

Ensures that engine.compute_drift and CLI diff commands use the same
limits when run on identical data.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest


def test_engine_uses_fingerprint_limit():
    """
    engine.compute_drift should use DRIFTBASE_FINGERPRINT_LIMIT for get_runs.
    """
    from driftbase.engine import compute_drift

    mock_backend = MagicMock()
    mock_backend.get_runs.return_value = []

    with (
        patch("driftbase.backends.factory.get_backend", return_value=mock_backend),
        patch.dict(os.environ, {"DRIFTBASE_FINGERPRINT_LIMIT": "3000"}),
    ):
        try:
            compute_drift("v1.0", "v2.0")
        except ValueError:
            # Expected - no runs found, but we just want to check the limit
            pass

        # Verify get_runs was called with limit=3000
        calls = mock_backend.get_runs.call_args_list
        assert len(calls) == 2  # baseline and current
        assert calls[0].kwargs["limit"] == 3000
        assert calls[1].kwargs["limit"] == 3000


def test_cli_diff_uses_fingerprint_limit():
    """
    CLI diff_local should use DRIFTBASE_FINGERPRINT_LIMIT for get_runs.
    """
    from driftbase.cli.cli_diff import diff_local

    mock_backend = MagicMock()
    mock_backend.get_runs.return_value = []

    with patch.dict(os.environ, {"DRIFTBASE_FINGERPRINT_LIMIT": "4000"}):
        report, baseline_fp, current_fp, err = diff_local(
            mock_backend,
            "v1.0",
            "v2.0",
            environment="production",
        )

        # Should have error due to insufficient data, but check the limits
        assert err is not None

        # Verify get_runs was called with limit=4000
        # get_runs_for_version internally calls get_runs
        # We should see calls with limit=4000
        calls = [
            call
            for call in mock_backend.get_runs.call_args_list
            if "limit" in call.kwargs
        ]
        # Should have at least 2 calls (baseline and current)
        assert len(calls) >= 2
        assert all(call.kwargs["limit"] == 4000 for call in calls)


def test_bootstrap_iterations_configurable():
    """
    Bootstrap iterations should be configurable via DRIFTBASE_BOOTSTRAP_ITERS.
    """
    from driftbase.config import get_settings

    # Test default
    settings = get_settings()
    assert settings.DRIFTBASE_BOOTSTRAP_ITERS == 500

    # Test custom value
    with patch.dict(os.environ, {"DRIFTBASE_BOOTSTRAP_ITERS": "1000"}):
        from driftbase.config import Settings

        settings = Settings()
        assert settings.DRIFTBASE_BOOTSTRAP_ITERS == 1000


def test_fingerprint_limit_configurable():
    """
    Fingerprint limit should be configurable via DRIFTBASE_FINGERPRINT_LIMIT.
    """
    from driftbase.config import get_settings

    # Test default
    settings = get_settings()
    assert settings.DRIFTBASE_FINGERPRINT_LIMIT == 5000

    # Test custom value
    with patch.dict(os.environ, {"DRIFTBASE_FINGERPRINT_LIMIT": "10000"}):
        from driftbase.config import Settings

        settings = Settings()
        assert settings.DRIFTBASE_FINGERPRINT_LIMIT == 10000
