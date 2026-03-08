"""
Factory for storage backend: SQLite only (reads DRIFTBASE_DB_PATH).
"""

from __future__ import annotations

import os
import threading
from typing import Optional

from driftbase.backends.base import StorageBackend
from driftbase.backends.sqlite import SQLiteBackend

_lock = threading.Lock()
_cached_backend: Optional[StorageBackend] = None


def _create_backend() -> StorageBackend:
    """Create SQLite backend from env (caller must hold _lock if mutating _cached_backend)."""
    db_path = os.path.expanduser(os.getenv("DRIFTBASE_DB_PATH", "~/.driftbase/runs.db"))
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
