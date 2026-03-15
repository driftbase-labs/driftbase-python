"""
Factory for storage backend: SQLite only (reads DRIFTBASE_DB_PATH).
"""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path

from driftbase.backends.base import StorageBackend
from driftbase.backends.sqlite import SQLiteBackend

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_cached_backend: StorageBackend | None = None


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


def _create_backend() -> StorageBackend:
    """Create SQLite backend from env (caller must hold _lock if mutating _cached_backend)."""
    env_path = os.getenv("DRIFTBASE_DB_PATH")
    if env_path:
        # User explicitly set the path, use it as-is (expand ~ if present)
        db_path = os.path.expanduser(env_path)
    else:
        # Use fallback chain for default path
        db_path = _resolve_db_path_with_fallbacks()

    return SQLiteBackend(db_path)


def get_backend() -> StorageBackend:
    """Return the configured storage backend (cached, thread-safe)."""
    global _cached_backend
    if _cached_backend is not None:
        return _cached_backend
    with _lock:
        if _cached_backend is None:
            _cached_backend = _create_backend()
    return _cached_backend


def clear_backend() -> None:
    """Clear the cached backend (for tests that change env and need a fresh backend)."""
    global _cached_backend
    with _lock:
        _cached_backend = None
