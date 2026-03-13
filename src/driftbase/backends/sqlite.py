"""
SQLite storage backend for agent runs (default for local @track() persistence).
"""

from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime
from typing import Any, Optional
from uuid import uuid4

from sqlalchemy import create_engine, text
from sqlmodel import Field, Session, SQLModel, select

from driftbase.backends.base import StorageBackend
from driftbase.config import get_settings

logger = logging.getLogger(__name__)


class AgentRunLocal(SQLModel, table=True):
    """Local copy of AgentRun schema for SQLite (same columns as store.AgentRun)."""

    __tablename__ = "agent_runs_local"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    session_id: str = ""
    deployment_version: str = "unknown"
    environment: str = "production"
    started_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: datetime = Field(default_factory=datetime.utcnow)
    task_input_hash: str = ""
    tool_sequence: str = "[]"
    tool_call_count: int = 0
    output_length: int = 0
    output_structure_hash: str = ""
    latency_ms: int = 0
    error_count: int = 0
    retry_count: int = 0
    semantic_cluster: str = "cluster_none"
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    raw_prompt: str = ""
    raw_output: str = ""


def _ensure_dir(path: str) -> None:
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)


def _migrate_schema(engine: Any) -> None:
    """Add new columns if missing (existing DBs)."""
    try:
        with engine.connect() as conn:
            r = conn.execute(text("PRAGMA table_info(agent_runs_local)"))
            columns = {row[1] for row in r.fetchall()}
            
            if "prompt_tokens" not in columns:
                conn.execute(text("ALTER TABLE agent_runs_local ADD COLUMN prompt_tokens INTEGER"))
                conn.commit()
            if "completion_tokens" not in columns:
                conn.execute(text("ALTER TABLE agent_runs_local ADD COLUMN completion_tokens INTEGER"))
                conn.commit()
            if "raw_prompt" not in columns:
                conn.execute(text("ALTER TABLE agent_runs_local ADD COLUMN raw_prompt TEXT"))
                conn.commit()
            if "raw_output" not in columns:
                conn.execute(text("ALTER TABLE agent_runs_local ADD COLUMN raw_output TEXT"))
                conn.commit()
    except Exception as e:
        logger.debug("Schema migration skip: %s", e)


def _row_to_run_dict(r: AgentRunLocal) -> dict[str, Any]:
    """Convert AgentRunLocal row to run dict."""
    return {
        "id": str(r.id) if r.id else str(uuid.uuid4()),
        "session_id": r.session_id,
        "deployment_version": r.deployment_version,
        "environment": r.environment,
        "started_at": r.started_at.isoformat() if isinstance(r.started_at, datetime) else r.started_at,
        "completed_at": r.completed_at.isoformat() if isinstance(r.completed_at, datetime) else r.completed_at,
        "task_input_hash": r.task_input_hash,
        "tool_sequence": r.tool_sequence,
        "tool_call_count": r.tool_call_count,
        "output_length": r.output_length,
        "output_structure_hash": r.output_structure_hash,
        "latency_ms": r.latency_ms,
        "error_count": r.error_count,
        "retry_count": r.retry_count,
        "semantic_cluster": r.semantic_cluster,
        "prompt_tokens": r.prompt_tokens,
        "completion_tokens": r.completion_tokens,
        "raw_prompt": r.raw_prompt,
        "raw_output": r.raw_output,
    }


class SQLiteBackend(StorageBackend):
    """SQLite backend using a single file (e.g. ~/.driftbase/runs.db)."""

    def __init__(self, db_path: str) -> None:
        self._db_path = os.path.expanduser(db_path)
        _ensure_dir(self._db_path)
        url = "sqlite:///" + self._db_path

        # Configure for concurrent reads/writes (critical for async frameworks)
        # WAL mode allows concurrent readers while one writer is active
        self._engine = create_engine(
            url,
            connect_args={"check_same_thread": False},
            pool_pre_ping=True,
        )

        # Enable WAL mode and optimize synchronous setting
        # These must be set on every connection for SQLite
        from sqlalchemy import event

        @event.listens_for(self._engine, "connect")
        def set_sqlite_pragma(dbapi_conn, connection_record):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.close()

        AgentRunLocal.__table__.create(self._engine, checkfirst=True)
        _migrate_schema(self._engine)

    def _prune(self, session: Session) -> None:
        """Enforces the rolling retention window to prevent disk bloat."""
        limit = get_settings().DRIFTBASE_LOCAL_RETENTION_LIMIT
        try:
            session.execute(
                text(
                    """
                    DELETE FROM agent_runs_local 
                    WHERE id NOT IN (
                        SELECT id FROM agent_runs_local 
                        ORDER BY started_at DESC 
                        LIMIT :limit
                    )
                    """
                ),
                {"limit": limit}
            )
        except Exception as e:
            logger.debug("SQLite database pruning failed: %s", e)

    def write_run(self, payload: dict[str, Any]) -> None:
        try:
            with Session(self._engine) as session:
                run = AgentRunLocal(**payload)
                session.add(run)
                self._prune(session)
                session.commit()
        except Exception as e:
            logger.debug("SQLite write_run failed: %s", e)

    def write_runs(self, batch: list[dict[str, Any]]) -> None:
        """Write multiple runs in a single transaction to reduce fsync overhead."""
        if not batch:
            return
        try:
            with Session(self._engine) as session:
                for payload in batch:
                    run = AgentRunLocal(**payload)
                    session.add(run)
                self._prune(session)
                session.commit()
        except Exception as e:
            logger.debug("SQLite write_runs failed: %s", e)

    def get_runs(
        self,
        deployment_version: str | None = None,
        environment: str | None = None,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        with Session(self._engine) as session:
            stmt = select(AgentRunLocal).order_by(AgentRunLocal.started_at.desc()).limit(limit)
            if deployment_version is not None:
                stmt = stmt.where(AgentRunLocal.deployment_version == deployment_version)
            if environment is not None:
                stmt = stmt.where(AgentRunLocal.environment == environment)
            result = session.execute(stmt)
            rows = result.scalars().all()
            return [
                _row_to_run_dict(r)
                for r in rows
            ]

    def get_versions(self) -> list[tuple[str, int]]:
        with Session(self._engine) as session:
            result = session.execute(
                text(
                    "SELECT deployment_version, COUNT(*) FROM agent_runs_local "
                    "GROUP BY deployment_version ORDER BY deployment_version"
                )
            )
            return [(row[0] or "unknown", row[1]) for row in result.fetchall()]

    def delete_runs(self, deployment_version: str) -> int:
        """Delete all runs for the given deployment_version. Returns number of rows deleted."""
        with Session(self._engine) as session:
            result = session.execute(
                text("DELETE FROM agent_runs_local WHERE deployment_version = :v"),
                {"v": deployment_version},
            )
            session.commit()
            return result.rowcount

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        if not run_id:
            return None
        with Session(self._engine) as session:
            row = session.get(AgentRunLocal, run_id)
            if row is None:
                return None
            return _row_to_run_dict(row)

    def get_last_run(self) -> dict[str, Any] | None:
        with Session(self._engine) as session:
            stmt = (
                select(AgentRunLocal)
                .order_by(AgentRunLocal.started_at.desc())
                .limit(1)
            )
            result = session.execute(stmt)
            row = result.scalars().first()
            if row is None:
                return None
            return _row_to_run_dict(row)

    def get_all_runs(self) -> list[dict[str, Any]]:
        """Fetch all runs from the local database for platform ingestion."""
        with Session(self._engine) as session:
            stmt = select(AgentRunLocal).order_by(AgentRunLocal.started_at.asc())
            result = session.execute(stmt)
            rows = result.scalars().all()
            return [
                _row_to_run_dict(r)
                for r in rows
            ]
