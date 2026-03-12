"""
Lightweight config via os.environ. No pydantic-settings or .env required.
Sensible defaults so the SDK works out-of-the-box for local developers.
"""

from __future__ import annotations

import os
from typing import Optional


def _env_bool(key: str, default: bool) -> bool:
    raw = os.environ.get(key)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _env_int(key: str, default: int, min_val: Optional[int] = None) -> int:
    raw = os.environ.get(key)
    if raw is None:
        return default
    try:
        val = int(raw.strip())
        if min_val is not None and val < min_val:
            return min_val
        return val
    except ValueError:
        return default


class Settings:
    """
    Read-only settings from environment. All defaults are tuned for local dev.
    """

    def __init__(self) -> None:
        # Local SQLite path (expanded); same default as backends.factory
        _path = os.environ.get("DRIFTBASE_DB_PATH", "~/.driftbase/runs.db")
        self._db_path = os.path.expanduser(_path)

    @property
    def DRIFTBASE_DB_PATH(self) -> str:
        """Path to the local SQLite database. Default: ~/.driftbase/runs.db"""
        return self._db_path

    @property
    def DRIFTBASE_OUTPUT_COLOR(self) -> bool:
        """Whether CLI output uses color. Default: True. Set DRIFTBASE_OUTPUT_COLOR=0 to disable."""
        return _env_bool("DRIFTBASE_OUTPUT_COLOR", True)

    @property
    def DRIFTBASE_MIN_SAMPLES(self) -> int:
        """Minimum number of runs required to compute a fingerprint. Default: 10."""
        return _env_int("DRIFTBASE_MIN_SAMPLES", 10, min_val=1)

    @property
    def DRIFTBASE_BASELINE_DAYS(self) -> int:
        """Number of days for temporal baseline window. Default: 7."""
        return _env_int("DRIFTBASE_BASELINE_DAYS", 7, min_val=1)

    @property
    def DRIFTBASE_CURRENT_HOURS(self) -> int:
        """Number of hours for current window in temporal drift. Default: 24."""
        return _env_int("DRIFTBASE_CURRENT_HOURS", 24, min_val=1)

    @property
    def DRIFTBASE_LOCAL_RETENTION_LIMIT(self) -> int:
        """Maximum number of runs to keep in the local SQLite database. Default: 10000."""
        return _env_int("DRIFTBASE_LOCAL_RETENTION_LIMIT", 10000, min_val=1)

    @property
    def DRIFTBASE_SCRUB_PII(self) -> bool:
        """
        Enable PII scrubbing by default. 
        Critical for EU AI Act and GDPR compliance.
        Set DRIFTBASE_SCRUB_PII=0 to disable.
        """
        return _env_bool("DRIFTBASE_SCRUB_PII", True)


_settings: Optional[Settings] = None


def get_settings() -> Settings:
    """Return the singleton Settings instance (reads from os.environ, no .env file)."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings