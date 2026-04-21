"""
Schema migration: split agent_runs_local into runs_raw + runs_features.

This migration:
1. Backs up the database before any changes
2. Creates new tables (runs_raw, runs_features)
3. Copies data from agent_runs_local to runs_raw
4. Leaves runs_features empty (lazy derivation on read)
5. Keeps agent_runs_local as read-only safety net

SAFETY: Migration is atomic (transaction), idempotent, and always backs up first.
"""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)


class MigrationError(Exception):
    """Raised when migration fails in a way that requires user intervention."""

    pass


@dataclass
class MigrationResult:
    """Result of running the migration."""

    migrated: bool  # True if migration ran, False if already migrated
    rows_copied: int  # Number of rows copied to runs_raw
    backup_path: Path | None = None  # Path to backup file if created


def needs_migration(engine: Engine) -> bool:
    """
    Check if migration is needed.

    Returns True if agent_runs_local exists and runs_raw does not.
    """
    try:
        with engine.connect() as conn:
            # Check if runs_raw exists
            result = conn.execute(
                text(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='runs_raw'"
                )
            )
            runs_raw_exists = result.fetchone() is not None

            # Check if agent_runs_local exists
            result = conn.execute(
                text(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='agent_runs_local'"
                )
            )
            agent_runs_local_exists = result.fetchone() is not None

            # Need migration if old table exists but new table doesn't
            return agent_runs_local_exists and not runs_raw_exists
    except Exception as e:
        logger.error(f"Failed to check migration status: {e}")
        return False


def backup_db(db_path: Path) -> Path:
    """
    Create backup of database file.

    Args:
        db_path: Path to the database file

    Returns:
        Path to the backup file

    Raises:
        MigrationError: If backup fails
    """
    backup_path = db_path.parent / f"{db_path.name}.pre-v0.11.backup"

    try:
        # If backup already exists, add timestamp suffix
        if backup_path.exists():
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            backup_path = (
                db_path.parent / f"{db_path.name}.pre-v0.11.backup.{timestamp}"
            )

        shutil.copy2(db_path, backup_path)
        logger.info(f"✓ Database backed up to: {backup_path.absolute()}")
        return backup_path
    except Exception as e:
        raise MigrationError(
            f"Failed to create backup at {backup_path}: {e}. "
            "Migration aborted. Your data is safe."
        ) from e


def migrate(engine: Engine, db_path: Path, dry_run: bool = False) -> MigrationResult:
    """
    Migrate agent_runs_local to runs_raw + runs_features schema.

    Args:
        engine: SQLAlchemy engine
        db_path: Path to the database file
        dry_run: If True, report what would happen without making changes

    Returns:
        MigrationResult with migration status and row count

    Raises:
        MigrationError: If migration fails
    """
    # Check if migration is needed
    if not needs_migration(engine):
        logger.info("✓ Schema already migrated to v0.11 (runs_raw + runs_features)")
        return MigrationResult(migrated=False, rows_copied=0)

    # Count rows to migrate
    with engine.connect() as conn:
        result = conn.execute(text("SELECT COUNT(*) FROM agent_runs_local"))
        row_count = result.fetchone()[0]

    if dry_run:
        logger.info(
            f"[DRY RUN] Would migrate {row_count} rows from agent_runs_local to runs_raw"
        )
        logger.info(
            f"[DRY RUN] Would create backup at: {db_path.parent / f'{db_path.name}.pre-v0.11.backup'}"
        )
        logger.info("[DRY RUN] Would create tables: runs_raw, runs_features")
        logger.info("[DRY RUN] runs_features would be left empty (lazy derivation)")
        return MigrationResult(migrated=False, rows_copied=0)

    # CRITICAL: Backup before any changes
    backup_path = backup_db(db_path)

    logger.info(f"Migrating {row_count} rows to new schema...")

    try:
        with engine.begin() as conn:  # Transaction: all-or-nothing
            # Create runs_raw table
            conn.execute(
                text(
                    """
                CREATE TABLE IF NOT EXISTS runs_raw (
                    id TEXT PRIMARY KEY,
                    external_id TEXT,
                    source TEXT,
                    ingestion_source TEXT NOT NULL DEFAULT 'decorator',
                    session_id TEXT NOT NULL DEFAULT '',
                    deployment_version TEXT NOT NULL DEFAULT 'unknown',
                    version_source TEXT NOT NULL DEFAULT 'epoch',
                    environment TEXT NOT NULL DEFAULT 'production',
                    timestamp TIMESTAMP NOT NULL,
                    input TEXT NOT NULL DEFAULT '',
                    output TEXT NOT NULL DEFAULT '',
                    latency_ms INTEGER NOT NULL DEFAULT 0,
                    tokens_prompt INTEGER,
                    tokens_completion INTEGER,
                    tokens_total INTEGER,
                    raw_status TEXT,
                    raw_error_message TEXT,
                    observation_tree_json TEXT,
                    ingested_at TIMESTAMP NOT NULL,
                    raw_schema_version INTEGER NOT NULL DEFAULT 1
                )
                """
                )
            )

            # Create runs_features table
            conn.execute(
                text(
                    """
                CREATE TABLE IF NOT EXISTS runs_features (
                    id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL UNIQUE,
                    feature_schema_version INTEGER NOT NULL DEFAULT 1,
                    derivation_error TEXT,
                    tool_sequence TEXT NOT NULL DEFAULT '[]',
                    tool_call_sequence TEXT NOT NULL DEFAULT '[]',
                    tool_call_count INTEGER NOT NULL DEFAULT 0,
                    semantic_cluster TEXT NOT NULL DEFAULT 'cluster_none',
                    loop_count INTEGER NOT NULL DEFAULT 0,
                    verbosity_ratio REAL NOT NULL DEFAULT 0.0,
                    time_to_first_tool_ms INTEGER NOT NULL DEFAULT 0,
                    fallback_rate REAL NOT NULL DEFAULT 0.0,
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    retry_patterns TEXT NOT NULL DEFAULT '{}',
                    error_classification TEXT NOT NULL DEFAULT 'ok',
                    input_hash TEXT NOT NULL DEFAULT '',
                    output_hash TEXT NOT NULL DEFAULT '',
                    input_length INTEGER NOT NULL DEFAULT 0,
                    output_length INTEGER NOT NULL DEFAULT 0,
                    computed_at TIMESTAMP NOT NULL,
                    FOREIGN KEY (run_id) REFERENCES runs_raw (id)
                )
                """
                )
            )

            # Create index on runs_features.run_id for fast lookups
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS idx_runs_features_run_id ON runs_features(run_id)"
                )
            )

            # Copy data from agent_runs_local to runs_raw
            # Map fields according to design reference
            conn.execute(
                text(
                    """
                INSERT INTO runs_raw (
                    id, external_id, source, ingestion_source,
                    session_id, deployment_version, version_source, environment,
                    timestamp, input, output, latency_ms,
                    tokens_prompt, tokens_completion, tokens_total,
                    raw_status, raw_error_message, observation_tree_json,
                    ingested_at, raw_schema_version
                )
                SELECT
                    id,
                    external_id,
                    source,
                    COALESCE(ingestion_source, 'decorator'),
                    session_id,
                    deployment_version,
                    COALESCE(version_source, 'epoch'),
                    environment,
                    started_at,  -- Use started_at as primary timestamp
                    raw_prompt,  -- Map raw_prompt to input
                    raw_output,  -- Map raw_output to output
                    latency_ms,
                    prompt_tokens,
                    completion_tokens,
                    CASE
                        WHEN prompt_tokens IS NOT NULL AND completion_tokens IS NOT NULL
                        THEN prompt_tokens + completion_tokens
                        ELSE NULL
                    END,
                    CASE WHEN error_count > 0 THEN 'error' ELSE 'success' END,
                    NULL,  -- raw_error_message not in old schema
                    NULL,  -- observation_tree_json not in old schema
                    COALESCE(started_at, datetime('now')),  -- ingested_at fallback
                    1  -- raw_schema_version
                FROM agent_runs_local
                """
                )
            )

            # Do NOT populate runs_features - lazy derivation will handle it

        logger.info(f"✓ Migrated {row_count} rows to runs_raw")
        logger.info(
            "✓ runs_features table created (empty, will be populated on first read)"
        )
        logger.info(f"✓ Backup saved at: {backup_path.absolute()}")

        return MigrationResult(
            migrated=True, rows_copied=row_count, backup_path=backup_path
        )

    except Exception as e:
        logger.error(f"Migration failed: {e}")
        logger.error(f"Your data is safe in the backup at: {backup_path.absolute()}")
        raise MigrationError(
            f"Migration failed: {e}. "
            f"Your original database is backed up at: {backup_path.absolute()}. "
            "To restore, copy the backup file over the current database."
        ) from e
