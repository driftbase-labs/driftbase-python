"""Tests for version resolution in @track decorator."""

import os
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pytest

from driftbase.sdk.track import _resolve_version


def test_explicit_version_is_used():
    """Explicit version string is used as-is."""
    assert _resolve_version("v1.0") == "v1.0"
    assert _resolve_version("my-version") == "my-version"
    assert _resolve_version("") == ""


def test_env_var_used_when_version_none():
    """DRIFTBASE_VERSION env var is used when version=None."""
    with patch.dict(os.environ, {"DRIFTBASE_VERSION": "v-from-env"}):
        assert _resolve_version(None) == "v-from-env"


def test_git_tag_used_when_available():
    """Git tag at HEAD is used when available and version=None."""
    with patch.dict(os.environ, {}, clear=False):
        # Remove DRIFTBASE_VERSION if present
        os.environ.pop("DRIFTBASE_VERSION", None)

        # Mock subprocess to return a git tag
        with patch("subprocess.run") as mock_run:
            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = "v1.2.3\n"
            mock_run.return_value = mock_result

            assert _resolve_version(None) == "v1.2.3"


def test_time_based_epoch_fallback():
    """Time-based epoch label is used when no version, no env var, no git tag."""
    with patch.dict(os.environ, {}, clear=False):
        # Remove DRIFTBASE_VERSION if present
        os.environ.pop("DRIFTBASE_VERSION", None)

        # Mock subprocess to simulate git tag not found
        with patch("subprocess.run") as mock_run:
            mock_result = MagicMock()
            mock_result.returncode = 1  # Git command failed
            mock_result.stdout = ""
            mock_run.return_value = mock_result

            # Calculate expected epoch
            today = date.today()
            monday = today - timedelta(days=today.weekday())
            expected = f"epoch-{monday.isoformat()}"

            assert _resolve_version(None) == expected


def test_same_week_gets_same_epoch():
    """Two runs in the same week get the same epoch label."""
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("DRIFTBASE_VERSION", None)

        with patch("subprocess.run") as mock_run:
            mock_result = MagicMock()
            mock_result.returncode = 1
            mock_result.stdout = ""
            mock_run.return_value = mock_result

            # Get epoch twice
            epoch1 = _resolve_version(None)
            epoch2 = _resolve_version(None)

            # Should be identical
            assert epoch1 == epoch2
            assert epoch1.startswith("epoch-")


def test_never_raises():
    """_resolve_version never raises on any input."""
    # Test with various edge cases
    assert isinstance(_resolve_version(None), str)
    assert isinstance(_resolve_version(""), str)
    assert isinstance(_resolve_version("v1.0"), str)

    # Test with subprocess failures
    with patch("subprocess.run", side_effect=Exception("Git failed")):
        result = _resolve_version(None)
        assert isinstance(result, str)
        assert result.startswith("epoch-")

    # Test with timeout
    with patch("subprocess.run", side_effect=TimeoutError("Git timeout")):
        result = _resolve_version(None)
        assert isinstance(result, str)
        assert result.startswith("epoch-")


def test_priority_order():
    """Version resolution follows correct priority order."""
    # Priority 1: Explicit version wins over everything
    with (
        patch.dict(os.environ, {"DRIFTBASE_VERSION": "from-env"}),
        patch("subprocess.run") as mock_run,
    ):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "from-git"
        mock_run.return_value = mock_result

        assert _resolve_version("explicit") == "explicit"

    # Priority 2: Env var wins over git
    with (
        patch.dict(os.environ, {"DRIFTBASE_VERSION": "from-env"}),
        patch("subprocess.run") as mock_run,
    ):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "from-git"
        mock_run.return_value = mock_result

        assert _resolve_version(None) == "from-env"

    # Priority 3: Git tag wins over time-based epoch
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("DRIFTBASE_VERSION", None)

        with patch("subprocess.run") as mock_run:
            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = "from-git"
            mock_run.return_value = mock_result

            result = _resolve_version(None)
            assert result == "from-git"
            assert not result.startswith("epoch-")
