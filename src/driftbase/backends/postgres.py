"""
PostgreSQL backend using asyncpg for Driftbase Pro and self-hosted deployments.

Security best practices:
- NEVER hardcode credentials
- ALWAYS use DATABASE_URL environment variable
- Gracefully exit with clear error if DATABASE_URL is missing
- Support both postgresql:// (asyncpg) and postgresql+asyncpg:// (SQLAlchemy) protocols
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Any
from urllib.parse import urlparse, urlunparse

from driftbase.backends.base import StorageBackend
from driftbase.local.local_store import AgentRun, BehavioralFingerprint

logger = logging.getLogger(__name__)


def _normalize_database_url(url: str, target: str = "asyncpg") -> str:
    """
    Normalize DATABASE_URL to handle protocol differences.

    asyncpg expects: postgresql://user:pass@host:port/db
    SQLAlchemy async expects: postgresql+asyncpg://user:pass@host:port/db

    Args:
        url: Raw DATABASE_URL from environment
        target: "asyncpg" or "sqlalchemy"

    Returns:
        Normalized connection string
    """
    parsed = urlparse(url)

    if target == "asyncpg":
        # Convert postgresql+asyncpg:// → postgresql://
        if parsed.scheme == "postgresql+asyncpg":
            return urlunparse(parsed._replace(scheme="postgresql"))
        elif parsed.scheme == "postgresql":
            return url
        else:
            raise ValueError(
                f"Invalid DATABASE_URL scheme: {parsed.scheme}. "
                f"Expected postgresql:// or postgresql+asyncpg://"
            )

    elif target == "sqlalchemy":
        # Convert postgresql:// → postgresql+asyncpg://
        if parsed.scheme == "postgresql":
            return urlunparse(parsed._replace(scheme="postgresql+asyncpg"))
        elif parsed.scheme == "postgresql+asyncpg":
            return url
        else:
            raise ValueError(
                f"Invalid DATABASE_URL scheme: {parsed.scheme}. "
                f"Expected postgresql:// or postgresql+asyncpg://"
            )

    else:
        raise ValueError(f"Unknown target: {target}")


def _get_database_url(required: bool = True) -> str | None:
    """
    Retrieve DATABASE_URL from environment with strict validation.

    Args:
        required: If True, exit with error if DATABASE_URL is missing

    Returns:
        DATABASE_URL string or None if not required and missing

    Exits:
        SystemExit(1) if required=True and DATABASE_URL is not set
    """
    url = os.getenv("DATABASE_URL")

    if url is None:
        if required:
            logger.error(
                "DATABASE_URL environment variable is not set. "
                "PostgreSQL backend requires explicit database credentials."
            )
            print(
                "\n❌ FATAL ERROR: DATABASE_URL environment variable is missing\n\n"
                "PostgreSQL backend requires DATABASE_URL to be set. Example:\n\n"
                "  export DATABASE_URL='postgresql://user:password@host:5432/database'\n\n"
                "For SQLAlchemy async support, use:\n\n"
                "  export DATABASE_URL='postgresql+asyncpg://user:password@host:5432/database'\n\n"
                "SECURITY: Never hardcode credentials in source code.\n"
                "See .env.example for configuration template.\n",
                file=sys.stderr
            )
            sys.exit(1)
        return None

    if not url.strip():
        if required:
            logger.error("DATABASE_URL is set but empty")
            print(
                "\n❌ FATAL ERROR: DATABASE_URL is empty\n\n"
                "Please provide a valid PostgreSQL connection string.\n",
                file=sys.stderr
            )
            sys.exit(1)
        return None

    return url.strip()


class PostgreSQLBackend(StorageBackend):
    """
    PostgreSQL storage backend for production deployments.

    Requires DATABASE_URL environment variable.
    Supports both asyncpg and SQLAlchemy async engines.
    """

    def __init__(self, use_sqlalchemy: bool = False):
        """
        Initialize PostgreSQL backend.

        Args:
            use_sqlalchemy: If True, use SQLAlchemy with asyncpg driver.
                           If False, use native asyncpg (default).

        Raises:
            SystemExit: If DATABASE_URL is not set
        """
        raw_url = _get_database_url(required=True)

        if use_sqlalchemy:
            # SQLAlchemy async requires postgresql+asyncpg://
            self.connection_url = _normalize_database_url(raw_url, target="sqlalchemy")
            self._init_sqlalchemy()
        else:
            # Native asyncpg requires postgresql://
            self.connection_url = _normalize_database_url(raw_url, target="asyncpg")
            self._init_asyncpg()

        logger.info(
            "PostgreSQL backend initialized (engine=%s, host=%s)",
            "sqlalchemy" if use_sqlalchemy else "asyncpg",
            urlparse(self.connection_url).hostname
        )

    def _init_asyncpg(self):
        """Initialize native asyncpg connection pool."""
        try:
            import asyncpg
        except ImportError as e:
            logger.error(
                "asyncpg is not installed. Install with: pip install 'driftbase[postgres]'"
            )
            raise ImportError(
                "PostgreSQL backend requires asyncpg. "
                "Install with: pip install 'driftbase[postgres]'"
            ) from e

        # Connection pool will be created lazily on first query
        self._pool = None
        self._asyncpg_url = self.connection_url

    def _init_sqlalchemy(self):
        """Initialize SQLAlchemy async engine with asyncpg driver."""
        try:
            from sqlalchemy.ext.asyncio import create_async_engine
        except ImportError as e:
            logger.error(
                "SQLAlchemy asyncio is not installed. "
                "Install with: pip install 'driftbase[postgres]'"
            )
            raise ImportError(
                "PostgreSQL backend with SQLAlchemy requires sqlalchemy[asyncio]. "
                "Install with: pip install 'driftbase[postgres]'"
            ) from e

        self._engine = create_async_engine(
            self.connection_url,
            echo=False,
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=10,
        )

    def write_run(self, run: AgentRun) -> None:
        """Write a single run to PostgreSQL."""
        # Implementation would use asyncpg or SQLAlchemy async
        raise NotImplementedError(
            "PostgreSQL backend is not yet implemented. "
            "This is a security-first template for future Pro tier integration."
        )

    def get_runs(
        self,
        deployment_version: str | None = None,
        environment: str | None = None,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        """Retrieve runs from PostgreSQL."""
        raise NotImplementedError(
            "PostgreSQL backend is not yet implemented. "
            "This is a security-first template for future Pro tier integration."
        )

    def get_versions(self) -> list[tuple[str, int]]:
        """Get deployment versions from PostgreSQL."""
        raise NotImplementedError(
            "PostgreSQL backend is not yet implemented. "
            "This is a security-first template for future Pro tier integration."
        )
