"""
SQLite storage backend for agent runs (default for local @track() persistence).
"""

from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime
from typing import Any
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
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    raw_prompt: str = ""
    raw_output: str = ""
    # New behavioral metrics
    loop_count: int = 0
    tool_call_sequence: str = "[]"
    time_to_first_tool_ms: int = 0
    verbosity_ratio: float = 0.0
    sensitivity: str | None = None


class CalibrationCache(SQLModel, table=True):
    """Cache for baseline calibration results."""

    __tablename__ = "calibration_cache"

    id: int | None = Field(default=None, primary_key=True)
    cache_key: str = Field(index=True, unique=True)
    calibrated_weights: str = "{}"
    thresholds: str = "{}"
    composite_thresholds: str = "{}"
    calibration_method: str = "default"
    baseline_n: int = 0
    run_count_at_calibration: int = 0
    reliability_multipliers: str = "{}"
    confidence: float = 0.0
    computed_at: datetime = Field(default_factory=datetime.utcnow)


class DeployEvent(SQLModel, table=True):
    """Deploy events (schema stabilized for future use)."""

    __tablename__ = "deploy_events"

    id: int | None = Field(default=None, primary_key=True)
    agent_id: str = ""
    version: str = ""
    environment: str = ""
    deployed_at: datetime = Field(default_factory=datetime.utcnow)
    triggered_by: str = ""


class BudgetBreach(SQLModel, table=True):
    """Budget breach records."""

    __tablename__ = "budget_breaches"

    id: int | None = Field(default=None, primary_key=True)
    agent_id: str = Field(index=True)
    version: str = Field(index=True)
    dimension: str
    budget_key: str
    limit_value: float
    actual_value: float
    direction: str
    run_count: int
    breached_at: datetime = Field(default_factory=datetime.utcnow)


class BudgetConfig(SQLModel, table=True):
    """Budget configuration per agent + version."""

    __tablename__ = "budget_configs"

    id: int | None = Field(default=None, primary_key=True)
    agent_id: str = Field(index=True)
    version: str = Field(index=True)
    config: str = "{}"  # JSON serialized budget limits
    source: str = "decorator"  # "decorator" | "config_file"
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ChangeEvent(SQLModel, table=True):
    """Change events for root cause analysis."""

    __tablename__ = "change_events"

    id: int | None = Field(default=None, primary_key=True)
    agent_id: str = Field(index=True)
    version: str = Field(index=True)
    change_type: str  # model_version|prompt_hash|rag_snapshot|tool_version|custom
    previous: str | None = None  # value before change (may not be known)
    current: str  # value after change
    recorded_at: datetime = Field(default_factory=datetime.utcnow)
    source: str  # "decorator" | "cli" | "auto"


def _ensure_dir(path: str) -> None:
    """
    Ensure the parent directory of the database file exists.
    Wraps mkdir in try/except to handle permission errors gracefully.
    """
    d = os.path.dirname(path)
    if d:
        try:
            os.makedirs(d, exist_ok=True)
        except Exception as e:
            logger.error("Failed to create database directory '%s': %s", d, str(e))
            raise RuntimeError(
                f"Could not create database directory at '{d}'. "
                f"Error: {e}. "
                "Please set DRIFTBASE_DB_PATH to a writable location."
            ) from e


def _migrate_schema(engine: Any) -> None:
    """Add new columns if missing (existing DBs)."""
    try:
        with engine.connect() as conn:
            r = conn.execute(text("PRAGMA table_info(agent_runs_local)"))
            columns = {row[1] for row in r.fetchall()}

            if "prompt_tokens" not in columns:
                conn.execute(
                    text(
                        "ALTER TABLE agent_runs_local ADD COLUMN prompt_tokens INTEGER"
                    )
                )
                conn.commit()
            if "completion_tokens" not in columns:
                conn.execute(
                    text(
                        "ALTER TABLE agent_runs_local ADD COLUMN completion_tokens INTEGER"
                    )
                )
                conn.commit()
            if "raw_prompt" not in columns:
                conn.execute(
                    text("ALTER TABLE agent_runs_local ADD COLUMN raw_prompt TEXT")
                )
                conn.commit()
            if "raw_output" not in columns:
                conn.execute(
                    text("ALTER TABLE agent_runs_local ADD COLUMN raw_output TEXT")
                )
                conn.commit()
            # New behavioral metrics migrations
            if "loop_count" not in columns:
                conn.execute(
                    text(
                        "ALTER TABLE agent_runs_local ADD COLUMN loop_count INTEGER DEFAULT 0"
                    )
                )
                conn.commit()
            if "tool_call_sequence" not in columns:
                conn.execute(
                    text(
                        "ALTER TABLE agent_runs_local ADD COLUMN tool_call_sequence TEXT DEFAULT '[]'"
                    )
                )
                conn.commit()
            if "time_to_first_tool_ms" not in columns:
                conn.execute(
                    text(
                        "ALTER TABLE agent_runs_local ADD COLUMN time_to_first_tool_ms INTEGER DEFAULT 0"
                    )
                )
                conn.commit()
            if "verbosity_ratio" not in columns:
                conn.execute(
                    text(
                        "ALTER TABLE agent_runs_local ADD COLUMN verbosity_ratio REAL DEFAULT 0.0"
                    )
                )
                conn.commit()
            if "sensitivity" not in columns:
                conn.execute(
                    text("ALTER TABLE agent_runs_local ADD COLUMN sensitivity TEXT")
                )
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
        "started_at": r.started_at.isoformat()
        if isinstance(r.started_at, datetime)
        else r.started_at,
        "completed_at": r.completed_at.isoformat()
        if isinstance(r.completed_at, datetime)
        else r.completed_at,
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
        # New behavioral metrics
        "loop_count": r.loop_count,
        "tool_call_sequence": r.tool_call_sequence,
        "time_to_first_tool_ms": r.time_to_first_tool_ms,
        "verbosity_ratio": r.verbosity_ratio,
        "sensitivity": r.sensitivity,
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
        CalibrationCache.__table__.create(self._engine, checkfirst=True)
        DeployEvent.__table__.create(self._engine, checkfirst=True)
        BudgetBreach.__table__.create(self._engine, checkfirst=True)
        BudgetConfig.__table__.create(self._engine, checkfirst=True)
        ChangeEvent.__table__.create(self._engine, checkfirst=True)
        _migrate_schema(self._engine)

        # Add UNIQUE constraint for change_events if not exists
        try:
            with self._engine.connect() as conn:
                conn.execute(
                    text(
                        "CREATE UNIQUE INDEX IF NOT EXISTS idx_change_events_unique "
                        "ON change_events(agent_id, version, change_type)"
                    )
                )
                conn.commit()
        except Exception:
            pass

    def prune_if_needed(self) -> None:
        """
        Enforces the rolling retention window to prevent disk bloat.

        This method should be called from the background worker thread in local_store.py,
        not during individual write operations. It checks the count first and only
        deletes if the retention limit is exceeded.
        """
        limit = get_settings().DRIFTBASE_LOCAL_RETENTION_LIMIT
        try:
            with Session(self._engine) as session:
                # Check count first before issuing expensive DELETE
                result = session.execute(text("SELECT COUNT(*) FROM agent_runs_local"))
                count = result.scalar()

                if count is None or count <= limit:
                    # No pruning needed
                    return

                # Count exceeds limit, perform pruning
                result = session.execute(
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
                    {"limit": limit},
                )
                deleted_count = result.rowcount
                session.commit()

                if deleted_count > 0:
                    logger.debug(
                        "Driftbase pruned %d old records (retention limit: %d, current count: %d)",
                        deleted_count,
                        limit,
                        count,
                    )
        except Exception as e:
            logger.debug("SQLite database pruning failed: %s", e)

    def write_run(self, payload: dict[str, Any]) -> None:
        try:
            with Session(self._engine) as session:
                run = AgentRunLocal(**payload)
                session.add(run)
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
            stmt = (
                select(AgentRunLocal)
                .order_by(AgentRunLocal.started_at.desc())
                .limit(limit)
            )
            if deployment_version is not None:
                stmt = stmt.where(
                    AgentRunLocal.deployment_version == deployment_version
                )
            if environment is not None:
                stmt = stmt.where(AgentRunLocal.environment == environment)
            result = session.execute(stmt)
            rows = result.scalars().all()
            return [_row_to_run_dict(r) for r in rows]

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
                select(AgentRunLocal).order_by(AgentRunLocal.started_at.desc()).limit(1)
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
            return [_row_to_run_dict(r) for r in rows]

    def get_runs_filtered(
        self,
        deployment_version: str | None = None,
        environment: str | None = None,
        outcomes: list[str] | None = None,
        min_latency_ms: int | None = None,
        max_latency_ms: int | None = None,
        since_hours: int | None = None,
        since_datetime: datetime | None = None,
        between: tuple[datetime, datetime] | None = None,
        offset: int = 0,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        """
        Get runs with enhanced filtering capabilities.

        Args:
            deployment_version: Filter by deployment version
            environment: Filter by environment
            outcomes: Filter by semantic_cluster values (e.g., ['resolved', 'escalated'])
            min_latency_ms: Minimum latency in milliseconds
            max_latency_ms: Maximum latency in milliseconds
            since_hours: Get runs from the last N hours
            since_datetime: Get runs since specific datetime
            between: Get runs between two datetimes (start, end)
            offset: Skip first N runs (for pagination)
            limit: Maximum runs to return

        Returns:
            List of run dicts matching all filters
        """
        with Session(self._engine) as session:
            stmt = select(AgentRunLocal).order_by(AgentRunLocal.started_at.desc())

            # Version filter
            if deployment_version is not None:
                stmt = stmt.where(
                    AgentRunLocal.deployment_version == deployment_version
                )

            # Environment filter
            if environment is not None:
                stmt = stmt.where(AgentRunLocal.environment == environment)

            # Outcome filters (semantic_cluster)
            if outcomes is not None and len(outcomes) > 0:
                stmt = stmt.where(AgentRunLocal.semantic_cluster.in_(outcomes))

            # Latency filters
            if min_latency_ms is not None:
                stmt = stmt.where(AgentRunLocal.latency_ms >= min_latency_ms)
            if max_latency_ms is not None:
                stmt = stmt.where(AgentRunLocal.latency_ms <= max_latency_ms)

            # Time filters
            if since_hours is not None:
                from datetime import timedelta

                cutoff = datetime.utcnow() - timedelta(hours=since_hours)
                stmt = stmt.where(AgentRunLocal.started_at >= cutoff)
            elif since_datetime is not None:
                stmt = stmt.where(AgentRunLocal.started_at >= since_datetime)
            elif between is not None:
                start_time, end_time = between
                stmt = stmt.where(
                    AgentRunLocal.started_at >= start_time,
                    AgentRunLocal.started_at <= end_time,
                )

            # Pagination
            stmt = stmt.offset(offset).limit(limit)

            result = session.execute(stmt)
            rows = result.scalars().all()
            return [_row_to_run_dict(r) for r in rows]

    def count_runs_filtered(
        self,
        deployment_version: str | None = None,
        environment: str | None = None,
        outcomes: list[str] | None = None,
        min_latency_ms: int | None = None,
        since_hours: int | None = None,
    ) -> int:
        """
        Count runs matching filters (for pagination metadata).

        Args:
            deployment_version: Filter by deployment version
            environment: Filter by environment
            outcomes: Filter by semantic_cluster values
            min_latency_ms: Minimum latency filter
            since_hours: Time window filter

        Returns:
            Count of matching runs
        """
        with Session(self._engine) as session:
            from sqlalchemy import func

            stmt = select(func.count(AgentRunLocal.id))

            if deployment_version is not None:
                stmt = stmt.where(
                    AgentRunLocal.deployment_version == deployment_version
                )
            if environment is not None:
                stmt = stmt.where(AgentRunLocal.environment == environment)
            if outcomes is not None and len(outcomes) > 0:
                stmt = stmt.where(AgentRunLocal.semantic_cluster.in_(outcomes))
            if min_latency_ms is not None:
                stmt = stmt.where(AgentRunLocal.latency_ms >= min_latency_ms)
            if since_hours is not None:
                from datetime import timedelta

                cutoff = datetime.utcnow() - timedelta(hours=since_hours)
                stmt = stmt.where(AgentRunLocal.started_at >= cutoff)

            result = session.execute(stmt)
            count = result.scalar()
            return count or 0

    def delete_runs_filtered(
        self,
        deployment_version: str | None = None,
        environment: str | None = None,
        older_than_days: int | None = None,
        keep_last_n: int | None = None,
    ) -> int:
        """
        Delete runs based on filter criteria.

        Args:
            deployment_version: Delete only this version
            environment: Delete only this environment
            older_than_days: Delete runs older than N days
            keep_last_n: Keep only the N most recent runs (deletes older ones)

        Returns:
            Number of rows deleted
        """
        with Session(self._engine) as session:
            if keep_last_n is not None:
                # Build subquery to get IDs of runs to keep
                keep_stmt = (
                    select(AgentRunLocal.id)
                    .order_by(AgentRunLocal.started_at.desc())
                    .limit(keep_last_n)
                )

                if deployment_version is not None:
                    keep_stmt = keep_stmt.where(
                        AgentRunLocal.deployment_version == deployment_version
                    )
                if environment is not None:
                    keep_stmt = keep_stmt.where(
                        AgentRunLocal.environment == environment
                    )

                # Get IDs to keep
                keep_result = session.execute(keep_stmt)
                keep_ids = [row[0] for row in keep_result.fetchall()]

                # Delete everything except those IDs
                if keep_ids:
                    delete_stmt = text(
                        f"DELETE FROM agent_runs_local WHERE id NOT IN ({','.join(['?'] * len(keep_ids))})"
                    )
                    result = session.execute(delete_stmt, keep_ids)
                else:
                    # If no IDs to keep, delete all matching filters
                    delete_stmt = text("DELETE FROM agent_runs_local WHERE 1=1")
                    result = session.execute(delete_stmt)

                session.commit()
                return result.rowcount

            # older_than_days filter
            delete_conditions = []
            params: dict[str, Any] = {}

            if older_than_days is not None:
                from datetime import timedelta

                cutoff = datetime.utcnow() - timedelta(days=older_than_days)
                delete_conditions.append("started_at < :cutoff")
                params["cutoff"] = cutoff

            if deployment_version is not None:
                delete_conditions.append("deployment_version = :version")
                params["version"] = deployment_version

            if environment is not None:
                delete_conditions.append("environment = :env")
                params["env"] = environment

            if delete_conditions:
                where_clause = " AND ".join(delete_conditions)
                delete_stmt = text(f"DELETE FROM agent_runs_local WHERE {where_clause}")
                result = session.execute(delete_stmt, params)
                session.commit()
                return result.rowcount

            return 0

    def get_db_stats(self) -> dict[str, Any]:
        """
        Get database health statistics.

        Returns:
            Dict with:
            - total_runs: Total number of runs
            - versions: List of versions with counts
            - disk_size_mb: Database file size in MB
            - oldest_run: Datetime of oldest run
            - newest_run: Datetime of newest run
        """
        with Session(self._engine) as session:
            # Total runs
            from sqlalchemy import func

            total_stmt = select(func.count(AgentRunLocal.id))
            total_result = session.execute(total_stmt)
            total_runs = total_result.scalar() or 0

            # Versions
            versions_stmt = text(
                "SELECT deployment_version, COUNT(*) FROM agent_runs_local "
                "GROUP BY deployment_version ORDER BY COUNT(*) DESC"
            )
            versions_result = session.execute(versions_stmt)
            versions = [
                {"version": row[0] or "unknown", "count": row[1]}
                for row in versions_result.fetchall()
            ]

            # Oldest and newest runs
            oldest_stmt = (
                select(AgentRunLocal.started_at)
                .order_by(AgentRunLocal.started_at.asc())
                .limit(1)
            )
            oldest_result = session.execute(oldest_stmt)
            oldest_row = oldest_result.scalar()
            oldest_run = oldest_row if oldest_row else None

            newest_stmt = (
                select(AgentRunLocal.started_at)
                .order_by(AgentRunLocal.started_at.desc())
                .limit(1)
            )
            newest_result = session.execute(newest_stmt)
            newest_row = newest_result.scalar()
            newest_run = newest_row if newest_row else None

            # Disk size (SQLite file)
            disk_size_mb = 0.0
            try:
                db_path = get_settings().DRIFTBASE_DB_PATH
                if os.path.exists(db_path):
                    size_bytes = os.path.getsize(db_path)
                    disk_size_mb = size_bytes / (1024 * 1024)
            except Exception as e:
                logger.debug(f"Failed to get database file size: {e}")

            return {
                "total_runs": total_runs,
                "versions": versions,
                "disk_size_mb": round(disk_size_mb, 2),
                "oldest_run": oldest_run,
                "newest_run": newest_run,
            }

    def get_calibration_cache(self, cache_key: str) -> dict[str, Any] | None:
        """Retrieve calibration from cache by key."""
        try:
            import json

            with Session(self._engine) as session:
                stmt = select(CalibrationCache).where(
                    CalibrationCache.cache_key == cache_key
                )
                result = session.execute(stmt)
                row = result.scalars().first()

                if row is None:
                    return None

                return {
                    "calibrated_weights": json.loads(row.calibrated_weights),
                    "thresholds": json.loads(row.thresholds),
                    "composite_thresholds": json.loads(row.composite_thresholds),
                    "calibration_method": row.calibration_method,
                    "baseline_n": row.baseline_n,
                    "run_count_at_calibration": row.run_count_at_calibration,
                    "reliability_multipliers": json.loads(row.reliability_multipliers),
                    "confidence": row.confidence,
                }
        except Exception as e:
            logger.debug(f"Failed to read calibration cache: {e}")
            return None

    def set_calibration_cache(self, cache_key: str, data: dict[str, Any]) -> None:
        """Store calibration in cache (upsert by cache_key)."""
        try:
            import json

            with Session(self._engine) as session:
                stmt = select(CalibrationCache).where(
                    CalibrationCache.cache_key == cache_key
                )
                result = session.execute(stmt)
                existing = result.scalars().first()

                if existing:
                    existing.calibrated_weights = json.dumps(data["calibrated_weights"])
                    existing.thresholds = json.dumps(data["thresholds"])
                    existing.composite_thresholds = json.dumps(
                        data["composite_thresholds"]
                    )
                    existing.calibration_method = data["calibration_method"]
                    existing.baseline_n = data["baseline_n"]
                    existing.run_count_at_calibration = data["run_count_at_calibration"]
                    existing.reliability_multipliers = json.dumps(
                        data.get("reliability_multipliers", {})
                    )
                    existing.confidence = data.get("confidence", 0.0)
                    existing.computed_at = datetime.utcnow()
                else:
                    cache = CalibrationCache(
                        cache_key=cache_key,
                        calibrated_weights=json.dumps(data["calibrated_weights"]),
                        thresholds=json.dumps(data["thresholds"]),
                        composite_thresholds=json.dumps(data["composite_thresholds"]),
                        calibration_method=data["calibration_method"],
                        baseline_n=data["baseline_n"],
                        run_count_at_calibration=data["run_count_at_calibration"],
                        reliability_multipliers=json.dumps(
                            data.get("reliability_multipliers", {})
                        ),
                        confidence=data.get("confidence", 0.0),
                    )
                    session.add(cache)

                session.commit()
        except Exception as e:
            logger.debug(f"Failed to write calibration cache: {e}")

    def write_budget_breach(self, breach: dict[str, Any]) -> None:
        """Write a budget breach record."""
        try:
            with Session(self._engine) as session:
                breach_record = BudgetBreach(
                    agent_id=breach["agent_id"],
                    version=breach["version"],
                    dimension=breach["dimension"],
                    budget_key=breach["budget_key"],
                    limit_value=breach["limit"],
                    actual_value=breach["actual"],
                    direction=breach["direction"],
                    run_count=breach["run_count"],
                    breached_at=breach.get("breached_at", datetime.utcnow()),
                )
                session.add(breach_record)
                session.commit()
        except Exception as e:
            logger.debug(f"SQLite write_budget_breach failed: {e}")

    def get_budget_breaches(
        self, agent_id: str | None = None, version: str | None = None
    ) -> list[dict[str, Any]]:
        """Return budget breaches, optionally filtered by agent_id and version."""
        with Session(self._engine) as session:
            stmt = select(BudgetBreach).order_by(BudgetBreach.breached_at.desc())

            if agent_id is not None:
                stmt = stmt.where(BudgetBreach.agent_id == agent_id)
            if version is not None:
                stmt = stmt.where(BudgetBreach.version == version)

            result = session.execute(stmt)
            rows = result.scalars().all()

            return [
                {
                    "id": row.id,
                    "agent_id": row.agent_id,
                    "version": row.version,
                    "dimension": row.dimension,
                    "budget_key": row.budget_key,
                    "limit": row.limit_value,
                    "actual": row.actual_value,
                    "direction": row.direction,
                    "run_count": row.run_count,
                    "breached_at": row.breached_at,
                }
                for row in rows
            ]

    def write_budget_config(
        self, agent_id: str, version: str, config: dict[str, Any], source: str
    ) -> None:
        """Write a budget config (upsert by agent_id + version)."""
        try:
            import json

            with Session(self._engine) as session:
                # Check if config already exists
                stmt = select(BudgetConfig).where(
                    BudgetConfig.agent_id == agent_id, BudgetConfig.version == version
                )
                result = session.execute(stmt)
                existing = result.scalars().first()

                if existing:
                    # Update existing config
                    existing.config = json.dumps(config)
                    existing.source = source
                    existing.created_at = datetime.utcnow()
                else:
                    # Create new config
                    budget_config = BudgetConfig(
                        agent_id=agent_id,
                        version=version,
                        config=json.dumps(config),
                        source=source,
                    )
                    session.add(budget_config)

                session.commit()
        except Exception as e:
            logger.debug(f"SQLite write_budget_config failed: {e}")

    def get_budget_config(self, agent_id: str, version: str) -> dict[str, Any] | None:
        """Return budget config for agent_id + version, or None if not found."""
        try:
            import json

            with Session(self._engine) as session:
                stmt = select(BudgetConfig).where(
                    BudgetConfig.agent_id == agent_id, BudgetConfig.version == version
                )
                result = session.execute(stmt)
                row = result.scalars().first()

                if row is None:
                    return None

                return {
                    "agent_id": row.agent_id,
                    "version": row.version,
                    "config": json.loads(row.config),
                    "source": row.source,
                    "created_at": row.created_at,
                }
        except Exception as e:
            logger.debug(f"SQLite get_budget_config failed: {e}")
            return None

    def delete_budget_breaches(
        self, agent_id: str | None = None, version: str | None = None
    ) -> int:
        """Delete budget breaches, optionally filtered. Returns number deleted."""
        try:
            with Session(self._engine) as session:
                stmt = text("DELETE FROM budget_breaches WHERE 1=1")
                params: dict[str, Any] = {}

                if agent_id is not None or version is not None:
                    conditions = []
                    if agent_id is not None:
                        conditions.append("agent_id = :agent_id")
                        params["agent_id"] = agent_id
                    if version is not None:
                        conditions.append("version = :version")
                        params["version"] = version

                    where_clause = " AND ".join(conditions)
                    stmt = text(f"DELETE FROM budget_breaches WHERE {where_clause}")

                result = session.execute(stmt, params)
                session.commit()
                return result.rowcount
        except Exception as e:
            logger.debug(f"SQLite delete_budget_breaches failed: {e}")
            return 0

    def write_change_event(self, event: dict[str, Any]) -> None:
        """Write a change event. On UNIQUE conflict, log warning and do not overwrite."""
        try:
            with Session(self._engine) as session:
                # Check if event already exists
                stmt = select(ChangeEvent).where(
                    ChangeEvent.agent_id == event["agent_id"],
                    ChangeEvent.version == event["version"],
                    ChangeEvent.change_type == event["change_type"],
                )
                result = session.execute(stmt)
                existing = result.scalars().first()

                if existing:
                    logger.warning(
                        f"Change event already exists for {event['agent_id']}/{event['version']}/{event['change_type']}. "
                        f"Keeping first recorded value: {existing.current}"
                    )
                    return

                change_event = ChangeEvent(
                    agent_id=event["agent_id"],
                    version=event["version"],
                    change_type=event["change_type"],
                    previous=event.get("previous"),
                    current=event["current"],
                    recorded_at=event.get("recorded_at", datetime.utcnow()),
                    source=event["source"],
                )
                session.add(change_event)
                session.commit()
        except Exception as e:
            logger.debug(f"SQLite write_change_event failed: {e}")

    def get_change_events(self, agent_id: str, version: str) -> list[dict[str, Any]]:
        """Return change events for agent_id + version."""
        try:
            with Session(self._engine) as session:
                stmt = (
                    select(ChangeEvent)
                    .where(
                        ChangeEvent.agent_id == agent_id,
                        ChangeEvent.version == version,
                    )
                    .order_by(ChangeEvent.recorded_at.desc())
                )

                result = session.execute(stmt)
                rows = result.scalars().all()

                return [
                    {
                        "id": row.id,
                        "agent_id": row.agent_id,
                        "version": row.version,
                        "change_type": row.change_type,
                        "previous": row.previous,
                        "current": row.current,
                        "recorded_at": row.recorded_at,
                        "source": row.source,
                    }
                    for row in rows
                ]
        except Exception as e:
            logger.debug(f"SQLite get_change_events failed: {e}")
            return []

    def get_change_events_for_versions(
        self, agent_id: str, v1: str, v2: str
    ) -> dict[str, list[dict[str, Any]]]:
        """Return change events for two versions. Returns {"v1": [...], "v2": [...]}."""
        try:
            v1_events = self.get_change_events(agent_id, v1)
            v2_events = self.get_change_events(agent_id, v2)
            return {"v1": v1_events, "v2": v2_events}
        except Exception as e:
            logger.debug(f"SQLite get_change_events_for_versions failed: {e}")
            return {"v1": [], "v2": []}
