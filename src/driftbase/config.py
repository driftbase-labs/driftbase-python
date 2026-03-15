"""
Lightweight config via os.environ with automatic .env loading.

Security best practices:
- Auto-loads .env file if present (for local development)
- Production environments should use real environment variables
- Sensible defaults for local developers (SQLite, no DATABASE_URL required)
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# Load .env file if present (idempotent - safe to call multiple times)
def _load_dotenv():
    """Load .env file for local development (production uses real env vars)."""
    try:
        from dotenv import load_dotenv

        env_path = Path.cwd() / ".env"
        if env_path.exists():
            load_dotenv(dotenv_path=env_path, override=False)
            logger.debug("Loaded environment from .env file")
    except ImportError:
        logger.debug("python-dotenv not available, skipping .env load")
    except Exception as e:
        logger.debug("Failed to load .env: %s", e)


# Load .env on module import (idempotent)
_load_dotenv()


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


def _resolve_db_path_with_fallbacks() -> str:
    """
    Resolve the database path with a robust fallback chain for environments
    where Path.home() fails (Docker, CI, restricted environments, etc.).

    Fallback chain:
    1. Try ~/.driftbase/runs.db (Path.home())
    2. Fall back to /tmp/driftbase/runs.db
    3. Fall back to ./.driftbase/runs.db (current working directory)

    This ensures the SDK works in restricted environments without requiring
    explicit DRIFTBASE_DB_PATH configuration.
    """
    # 1. Try Path.home() first (most common case)
    try:
        home_path = Path.home() / ".driftbase" / "runs.db"
        return str(home_path)
    except Exception as e:
        logger.debug("Path.home() failed (%s), trying /tmp fallback", e)

    # 2. Fall back to /tmp
    try:
        tmp_path = Path("/tmp") / "driftbase" / "runs.db"
        return str(tmp_path)
    except Exception as e:
        logger.debug("/tmp fallback failed (%s), trying cwd fallback", e)

    # 3. Final fallback to current working directory
    try:
        cwd_path = Path.cwd() / ".driftbase" / "runs.db"
        return str(cwd_path)
    except Exception as e:
        logger.error("All database path fallbacks failed: %s", e)
        raise RuntimeError(
            "Could not resolve a writable database path. "
            "Please set DRIFTBASE_DB_PATH explicitly to a writable location."
        ) from e


class Settings:
    """
    Read-only settings from environment. All defaults are tuned for local dev.
    """

    def __init__(self) -> None:
        # Local SQLite path with fallback chain for restricted environments
        env_path = os.environ.get("DRIFTBASE_DB_PATH")
        if env_path:
            # User explicitly set the path, use it as-is (expand ~ if present)
            self._db_path = os.path.expanduser(env_path)
        else:
            # Use fallback chain for default path
            self._db_path = _resolve_db_path_with_fallbacks()

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
