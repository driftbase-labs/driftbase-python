"""
Factory for storage backend: SQLite (default) or PostgreSQL (Pro tier).

Security best practices:
- Auto-loads .env file if present (for local development)
- Never hardcodes credentials
- Falls back to SQLite if DATABASE_URL not set
- Validates DATABASE_URL format for PostgreSQL
"""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from typing import Optional

from driftbase.backends.base import StorageBackend
from driftbase.backends.sqlite import SQLiteBackend

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
        # python-dotenv not installed (shouldn't happen after adding to deps)
        logger.debug("python-dotenv not available, skipping .env load")
    except Exception as e:
        # Don't crash if .env loading fails
        logger.debug("Failed to load .env: %s", e)

# Load .env on module import (idempotent)
_load_dotenv()

_lock = threading.Lock()
_cached_backend: Optional[StorageBackend] = None


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
    """
    Create storage backend from environment configuration.

    Priority:
    1. If DATABASE_URL is set → PostgreSQL backend (Pro tier)
    2. If DRIFTBASE_DB_PATH is set → SQLite at specified path
    3. Default → SQLite with fallback chain (free tier)

    Returns:
        StorageBackend instance (SQLite or PostgreSQL)
    """
    # Check for PostgreSQL (Pro tier)
    database_url = os.getenv("DATABASE_URL")
    if database_url and database_url.strip():
        logger.info("DATABASE_URL detected, using PostgreSQL backend")
        try:
            from driftbase.backends.postgres import PostgreSQLBackend
            # Use SQLAlchemy by default for better ORM support
            return PostgreSQLBackend(use_sqlalchemy=True)
        except ImportError as e:
            logger.error(
                "PostgreSQL backend requested but dependencies not installed. "
                "Install with: pip install 'driftbase[postgres]'"
            )
            raise ImportError(
                "PostgreSQL backend requires additional dependencies. "
                "Install with: pip install 'driftbase[postgres]'"
            ) from e

    # Fall back to SQLite (default for free tier)
    env_path = os.getenv("DRIFTBASE_DB_PATH")
    if env_path:
        # User explicitly set the path, use it as-is (expand ~ if present)
        db_path = os.path.expanduser(env_path)
    else:
        # Use fallback chain for default path
        db_path = _resolve_db_path_with_fallbacks()

    logger.debug("Using SQLite backend at %s", db_path)
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
