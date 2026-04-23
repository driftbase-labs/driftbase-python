"""
SQLite storage backend for agent runs (default for local @track() persistence).
"""

from __future__ import annotations

import hashlib
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

# Schema version constants
RAW_SCHEMA_VERSION = 1
FEATURE_SCHEMA_VERSION = 1


class RunRaw(SQLModel, table=True):
    """Immutable facts from trace source (re-ingestion reproduces them)."""

    __tablename__ = "runs_raw"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    external_id: str | None = None  # Original ID from Langfuse/LangSmith
    source: str | None = None  # "langfuse" | "langsmith" | null for @track()
    ingestion_source: str = (
        "decorator"  # "connector" | "decorator" | "otlp" | "webhook"
    )
    session_id: str = ""
    deployment_version: str = "unknown"
    version_source: str = "epoch"  # "release" | "tag" | "env" | "epoch" | "unknown"
    environment: str = "production"
    timestamp: datetime = Field(default_factory=datetime.utcnow)  # Primary timestamp
    input: str = ""  # Truncated inline (Phase 4 will externalize)
    output: str = ""  # Truncated inline
    latency_ms: int = 0
    tokens_prompt: int | None = None
    tokens_completion: int | None = None
    tokens_total: int | None = None
    raw_status: str | None = None  # "success" | "error" | null
    raw_error_message: str | None = None  # Verbatim from trace
    observation_tree_json: str | None = None  # Phase 4 will populate
    ingested_at: datetime = Field(default_factory=datetime.utcnow)
    raw_schema_version: int = RAW_SCHEMA_VERSION


class RunFeatures(SQLModel, table=True):
    """Driftbase-computed features (re-derivable from RunRaw)."""

    __tablename__ = "runs_features"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    run_id: str = Field(foreign_key="runs_raw.id", index=True, unique=True)
    feature_schema_version: int = FEATURE_SCHEMA_VERSION
    feature_source: str = "derived"  # "derived" | "migrated"
    derivation_error: str | None = None  # Reason if feature_schema_version == -1
    tool_sequence: str = "[]"  # JSON list of tool names
    tool_call_sequence: str = "[]"  # JSON list of tool calls with args
    tool_call_count: int = 0
    semantic_cluster: str = "cluster_none"
    loop_count: int = 0
    verbosity_ratio: float = 0.0
    time_to_first_tool_ms: int = 0
    fallback_rate: float = 0.0
    retry_count: int = 0
    retry_patterns: str = "{}"  # JSON dict
    error_classification: str = "ok"  # "trace_error" | "inferred_error" | "ok"
    input_hash: str = ""
    output_hash: str = ""
    input_length: int = 0
    output_length: int = 0
    run_quality: float = 0.0  # Quality score (0.0-1.0) from run_quality.py
    computed_at: datetime = Field(default_factory=datetime.utcnow)


class RunBlob(SQLModel, table=True):
    """Blob storage for full input/output text (Phase 4)."""

    __tablename__ = "runs_blobs"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    run_id: str = Field(foreign_key="runs_raw.id", index=True)
    field_name: str = ""  # "input" | "output"
    content: str = ""  # Full text, not truncated
    content_length: int = 0
    content_hash: str = ""  # SHA-256 of content
    truncated: bool = False  # True if content exceeded size cap
    created_at: datetime = Field(default_factory=datetime.utcnow)


class AgentRunLocal(SQLModel, table=True):
    """Local copy of AgentRun schema for SQLite (same columns as store.AgentRun)."""

    __tablename__ = "agent_runs_local"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    session_id: str = ""
    deployment_version: str = "unknown"
    version_source: str = (
        "epoch"  # How version was resolved: release | tag | env | epoch | none
    )
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
    # Connector provenance (for imported traces)
    external_id: str | None = None  # original ID from LangSmith/LangFuse
    source: str | None = None  # "langsmith", "langfuse", or None for @track()
    ingestion_source: str = (
        "decorator"  # How run was ingested: connector | decorator | otlp | webhook
    )


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


class DeployOutcome(SQLModel, table=True):
    """Deploy outcome labels for weight learning."""

    __tablename__ = "deploy_outcomes"

    id: int | None = Field(default=None, primary_key=True)
    agent_id: str = Field(index=True)
    version: str = Field(index=True)
    outcome: str  # "good" | "bad"
    labeled_by: str = "user"  # "user" | "auto"
    note: str = ""
    labeled_at: datetime = Field(default_factory=datetime.utcnow)


class LearnedWeightsCache(SQLModel, table=True):
    """Cached learned weights from labeled deploy outcomes."""

    __tablename__ = "learned_weights_cache"

    id: int | None = Field(default=None, primary_key=True)
    agent_id: str = Field(index=True, unique=True)
    weights: str = "{}"  # JSON
    weights_metadata: str = "{}"  # JSON (correlations, factors, etc.)
    n_total: int = 0
    computed_at: datetime = Field(default_factory=datetime.utcnow)


class SignificanceThreshold(SQLModel, table=True):
    """Adaptive significance thresholds derived from power analysis."""

    __tablename__ = "significance_thresholds"

    id: int | None = Field(default=None, primary_key=True)
    agent_id: str = Field(index=True)
    version: str = Field(index=True)
    use_case: str = "GENERAL"
    effect_size: float = 0.10
    min_runs_overall: int = 50
    min_runs_per_dim: str = "{}"  # JSON
    limiting_dim: str = ""
    computed_at: datetime = Field(default_factory=datetime.utcnow)
    baseline_n_at_computation: int = 0


class DetectedEpoch(SQLModel, table=True):
    """Auto-detected behavioral epochs (cached with TTL)."""

    __tablename__ = "detected_epochs"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    agent_id: str = Field(index=True)
    epoch_label: str
    start_run_id: str | None = None
    end_run_id: str | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    run_count: int = 0
    stability: str = "UNKNOWN"  # HIGH | MODERATE | LOW | UNKNOWN
    summary: str = ""
    detected_at: datetime = Field(default_factory=datetime.utcnow)
    cache_expires_at: datetime = Field(default_factory=datetime.utcnow)


class ConnectorSync(SQLModel, table=True):
    """Connector sync metadata for incremental imports."""

    __tablename__ = "connector_syncs"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    source: str = ""  # "langsmith" or "langfuse"
    project_name: str = ""
    agent_id: str = ""
    last_sync_at: datetime = Field(default_factory=datetime.utcnow)
    runs_imported: int = 0
    last_external_id: str | None = None
    status: str = "success"  # success|error


class VerdictRecord(SQLModel, table=True):
    """Stores completed drift verdicts for explain and history."""

    __tablename__ = "verdict_history"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    baseline_version: str = ""
    current_version: str = ""
    environment: str = "production"
    composite_score: float = 0.0
    verdict: str | None = None  # SHIP/MONITOR/REVIEW/BLOCK or None
    severity: str | None = None
    confidence_tier: str = "TIER3"
    report_json: str = "{}"  # Full DriftReport serialized as JSON


class DriftFeedback(SQLModel, table=True):
    """Stores user feedback on drift verdicts for weight learning."""

    __tablename__ = "feedback"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    verdict_id: str = Field(foreign_key="verdict_history.id", index=True)
    action: str = ""  # "dismiss" | "acknowledge" | "investigate"
    reason: str | None = None
    dismissed_dimensions: str | None = None  # JSON list of dimension names
    created_at: datetime = Field(default_factory=datetime.utcnow)
    agent_id: str | None = None


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
            # Connector provenance fields
            if "external_id" not in columns:
                conn.execute(
                    text("ALTER TABLE agent_runs_local ADD COLUMN external_id TEXT")
                )
                conn.commit()
            if "source" not in columns:
                conn.execute(
                    text("ALTER TABLE agent_runs_local ADD COLUMN source TEXT")
                )
                conn.commit()
            # Version resolution source
            if "version_source" not in columns:
                conn.execute(
                    text(
                        "ALTER TABLE agent_runs_local ADD COLUMN version_source TEXT DEFAULT 'unknown'"
                    )
                )
                conn.commit()
            # Ingestion source tracking
            if "ingestion_source" not in columns:
                conn.execute(
                    text(
                        "ALTER TABLE agent_runs_local ADD COLUMN ingestion_source TEXT DEFAULT 'decorator'"
                    )
                )
                conn.commit()

            # Migrate learned_weights_cache table (rename metadata to weights_metadata)
            r = conn.execute(text("PRAGMA table_info(learned_weights_cache)"))
            lwc_columns = {row[1] for row in r.fetchall()}
            if (
                lwc_columns
                and "metadata" in lwc_columns
                and "weights_metadata" not in lwc_columns
            ):
                # Rename metadata column to weights_metadata
                conn.execute(
                    text(
                        "ALTER TABLE learned_weights_cache RENAME COLUMN metadata TO weights_metadata"
                    )
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
        "version_source": getattr(r, "version_source", "epoch"),
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
        "external_id": r.external_id,
        "source": r.source,
        "ingestion_source": getattr(r, "ingestion_source", "decorator"),
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
        DeployOutcome.__table__.create(self._engine, checkfirst=True)
        LearnedWeightsCache.__table__.create(self._engine, checkfirst=True)
        SignificanceThreshold.__table__.create(self._engine, checkfirst=True)
        DetectedEpoch.__table__.create(self._engine, checkfirst=True)
        ConnectorSync.__table__.create(self._engine, checkfirst=True)
        VerdictRecord.__table__.create(self._engine, checkfirst=True)
        DriftFeedback.__table__.create(self._engine, checkfirst=True)
        _migrate_schema(self._engine)

        # Run v0.11 schema split migration (runs_raw + runs_features)
        from pathlib import Path

        from driftbase.backends.migrations.v0_11_schema_split import (
            MigrationError,
            migrate,
        )

        try:
            result = migrate(self._engine, Path(self._db_path), dry_run=False)
            if result.migrated:
                logger.info(
                    f"Migrated {result.rows_copied} rows to runs_raw. "
                    f"Backup at {result.backup_path}"
                )
        except MigrationError as e:
            logger.error(f"Schema migration failed: {e}")
            raise RuntimeError(
                f"Database schema migration failed: {e}. See logs for details."
            ) from e

        # Create runs_raw and runs_features tables if they don't exist (fresh databases)
        RunRaw.__table__.create(self._engine, checkfirst=True)
        RunFeatures.__table__.create(self._engine, checkfirst=True)
        RunBlob.__table__.create(self._engine, checkfirst=True)

        # Add run_quality column to runs_features if missing (v0.11.1)
        try:
            with self._engine.connect() as conn:
                # Check if runs_features table exists and if run_quality column exists
                result = conn.execute(
                    text(
                        "SELECT name FROM sqlite_master WHERE type='table' AND name='runs_features'"
                    )
                )
                if result.fetchone() is not None:
                    # Table exists, check for run_quality column
                    result = conn.execute(text("PRAGMA table_info(runs_features)"))
                    columns = {row[1] for row in result.fetchall()}
                    if "run_quality" not in columns:
                        conn.execute(
                            text(
                                "ALTER TABLE runs_features ADD COLUMN run_quality REAL NOT NULL DEFAULT 0.0"
                            )
                        )
                        conn.commit()
                        logger.info("✓ Added run_quality column to runs_features table")
        except Exception as e:
            logger.debug(f"run_quality column migration skip: {e}")

        # Add UNIQUE constraints if not exists
        try:
            with self._engine.connect() as conn:
                conn.execute(
                    text(
                        "CREATE UNIQUE INDEX IF NOT EXISTS idx_change_events_unique "
                        "ON change_events(agent_id, version, change_type)"
                    )
                )
                conn.execute(
                    text(
                        "CREATE UNIQUE INDEX IF NOT EXISTS idx_deploy_outcomes_unique "
                        "ON deploy_outcomes(agent_id, version)"
                    )
                )
                conn.execute(
                    text(
                        "CREATE UNIQUE INDEX IF NOT EXISTS idx_significance_thresholds_unique "
                        "ON significance_thresholds(agent_id, version)"
                    )
                )
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS idx_detected_epochs_agent_time "
                        "ON detected_epochs(agent_id, detected_at DESC)"
                    )
                )
                conn.commit()
        except Exception:
            pass

        # Add performance indexes for query patterns
        try:
            with self._engine.connect() as conn:
                # Primary fingerprint query pattern: version + environment + timestamp
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS idx_runs_raw_version_env_ts "
                        "ON runs_raw(deployment_version, environment, timestamp)"
                    )
                )
                # Session-based filtering
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS idx_runs_raw_session_ts "
                        "ON runs_raw(session_id, timestamp)"
                    )
                )
                # Version source filtering (for drift warnings)
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS idx_runs_raw_version_source "
                        "ON runs_raw(version_source)"
                    )
                )
                # FK join performance (may already exist from migration)
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS idx_runs_features_run_id "
                        "ON runs_features(run_id)"
                    )
                )
                # Schema version queries (migration --status, lazy derivation)
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS idx_runs_features_schema_version "
                        "ON runs_features(feature_schema_version)"
                    )
                )
                conn.commit()
                logger.debug("✓ Performance indexes created/verified")
        except Exception as e:
            logger.debug(f"Index creation skip: {e}")

        # Log blob storage mode
        settings = get_settings()
        if settings.DRIFTBASE_BLOB_STORAGE:
            size_mb = settings.DRIFTBASE_BLOB_SIZE_LIMIT / (1024 * 1024)
            logger.info(f"Blob storage enabled (limit: {size_mb:.1f}MB per blob)")
        else:
            logger.info("Blob storage disabled")

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
        """
        Write multiple runs in a single transaction to reduce fsync overhead.

        Phase 4: Also saves full input/output to blob storage if available.
        """
        if not batch:
            return
        try:
            with Session(self._engine) as session:
                for payload in batch:
                    # Extract full versions for blob storage (Phase 4)
                    raw_prompt_full = payload.pop("raw_prompt_full", None)
                    raw_output_full = payload.pop("raw_output_full", None)

                    # Write run to legacy table
                    run = AgentRunLocal(**payload)
                    session.add(run)
                    session.flush()  # Get run.id for blob storage

                    # Save blobs in same session (best-effort, never fail ingestion)
                    if raw_prompt_full:
                        try:
                            self.save_blob(
                                run.id, "input", raw_prompt_full, session=session
                            )
                        except Exception as e:
                            logger.debug(f"Failed to save input blob for {run.id}: {e}")

                    if raw_output_full:
                        try:
                            self.save_blob(
                                run.id, "output", raw_output_full, session=session
                            )
                        except Exception as e:
                            logger.debug(
                                f"Failed to save output blob for {run.id}: {e}"
                            )

                session.commit()
        except Exception as e:
            logger.debug("SQLite write_runs failed: %s", e)

    def get_runs(
        self,
        deployment_version: str | None = None,
        environment: str | None = None,
        limit: int = 1000,
        include_all_sources: bool = False,
    ) -> list[dict[str, Any]]:
        # Use lazy derivation reader for runs_raw + runs_features
        from driftbase.backends.sqlite_reader import get_runs_with_features

        return get_runs_with_features(
            backend=self,
            deployment_version=deployment_version,
            environment=environment,
            limit=limit,
            include_all_sources=include_all_sources,
        )

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

    def write_deploy_outcome(
        self,
        agent_id: str,
        version: str,
        outcome: str,
        note: str = "",
        labeled_by: str = "user",
    ) -> None:
        """Write deploy outcome label. On UNIQUE conflict, overwrite."""
        try:
            with Session(self._engine) as session:
                # Check if already exists
                existing = session.exec(
                    select(DeployOutcome).where(
                        DeployOutcome.agent_id == agent_id,
                        DeployOutcome.version == version,
                    )
                ).first()

                if existing:
                    logger.info(
                        f"Overwriting existing deploy outcome for {agent_id}/{version}: "
                        f"{existing.outcome} -> {outcome}"
                    )
                    existing.outcome = outcome
                    existing.note = note
                    existing.labeled_by = labeled_by
                    existing.labeled_at = datetime.utcnow()
                else:
                    record = DeployOutcome(
                        agent_id=agent_id,
                        version=version,
                        outcome=outcome,
                        note=note,
                        labeled_by=labeled_by,
                    )
                    session.add(record)

                session.commit()
        except Exception as e:
            logger.debug(f"SQLite write_deploy_outcome failed: {e}")

    def get_deploy_outcome(self, agent_id: str, version: str) -> dict[str, Any] | None:
        """Return deploy outcome for agent_id + version, or None if not found."""
        try:
            with Session(self._engine) as session:
                outcome = session.exec(
                    select(DeployOutcome).where(
                        DeployOutcome.agent_id == agent_id,
                        DeployOutcome.version == version,
                    )
                ).first()

                if not outcome:
                    return None

                return {
                    "id": outcome.id,
                    "agent_id": outcome.agent_id,
                    "version": outcome.version,
                    "outcome": outcome.outcome,
                    "labeled_by": outcome.labeled_by,
                    "note": outcome.note,
                    "labeled_at": outcome.labeled_at.isoformat()
                    if isinstance(outcome.labeled_at, datetime)
                    else outcome.labeled_at,
                }
        except Exception as e:
            logger.debug(f"SQLite get_deploy_outcome failed: {e}")
            return None

    def get_deploy_outcomes(self, agent_id: str) -> list[dict[str, Any]]:
        """Return all labeled versions for agent_id, ordered by labeled_at desc."""
        try:
            with Session(self._engine) as session:
                outcomes = session.exec(
                    select(DeployOutcome)
                    .where(DeployOutcome.agent_id == agent_id)
                    .order_by(DeployOutcome.labeled_at.desc())
                ).all()

                return [
                    {
                        "id": o.id,
                        "agent_id": o.agent_id,
                        "version": o.version,
                        "outcome": o.outcome,
                        "labeled_by": o.labeled_by,
                        "note": o.note,
                        "labeled_at": o.labeled_at.isoformat()
                        if isinstance(o.labeled_at, datetime)
                        else o.labeled_at,
                    }
                    for o in outcomes
                ]
        except Exception as e:
            logger.debug(f"SQLite get_deploy_outcomes failed: {e}")
            return []

    def get_labeled_versions_with_drift(self, agent_id: str) -> list[dict[str, Any]]:
        """
        Return versions with both deploy_outcome AND drift report data.
        For weight learning training set.
        """
        try:
            with Session(self._engine) as session:
                # Get all labeled outcomes for this agent
                outcomes = session.exec(
                    select(DeployOutcome).where(DeployOutcome.agent_id == agent_id)
                ).all()

                results = []
                for outcome in outcomes:
                    # Check if this version has runs (need for drift computation)
                    runs = session.exec(
                        select(AgentRunLocal)
                        .where(
                            AgentRunLocal.session_id == agent_id,
                            AgentRunLocal.deployment_version == outcome.version,
                        )
                        .limit(1)
                    ).first()

                    if not runs:
                        continue

                    # For now, we'll return the version and outcome
                    # Drift scores will be computed on-demand in weight_learner
                    results.append(
                        {
                            "version": outcome.version,
                            "outcome": outcome.outcome,
                            "agent_id": outcome.agent_id,
                        }
                    )

                return results
        except Exception as e:
            logger.debug(f"SQLite get_labeled_versions_with_drift failed: {e}")
            return []

    def write_learned_weights(
        self, agent_id: str, learned_weights: dict[str, Any]
    ) -> None:
        """Write learned weights to cache. On UNIQUE conflict, overwrite."""
        try:
            import json

            with Session(self._engine) as session:
                # Check if already exists
                existing = session.exec(
                    select(LearnedWeightsCache).where(
                        LearnedWeightsCache.agent_id == agent_id
                    )
                ).first()

                if existing:
                    existing.weights = json.dumps(learned_weights.get("weights", {}))
                    existing.weights_metadata = json.dumps(
                        learned_weights.get("metadata", {})
                    )
                    existing.n_total = learned_weights.get("n_total", 0)
                    existing.computed_at = datetime.utcnow()
                else:
                    record = LearnedWeightsCache(
                        agent_id=agent_id,
                        weights=json.dumps(learned_weights.get("weights", {})),
                        weights_metadata=json.dumps(
                            learned_weights.get("metadata", {})
                        ),
                        n_total=learned_weights.get("n_total", 0),
                    )
                    session.add(record)

                session.commit()
        except Exception as e:
            logger.debug(f"SQLite write_learned_weights failed: {e}")

    def get_learned_weights(self, agent_id: str) -> dict[str, Any] | None:
        """Return learned weights for agent_id, or None if not found."""
        try:
            import json

            with Session(self._engine) as session:
                cached = session.exec(
                    select(LearnedWeightsCache).where(
                        LearnedWeightsCache.agent_id == agent_id
                    )
                ).first()

                if not cached:
                    return None

                return {
                    "agent_id": cached.agent_id,
                    "weights": json.loads(cached.weights),
                    "metadata": json.loads(cached.weights_metadata),
                    "n_total": cached.n_total,
                    "computed_at": cached.computed_at.isoformat()
                    if isinstance(cached.computed_at, datetime)
                    else cached.computed_at,
                }
        except Exception as e:
            logger.debug(f"SQLite get_learned_weights failed: {e}")
            return None

    def write_significance_threshold(
        self, agent_id: str, version: str, threshold_data: dict[str, Any]
    ) -> None:
        """Write significance threshold for agent_id + version. On conflict, overwrite if baseline_n has grown > 20%."""
        try:
            import json

            with Session(self._engine) as session:
                existing = session.exec(
                    select(SignificanceThreshold).where(
                        SignificanceThreshold.agent_id == agent_id,
                        SignificanceThreshold.version == version,
                    )
                ).first()

                baseline_n_new = threshold_data.get("baseline_n_at_computation", 0)

                # Check if we should recompute: baseline_n has grown by > 20%
                should_overwrite = False
                if existing:
                    baseline_n_old = existing.baseline_n_at_computation
                    if baseline_n_old > 0 and baseline_n_new > baseline_n_old * 1.20:
                        should_overwrite = True
                else:
                    should_overwrite = True

                if should_overwrite:
                    if existing:
                        existing.use_case = threshold_data.get("use_case", "GENERAL")
                        existing.effect_size = threshold_data.get("effect_size", 0.10)
                        existing.min_runs_overall = threshold_data.get("overall", 50)
                        existing.min_runs_per_dim = json.dumps(
                            threshold_data.get("per_dimension", {})
                        )
                        existing.limiting_dim = threshold_data.get(
                            "limiting_dimension", ""
                        )
                        existing.computed_at = datetime.utcnow()
                        existing.baseline_n_at_computation = baseline_n_new
                    else:
                        record = SignificanceThreshold(
                            agent_id=agent_id,
                            version=version,
                            use_case=threshold_data.get("use_case", "GENERAL"),
                            effect_size=threshold_data.get("effect_size", 0.10),
                            min_runs_overall=threshold_data.get("overall", 50),
                            min_runs_per_dim=json.dumps(
                                threshold_data.get("per_dimension", {})
                            ),
                            limiting_dim=threshold_data.get("limiting_dimension", ""),
                            baseline_n_at_computation=baseline_n_new,
                        )
                        session.add(record)

                    session.commit()
        except Exception as e:
            logger.debug(f"SQLite write_significance_threshold failed: {e}")

    def get_significance_threshold(
        self, agent_id: str, version: str
    ) -> dict[str, Any] | None:
        """Return significance threshold for agent_id + version, or None if not found."""
        try:
            import json

            with Session(self._engine) as session:
                cached = session.exec(
                    select(SignificanceThreshold).where(
                        SignificanceThreshold.agent_id == agent_id,
                        SignificanceThreshold.version == version,
                    )
                ).first()

                if not cached:
                    return None

                return {
                    "use_case": cached.use_case,
                    "effect_size": cached.effect_size,
                    "overall": cached.min_runs_overall,
                    "per_dimension": json.loads(cached.min_runs_per_dim),
                    "limiting_dimension": cached.limiting_dim,
                    "baseline_n_at_computation": cached.baseline_n_at_computation,
                    "computed_at": cached.computed_at.isoformat()
                    if isinstance(cached.computed_at, datetime)
                    else cached.computed_at,
                }
        except Exception as e:
            logger.debug(f"SQLite get_significance_threshold failed: {e}")
            return None

    def write_detected_epochs(
        self, agent_id: str, epochs: list[dict[str, Any]], ttl_hours: int = 1
    ) -> None:
        """Write detected epochs to cache. Replaces existing cache for this agent."""
        try:
            from datetime import timedelta

            with Session(self._engine) as session:
                # Clear existing epochs for this agent
                session.execute(
                    text("DELETE FROM detected_epochs WHERE agent_id = :agent_id"),
                    {"agent_id": agent_id},
                )

                # Insert new epochs
                now = datetime.utcnow()
                expires_at = now + timedelta(hours=ttl_hours)

                for epoch in epochs:
                    record = DetectedEpoch(
                        agent_id=agent_id,
                        epoch_label=epoch.get("label", ""),
                        start_run_id=epoch.get("start_run_id"),
                        end_run_id=epoch.get("end_run_id"),
                        start_time=epoch.get("start_time"),
                        end_time=epoch.get("end_time"),
                        run_count=epoch.get("run_count", 0),
                        stability=epoch.get("stability", "UNKNOWN"),
                        summary=epoch.get("summary", ""),
                        detected_at=now,
                        cache_expires_at=expires_at,
                    )
                    session.add(record)

                session.commit()
        except Exception as e:
            logger.debug(f"SQLite write_detected_epochs failed: {e}")

    def get_detected_epochs(self, agent_id: str) -> list[dict[str, Any]] | None:
        """
        Return cached detected epochs for agent_id, or None if cache is expired/missing.
        Checks TTL before returning.
        """
        try:
            with Session(self._engine) as session:
                epochs = session.exec(
                    select(DetectedEpoch)
                    .where(DetectedEpoch.agent_id == agent_id)
                    .order_by(DetectedEpoch.start_time)
                ).all()

                if not epochs:
                    return None

                # Check if cache is expired (use first epoch's TTL)
                now = datetime.utcnow()
                if epochs[0].cache_expires_at < now:
                    # Cache expired, delete and return None
                    session.execute(
                        text("DELETE FROM detected_epochs WHERE agent_id = :agent_id"),
                        {"agent_id": agent_id},
                    )
                    session.commit()
                    return None

                return [
                    {
                        "id": e.id,
                        "label": e.epoch_label,
                        "start_run_id": e.start_run_id,
                        "end_run_id": e.end_run_id,
                        "start_time": e.start_time,
                        "end_time": e.end_time,
                        "run_count": e.run_count,
                        "stability": e.stability,
                        "summary": e.summary,
                    }
                    for e in epochs
                ]
        except Exception as e:
            logger.debug(f"SQLite get_detected_epochs failed: {e}")
            return None

    def clear_detected_epochs(self, agent_id: str) -> None:
        """Clear detected epoch cache for agent_id."""
        try:
            with Session(self._engine) as session:
                session.execute(
                    text("DELETE FROM detected_epochs WHERE agent_id = :agent_id"),
                    {"agent_id": agent_id},
                )
                session.commit()
        except Exception as e:
            logger.debug(f"SQLite clear_detected_epochs failed: {e}")

    def get_connector_sync(
        self, source: str, project_name: str
    ) -> dict[str, Any] | None:
        """Get last sync info for source + project."""
        try:
            with Session(self._engine) as session:
                sync = session.exec(
                    select(ConnectorSync).where(
                        ConnectorSync.source == source,
                        ConnectorSync.project_name == project_name,
                    )
                ).first()

                if not sync:
                    return None

                return {
                    "id": sync.id,
                    "source": sync.source,
                    "project_name": sync.project_name,
                    "agent_id": sync.agent_id,
                    "last_sync_at": sync.last_sync_at,
                    "runs_imported": sync.runs_imported,
                    "last_external_id": sync.last_external_id,
                    "status": sync.status,
                }
        except Exception as e:
            logger.debug(f"SQLite get_connector_sync failed: {e}")
            return None

    def write_connector_sync(
        self,
        source: str,
        project_name: str,
        agent_id: str,
        runs_imported: int,
        last_external_id: str | None = None,
        status: str = "success",
    ) -> None:
        """Update sync metadata (upsert by source + project_name)."""
        try:
            with Session(self._engine) as session:
                existing = session.exec(
                    select(ConnectorSync).where(
                        ConnectorSync.source == source,
                        ConnectorSync.project_name == project_name,
                    )
                ).first()

                if existing:
                    existing.agent_id = agent_id
                    existing.last_sync_at = datetime.utcnow()
                    existing.runs_imported += runs_imported
                    if last_external_id:
                        existing.last_external_id = last_external_id
                    existing.status = status
                else:
                    sync = ConnectorSync(
                        source=source,
                        project_name=project_name,
                        agent_id=agent_id,
                        runs_imported=runs_imported,
                        last_external_id=last_external_id,
                        status=status,
                    )
                    session.add(sync)

                session.commit()
        except Exception as e:
            logger.debug(f"SQLite write_connector_sync failed: {e}")

    def save_verdict(
        self,
        report_json: str,
        baseline_version: str,
        current_version: str,
        environment: str,
        composite_score: float,
        verdict: str | None,
        severity: str | None,
        confidence_tier: str,
    ) -> str:
        """
        Save a verdict to the verdict_history table.

        Args:
            report_json: Serialized DriftReport as JSON string
            baseline_version: Baseline deployment version
            current_version: Current deployment version
            environment: Environment (e.g. production)
            composite_score: Composite drift score
            verdict: SHIP/MONITOR/REVIEW/BLOCK or None
            severity: none/low/moderate/significant/critical or None
            confidence_tier: TIER1/TIER2/TIER3

        Returns:
            Verdict ID (UUID string)
        """
        try:
            with Session(self._engine) as session:
                record = VerdictRecord(
                    baseline_version=baseline_version,
                    current_version=current_version,
                    environment=environment,
                    composite_score=composite_score,
                    verdict=verdict,
                    severity=severity,
                    confidence_tier=confidence_tier,
                    report_json=report_json,
                )
                session.add(record)
                session.commit()
                session.refresh(record)
                return record.id
        except Exception as e:
            logger.warning(f"Failed to save verdict: {e}")
            return str(uuid4())  # Return dummy ID on failure

    def get_verdict(self, verdict_id: str) -> dict[str, Any] | None:
        """
        Retrieve a verdict by ID.

        Args:
            verdict_id: Verdict ID (UUID)

        Returns:
            Dict with verdict fields or None if not found
        """
        try:
            with Session(self._engine) as session:
                record = session.get(VerdictRecord, verdict_id)
                if record is None:
                    return None
                return {
                    "id": record.id,
                    "created_at": record.created_at,
                    "baseline_version": record.baseline_version,
                    "current_version": record.current_version,
                    "environment": record.environment,
                    "composite_score": record.composite_score,
                    "verdict": record.verdict,
                    "severity": record.severity,
                    "confidence_tier": record.confidence_tier,
                    "report_json": record.report_json,
                }
        except Exception as e:
            logger.debug(f"Failed to get verdict {verdict_id}: {e}")
            return None

    def list_verdicts(self, limit: int = 20) -> list[dict[str, Any]]:
        """
        List recent verdicts in reverse chronological order.

        Args:
            limit: Maximum number of verdicts to return (default 20)

        Returns:
            List of verdict dicts (most recent first)
        """
        try:
            with Session(self._engine) as session:
                statement = (
                    select(VerdictRecord)
                    .order_by(VerdictRecord.created_at.desc())
                    .limit(limit)
                )
                records = session.exec(statement).all()
                return [
                    {
                        "id": r.id,
                        "created_at": r.created_at,
                        "baseline_version": r.baseline_version,
                        "current_version": r.current_version,
                        "environment": r.environment,
                        "composite_score": r.composite_score,
                        "verdict": r.verdict,
                        "severity": r.severity,
                        "confidence_tier": r.confidence_tier,
                        "report_json": r.report_json,
                    }
                    for r in records
                ]
        except Exception as e:
            logger.debug(f"Failed to list verdicts: {e}")
            return []

    def save_blob(
        self, run_id: str, field_name: str, content: str, session: Session | None = None
    ) -> str:
        """
        Save blob content for a run field.

        Args:
            run_id: Run ID
            field_name: Field name ("input" or "output")
            content: Full text content
            session: Optional session to use (for transactional context)

        Returns:
            Blob ID

        Note:
            If blob storage is disabled or content exceeds size limit,
            truncates and sets truncated=True. Never fails ingestion.
        """
        try:
            settings = get_settings()
            if not settings.DRIFTBASE_BLOB_STORAGE:
                logger.debug(
                    f"Blob storage disabled, skipping {field_name} for {run_id}"
                )
                return ""

            # Check size and truncate if needed
            size_limit = settings.DRIFTBASE_BLOB_SIZE_LIMIT
            truncated = False
            original_length = len(content)

            if original_length > size_limit:
                content = content[:size_limit]
                truncated = True
                logger.debug(
                    f"Truncated {field_name} blob for {run_id}: "
                    f"{original_length} -> {size_limit} bytes"
                )

            # Compute SHA-256 hash
            content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()

            # Create blob
            blob = RunBlob(
                run_id=run_id,
                field_name=field_name,
                content=content,
                content_length=original_length,
                content_hash=content_hash,
                truncated=truncated,
            )

            if session is not None:
                # Use provided session (transactional context)
                session.add(blob)
                session.flush()  # Get blob.id without committing
                return blob.id
            else:
                # Create new session and commit
                with Session(self._engine) as new_session:
                    new_session.add(blob)
                    new_session.commit()
                    new_session.refresh(blob)
                    return blob.id

        except Exception as e:
            logger.warning(f"Failed to save blob for {run_id}.{field_name}: {e}")
            return ""

    def get_blob(self, run_id: str, field_name: str) -> RunBlob | None:
        """
        Get blob content for a run field.

        Args:
            run_id: Run ID
            field_name: Field name ("input" or "output")

        Returns:
            RunBlob if found, None otherwise
        """
        try:
            with Session(self._engine) as session:
                statement = select(RunBlob).where(
                    RunBlob.run_id == run_id, RunBlob.field_name == field_name
                )
                return session.exec(statement).first()
        except Exception as e:
            logger.debug(f"Failed to get blob for {run_id}.{field_name}: {e}")
            return None

    def get_blobs_for_run(self, run_id: str) -> list[RunBlob]:
        """
        Get all blobs for a run.

        Args:
            run_id: Run ID

        Returns:
            List of RunBlob objects (may be empty)
        """
        try:
            with Session(self._engine) as session:
                statement = select(RunBlob).where(RunBlob.run_id == run_id)
                return list(session.exec(statement).all())
        except Exception as e:
            logger.debug(f"Failed to get blobs for run {run_id}: {e}")
            return []

    def save_feedback(
        self,
        verdict_id: str,
        action: str,
        agent_id: str | None = None,
        reason: str | None = None,
        dismissed_dimensions: list[str] | None = None,
    ) -> str:
        """
        Save user feedback on a drift verdict.

        Args:
            verdict_id: Verdict ID (FK to verdict_history)
            action: "dismiss" | "acknowledge" | "investigate"
            agent_id: Agent identifier for per-agent learning
            reason: Free text explanation from user
            dismissed_dimensions: List of dimension names to downweight

        Returns:
            Feedback ID (UUID)
        """
        try:
            import json

            with Session(self._engine) as session:
                feedback = DriftFeedback(
                    verdict_id=verdict_id,
                    action=action,
                    agent_id=agent_id,
                    reason=reason,
                    dismissed_dimensions=json.dumps(dismissed_dimensions)
                    if dismissed_dimensions
                    else None,
                )
                session.add(feedback)
                session.commit()
                session.refresh(feedback)
                return feedback.id
        except Exception as e:
            logger.warning(f"Failed to save feedback: {e}")
            return str(uuid4())  # Return dummy ID on failure

    def get_feedback_for_verdict(self, verdict_id: str) -> list[dict[str, Any]]:
        """
        Get all feedback for a specific verdict.

        Args:
            verdict_id: Verdict ID

        Returns:
            List of feedback dicts
        """
        try:
            import json

            with Session(self._engine) as session:
                statement = (
                    select(DriftFeedback)
                    .where(DriftFeedback.verdict_id == verdict_id)
                    .order_by(DriftFeedback.created_at.desc())
                )
                records = session.exec(statement).all()
                return [
                    {
                        "id": r.id,
                        "verdict_id": r.verdict_id,
                        "action": r.action,
                        "agent_id": r.agent_id,
                        "reason": r.reason,
                        "dismissed_dimensions": json.loads(r.dismissed_dimensions)
                        if r.dismissed_dimensions
                        else None,
                        "created_at": r.created_at.isoformat()
                        if isinstance(r.created_at, datetime)
                        else r.created_at,
                    }
                    for r in records
                ]
        except Exception as e:
            logger.debug(f"Failed to get feedback for verdict {verdict_id}: {e}")
            return []

    def get_feedback_for_agent(self, agent_id: str) -> list[dict[str, Any]]:
        """
        Get all feedback for a specific agent (for weight learning).

        Args:
            agent_id: Agent identifier

        Returns:
            List of feedback dicts
        """
        try:
            import json

            with Session(self._engine) as session:
                statement = (
                    select(DriftFeedback)
                    .where(DriftFeedback.agent_id == agent_id)
                    .order_by(DriftFeedback.created_at.desc())
                )
                records = session.exec(statement).all()
                return [
                    {
                        "id": r.id,
                        "verdict_id": r.verdict_id,
                        "action": r.action,
                        "agent_id": r.agent_id,
                        "reason": r.reason,
                        "dismissed_dimensions": json.loads(r.dismissed_dimensions)
                        if r.dismissed_dimensions
                        else None,
                        "created_at": r.created_at.isoformat()
                        if isinstance(r.created_at, datetime)
                        else r.created_at,
                    }
                    for r in records
                ]
        except Exception as e:
            logger.debug(f"Failed to get feedback for agent {agent_id}: {e}")
            return []

    def list_feedback(self, limit: int = 50) -> list[dict[str, Any]]:
        """
        List recent feedback in reverse chronological order.

        Args:
            limit: Maximum number of feedback records to return

        Returns:
            List of feedback dicts (most recent first)
        """
        try:
            import json

            with Session(self._engine) as session:
                statement = (
                    select(DriftFeedback)
                    .order_by(DriftFeedback.created_at.desc())
                    .limit(limit)
                )
                records = session.exec(statement).all()
                return [
                    {
                        "id": r.id,
                        "verdict_id": r.verdict_id,
                        "action": r.action,
                        "agent_id": r.agent_id,
                        "reason": r.reason,
                        "dismissed_dimensions": json.loads(r.dismissed_dimensions)
                        if r.dismissed_dimensions
                        else None,
                        "created_at": r.created_at.isoformat()
                        if isinstance(r.created_at, datetime)
                        else r.created_at,
                    }
                    for r in records
                ]
        except Exception as e:
            logger.debug(f"Failed to list feedback: {e}")
            return []
