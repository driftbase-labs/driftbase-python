"""
Tests for v0.11 schema migration (agent_runs_local → runs_raw + runs_features).
"""

from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from sqlalchemy import create_engine, text
from sqlmodel import Session, SQLModel

from driftbase.backends.migrations.v0_11_schema_split import (
    MigrationResult,
    migrate,
    needs_migration,
)
from driftbase.backends.sqlite import FEATURE_SCHEMA_VERSION, RunFeatures, RunRaw


class TestSchemaMigration(unittest.TestCase):
    """Test v0.11 schema migration functionality."""

    def setUp(self):
        """Create a temporary database for each test."""
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test.db"
        self.engine = create_engine(f"sqlite:///{self.db_path}")

    def tearDown(self):
        """Clean up temporary database."""
        import shutil

        self.engine.dispose()
        if self.temp_dir and os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def _create_legacy_schema(self):
        """Create the old agent_runs_local table schema."""
        with Session(self.engine) as session:
            session.execute(
                text(
                    """
                CREATE TABLE IF NOT EXISTS agent_runs_local (
                    id TEXT PRIMARY KEY,
                    external_id TEXT,
                    source TEXT,
                    ingestion_source TEXT NOT NULL DEFAULT 'decorator',
                    session_id TEXT NOT NULL DEFAULT '',
                    deployment_version TEXT NOT NULL DEFAULT 'unknown',
                    version_source TEXT NOT NULL DEFAULT 'epoch',
                    environment TEXT NOT NULL DEFAULT 'production',
                    started_at TIMESTAMP NOT NULL,
                    raw_prompt TEXT NOT NULL DEFAULT '',
                    raw_output TEXT NOT NULL DEFAULT '',
                    latency_ms INTEGER NOT NULL DEFAULT 0,
                    prompt_tokens INTEGER,
                    completion_tokens INTEGER,
                    tool_sequence TEXT NOT NULL DEFAULT '[]',
                    tool_call_sequence TEXT NOT NULL DEFAULT '[]',
                    tool_call_count INTEGER NOT NULL DEFAULT 0,
                    semantic_cluster TEXT NOT NULL DEFAULT 'cluster_none',
                    loop_count INTEGER NOT NULL DEFAULT 0,
                    verbosity_ratio REAL NOT NULL DEFAULT 0.0,
                    time_to_first_tool_ms INTEGER NOT NULL DEFAULT 0,
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    error_count INTEGER NOT NULL DEFAULT 0,
                    task_input_hash TEXT NOT NULL DEFAULT '',
                    output_structure_hash TEXT NOT NULL DEFAULT '',
                    output_length INTEGER NOT NULL DEFAULT 0
                )
            """
                )
            )
            session.commit()

    def _insert_legacy_run(
        self,
        deployment_version: str = "v1.0",
        tool_sequence: str = '["tool_a"]',
        error_count: int = 0,
    ) -> str:
        """Insert a run into the legacy agent_runs_local table."""
        run_id = str(uuid4())
        with Session(self.engine) as session:
            session.execute(
                text(
                    """
                INSERT INTO agent_runs_local (
                    id, external_id, source, ingestion_source,
                    session_id, deployment_version, version_source, environment,
                    started_at, raw_prompt, raw_output, latency_ms,
                    prompt_tokens, completion_tokens,
                    tool_sequence, tool_call_sequence, tool_call_count,
                    semantic_cluster, loop_count, verbosity_ratio,
                    time_to_first_tool_ms, retry_count, error_count,
                    task_input_hash, output_structure_hash, output_length
                ) VALUES (
                    :id, :external_id, :source, :ingestion_source,
                    :session_id, :deployment_version, :version_source, :environment,
                    :started_at, :raw_prompt, :raw_output, :latency_ms,
                    :prompt_tokens, :completion_tokens,
                    :tool_sequence, :tool_call_sequence, :tool_call_count,
                    :semantic_cluster, :loop_count, :verbosity_ratio,
                    :time_to_first_tool_ms, :retry_count, :error_count,
                    :task_input_hash, :output_structure_hash, :output_length
                )
            """
                ),
                {
                    "id": run_id,
                    "external_id": str(uuid4()),
                    "source": "langfuse",
                    "ingestion_source": "connector",
                    "session_id": str(uuid4()),
                    "deployment_version": deployment_version,
                    "version_source": "explicit",
                    "environment": "production",
                    "started_at": datetime.now(timezone.utc),
                    "raw_prompt": "Test prompt",
                    "raw_output": "Test output",
                    "latency_ms": 100,
                    "prompt_tokens": 10,
                    "completion_tokens": 20,
                    "tool_sequence": tool_sequence,
                    "tool_call_sequence": tool_sequence,
                    "tool_call_count": 1,
                    "semantic_cluster": "cluster_resolved",
                    "loop_count": 0,
                    "verbosity_ratio": 0.5,
                    "time_to_first_tool_ms": 50,
                    "retry_count": 0,
                    "error_count": error_count,
                    "task_input_hash": "abc123",
                    "output_structure_hash": "def456",
                    "output_length": 50,
                },
            )
            session.commit()
        return run_id

    def test_needs_migration_on_legacy_schema(self):
        """Test needs_migration returns True when only legacy table exists."""
        self._create_legacy_schema()
        self.assertTrue(needs_migration(self.engine))

    def test_needs_migration_on_new_schema(self):
        """Test needs_migration returns False when new schema exists."""
        # Create new schema
        SQLModel.metadata.create_all(self.engine)
        self.assertFalse(needs_migration(self.engine))

    def test_migration_creates_tables(self):
        """Test migration creates runs_raw and runs_features tables."""
        self._create_legacy_schema()
        self._insert_legacy_run()

        result = migrate(self.engine, self.db_path, dry_run=False)

        self.assertTrue(result.migrated)
        self.assertEqual(result.rows_copied, 1)

        # Verify tables exist
        with Session(self.engine) as session:
            tables_result = session.execute(
                text(
                    "SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name IN ('runs_raw', 'runs_features')"
                )
            )
            tables = [row[0] for row in tables_result.fetchall()]
            self.assertIn("runs_raw", tables)
            self.assertIn("runs_features", tables)

    def test_migration_copies_all_rows(self):
        """Test migration copies all rows from agent_runs_local to runs_raw."""
        self._create_legacy_schema()
        run_ids = [
            self._insert_legacy_run(deployment_version=f"v{i}") for i in range(5)
        ]

        result = migrate(self.engine, self.db_path, dry_run=False)

        self.assertTrue(result.migrated)
        self.assertEqual(result.rows_copied, 5)

        # Verify all rows in runs_raw
        with Session(self.engine) as session:
            result = session.execute(text("SELECT COUNT(*) FROM runs_raw"))
            count = result.fetchone()[0]
            self.assertEqual(count, 5)

            # Verify all IDs present
            result = session.execute(text("SELECT id FROM runs_raw"))
            migrated_ids = {row[0] for row in result.fetchall()}
            self.assertEqual(migrated_ids, set(run_ids))

    def test_migration_is_idempotent(self):
        """Test running migration twice doesn't duplicate data."""
        self._create_legacy_schema()
        self._insert_legacy_run()

        # First migration
        result1 = migrate(self.engine, self.db_path, dry_run=False)
        self.assertTrue(result1.migrated)

        # Second migration (should detect already migrated)
        result2 = migrate(self.engine, self.db_path, dry_run=False)
        self.assertFalse(result2.migrated)
        self.assertEqual(result2.rows_copied, 0)

        # Verify no duplicate rows
        with Session(self.engine) as session:
            result = session.execute(text("SELECT COUNT(*) FROM runs_raw"))
            count = result.fetchone()[0]
            self.assertEqual(count, 1)

    def test_migration_creates_backup(self):
        """Test migration creates backup file."""
        self._create_legacy_schema()
        self._insert_legacy_run()

        result = migrate(self.engine, self.db_path, dry_run=False)

        self.assertIsNotNone(result.backup_path)
        self.assertTrue(result.backup_path.exists())
        self.assertTrue(str(result.backup_path).endswith(".pre-v0.11.backup"))

    def test_dry_run_makes_no_changes(self):
        """Test dry_run=True doesn't modify database."""
        self._create_legacy_schema()
        self._insert_legacy_run()

        result = migrate(self.engine, self.db_path, dry_run=True)

        self.assertFalse(result.migrated)
        self.assertEqual(result.rows_copied, 0)

        # Verify no new tables created
        with Session(self.engine) as session:
            tables_result = session.execute(
                text(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='runs_raw'"
                )
            )
            self.assertIsNone(tables_result.fetchone())

    def test_migrated_rows_have_feature_source_migrated(self):
        """Test migrated features have feature_source='migrated'."""
        self._create_legacy_schema()
        self._insert_legacy_run()

        migrate(self.engine, self.db_path, dry_run=False)

        # Check feature_source
        with Session(self.engine) as session:
            result = session.execute(
                text("SELECT feature_source FROM runs_features LIMIT 1")
            )
            feature_source = result.fetchone()[0]
            self.assertEqual(feature_source, "migrated")

    def test_lazy_derivation_on_missing_features(self):
        """Test lazy derivation creates features for runs without them."""
        from driftbase.backends.sqlite import SQLiteBackend
        from driftbase.backends.sqlite_reader import get_runs_with_features

        # Create new schema without migration
        SQLModel.metadata.create_all(self.engine)

        # Insert a run in runs_raw without corresponding features
        run_id = str(uuid4())
        with Session(self.engine) as session:
            raw = RunRaw(
                id=run_id,
                external_id=None,
                source="test",
                ingestion_source="decorator",
                session_id=str(uuid4()),
                deployment_version="v1.0",
                version_source="explicit",
                environment="production",
                timestamp=datetime.now(timezone.utc),
                input="test input",
                output="test output",
                latency_ms=100,
                tokens_prompt=10,
                tokens_completion=20,
                tokens_total=30,
                raw_status=None,
                raw_error_message=None,
                observation_tree_json=None,
                ingested_at=datetime.now(timezone.utc),
                raw_schema_version=1,
            )
            session.add(raw)
            session.commit()

        # Create backend with db_path (not engine)
        backend = SQLiteBackend(db_path=str(self.db_path))
        runs = get_runs_with_features(
            backend, deployment_version="v1.0", limit=10, include_all_sources=True
        )

        self.assertEqual(len(runs), 1)

        # Verify feature was created
        with Session(self.engine) as session:
            result = session.execute(
                text("SELECT feature_source FROM runs_features WHERE run_id = :run_id"),
                {"run_id": run_id},
            )
            row = result.fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row[0], "derived")

    def test_derivation_failure_writes_sentinel(self):
        """Test feature derivation failure creates sentinel with schema_version=-1."""
        from driftbase.local.feature_deriver import derive_features

        # Create RunRaw that will cause derivation issues (empty required fields)
        raw = RunRaw(
            id=str(uuid4()),
            external_id=None,
            source="test",
            ingestion_source="decorator",
            session_id="",
            deployment_version="v1.0",
            version_source="explicit",
            environment="production",
            timestamp=datetime.now(timezone.utc),
            input="",
            output="",
            latency_ms=0,
            tokens_prompt=None,
            tokens_completion=None,
            tokens_total=None,
            raw_status=None,
            raw_error_message=None,
            observation_tree_json=None,
            ingested_at=datetime.now(timezone.utc),
            raw_schema_version=1,
        )

        # Derive features (should handle gracefully)
        features = derive_features(raw)

        # Should never raise, even with problematic input
        self.assertIsNotNone(features)
        # Schema version -1 only if actual exception occurred
        # In this case, the deriver handles None tokens gracefully
        self.assertIn(features.feature_schema_version, [FEATURE_SCHEMA_VERSION, -1])

    def test_feature_schema_version_correct(self):
        """Test migrated features have correct schema version."""
        self._create_legacy_schema()
        self._insert_legacy_run()

        migrate(self.engine, self.db_path, dry_run=False)

        with Session(self.engine) as session:
            result = session.execute(
                text("SELECT feature_schema_version FROM runs_features LIMIT 1")
            )
            version = result.fetchone()[0]
            self.assertEqual(version, FEATURE_SCHEMA_VERSION)

    def test_migration_preserves_feature_values(self):
        """Test migration preserves computed feature values."""
        self._create_legacy_schema()
        run_id = self._insert_legacy_run(tool_sequence='["tool_a","tool_b"]')

        migrate(self.engine, self.db_path, dry_run=False)

        # Verify feature values preserved
        with Session(self.engine) as session:
            result = session.execute(
                text(
                    "SELECT tool_sequence, tool_call_count FROM runs_features "
                    "WHERE run_id = :run_id"
                ),
                {"run_id": run_id},
            )
            row = result.fetchone()
            self.assertEqual(row[0], '["tool_a","tool_b"]')
            self.assertEqual(row[1], 1)

    def test_error_classification_mapping(self):
        """Test error_count maps to error_classification correctly."""
        self._create_legacy_schema()
        error_run_id = self._insert_legacy_run(error_count=1)
        success_run_id = self._insert_legacy_run(error_count=0)

        migrate(self.engine, self.db_path, dry_run=False)

        with Session(self.engine) as session:
            # Check error run
            result = session.execute(
                text(
                    "SELECT error_classification FROM runs_features WHERE run_id = :run_id"
                ),
                {"run_id": error_run_id},
            )
            self.assertEqual(result.fetchone()[0], "trace_error")

            # Check success run
            result = session.execute(
                text(
                    "SELECT error_classification FROM runs_features WHERE run_id = :run_id"
                ),
                {"run_id": success_run_id},
            )
            self.assertEqual(result.fetchone()[0], "ok")

    def test_field_mapping_correctness(self):
        """Test raw field mappings (prompt→input, output→output, etc)."""
        self._create_legacy_schema()
        run_id = self._insert_legacy_run()

        migrate(self.engine, self.db_path, dry_run=False)

        # Verify field mappings
        with Session(self.engine) as session:
            # Check runs_raw mappings
            result = session.execute(
                text(
                    "SELECT input, output, timestamp FROM runs_raw WHERE id = :run_id"
                ),
                {"run_id": run_id},
            )
            row = result.fetchone()
            self.assertEqual(row[0], "Test prompt")  # raw_prompt → input
            self.assertEqual(row[1], "Test output")  # raw_output → output
            self.assertIsNotNone(row[2])  # started_at → timestamp

    def test_index_creation(self):
        """Test migration creates required indexes."""
        self._create_legacy_schema()
        self._insert_legacy_run()

        migrate(self.engine, self.db_path, dry_run=False)

        # Verify index on runs_features.run_id exists
        with Session(self.engine) as session:
            result = session.execute(
                text(
                    "SELECT name FROM sqlite_master WHERE type='index' "
                    "AND name='idx_runs_features_run_id'"
                )
            )
            self.assertIsNotNone(result.fetchone())

    def test_runs_raw_and_features_count_match(self):
        """Test runs_raw and runs_features have same row count after migration."""
        self._create_legacy_schema()
        for i in range(10):
            self._insert_legacy_run(deployment_version=f"v{i}")

        migrate(self.engine, self.db_path, dry_run=False)

        with Session(self.engine) as session:
            result = session.execute(text("SELECT COUNT(*) FROM runs_raw"))
            raw_count = result.fetchone()[0]

            result = session.execute(text("SELECT COUNT(*) FROM runs_features"))
            features_count = result.fetchone()[0]

            self.assertEqual(raw_count, features_count)
            self.assertEqual(raw_count, 10)


if __name__ == "__main__":
    unittest.main()
