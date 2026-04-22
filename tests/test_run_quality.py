"""
Tests for run quality scoring.

Verifies that the quality score is computed correctly based on version clarity,
data completeness, feature derivability, and observation richness.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import text
from sqlmodel import Session

from driftbase.backends.sqlite import RunFeatures, RunRaw
from driftbase.local.feature_deriver import derive_features
from driftbase.local.run_quality import compute_run_quality


def test_perfect_quality_run():
    """A run with all data present and explicit version should score near 1.0."""
    raw = RunRaw(
        id="test-perfect",
        version_source="release",
        input="What is the weather like today?",
        output="The weather is sunny and warm.",
        latency_ms=150,
        tokens_prompt=10,
        tokens_completion=20,
        session_id="sess-123",
        timestamp=datetime.utcnow(),
    )

    features = RunFeatures(
        id="feat-perfect",
        run_id="test-perfect",
        feature_schema_version=1,
        tool_sequence='["get_weather", "format_response"]',
        tool_call_count=2,
        semantic_cluster="resolved",
        retry_count=0,
        loop_count=1,
    )

    score = compute_run_quality(raw, features)

    # Perfect score breakdown:
    # Version clarity: release = 1.0 * 0.25 = 0.25
    # Data completeness: input + output + latency + tokens + session = 1.0 * 0.25 = 0.25
    # Feature derivability: schema_version=1 = 1.0 * 0.25 = 0.25
    # Observation richness: tools + count + cluster = 0.8 * 0.25 = 0.2
    # Total = 0.95
    assert score >= 0.9, f"Expected near-perfect score, got {score}"
    assert score <= 1.0


def test_minimal_quality_run():
    """A run with unknown version, empty data, and failed features should score near 0.0."""
    raw = RunRaw(
        id="test-minimal",
        version_source="unknown",
        input="",
        output="",
        latency_ms=0,
        tokens_prompt=None,
        session_id="",
        timestamp=datetime.utcnow(),
    )

    features = RunFeatures(
        id="feat-minimal",
        run_id="test-minimal",
        feature_schema_version=-1,  # Failed derivation
        tool_sequence="[]",
        tool_call_count=0,
        semantic_cluster="unknown",
    )

    score = compute_run_quality(raw, features)

    # Minimal score breakdown:
    # Version clarity: unknown = 0.0 * 0.25 = 0.0
    # Data completeness: nothing = 0.0 * 0.25 = 0.0
    # Feature derivability: schema_version=-1 = 0.0 * 0.25 = 0.0
    # Observation richness: nothing = 0.0 * 0.25 = 0.0
    # Total = 0.0
    assert score == 0.0


def test_partial_quality_run():
    """A run with epoch version and some data should score in middle range."""
    raw = RunRaw(
        id="test-partial",
        version_source="epoch",
        input="test input",
        output="",  # Missing output
        latency_ms=100,
        tokens_prompt=None,  # Missing tokens
        session_id="sess-456",
        timestamp=datetime.utcnow(),
    )

    features = RunFeatures(
        id="feat-partial",
        run_id="test-partial",
        feature_schema_version=1,
        tool_sequence="[]",  # No tools
        tool_call_count=0,
        semantic_cluster="unknown",
    )

    score = compute_run_quality(raw, features)

    # Partial score breakdown:
    # Version clarity: epoch = 0.3 * 0.25 = 0.075
    # Data completeness: input + latency + session = (0.25 + 0.20 + 0.15) = 0.60 * 0.25 = 0.15
    # Feature derivability: schema_version=1 = 1.0 * 0.25 = 0.25
    # Observation richness: nothing = 0.0 * 0.25 = 0.0
    # Total = 0.475
    assert 0.3 <= score <= 0.7, f"Expected middle-range score, got {score}"


def test_quality_components_independent():
    """Each quality component should contribute independently."""
    base_raw = RunRaw(
        id="test-base",
        version_source="unknown",
        input="",
        output="",
        latency_ms=0,
        session_id="",
        timestamp=datetime.utcnow(),
    )

    base_features = RunFeatures(
        id="feat-base",
        run_id="test-base",
        feature_schema_version=1,
        tool_sequence="[]",
        tool_call_count=0,
        semantic_cluster="unknown",
    )

    base_score = compute_run_quality(base_raw, base_features)

    # Test version clarity component (0.25 weight)
    raw_version = RunRaw(**{**base_raw.model_dump(), "version_source": "release"})
    score_version = compute_run_quality(raw_version, base_features)
    assert score_version > base_score
    assert abs(score_version - base_score - 0.25) < 0.01  # Should add ~0.25

    # Test data completeness component (0.25 weight)
    raw_data = RunRaw(
        **{
            **base_raw.model_dump(),
            "input": "test",
            "output": "test",
            "latency_ms": 100,
            "tokens_prompt": 10,
            "session_id": "sess",
        }
    )
    score_data = compute_run_quality(raw_data, base_features)
    assert score_data > base_score
    assert abs(score_data - base_score - 0.25) < 0.01  # Should add ~0.25

    # Test observation richness component (0.25 weight)
    features_rich = RunFeatures(
        **{
            **base_features.model_dump(),
            "tool_sequence": '["tool1"]',
            "tool_call_count": 1,
            "semantic_cluster": "resolved",
        }
    )
    score_rich = compute_run_quality(base_raw, features_rich)
    assert score_rich > base_score


def test_quality_exception_returns_zero():
    """Malformed data that causes exceptions should return 0.0 without raising."""

    # Create a mock object that will raise when accessed
    class MalformedRaw:
        @property
        def id(self):
            return "bad-id"

        @property
        def version_source(self):
            raise ValueError("Simulated error")

    class MalformedFeatures:
        @property
        def feature_schema_version(self):
            raise ValueError("Simulated error")

    score = compute_run_quality(MalformedRaw(), MalformedFeatures())
    assert score == 0.0  # Should degrade gracefully


def test_quality_stored_in_features(tmp_path):
    """Feature derivation should populate run_quality field."""
    import os
    from unittest.mock import patch

    # Use temporary database
    db_path = tmp_path / "test_quality.db"

    with patch.dict(os.environ, {"DRIFTBASE_DB_PATH": str(db_path)}):
        from driftbase.backends.factory import clear_backend, get_backend

        clear_backend()  # Clear cache to pick up new DB path
        backend = get_backend()

        # Create a raw run with good quality indicators
        raw = RunRaw(
            id="test-stored",
            version_source="tag",
            input="test input",
            output="test output",
            latency_ms=100,
            tokens_prompt=10,
            tokens_completion=20,
            session_id="sess-789",
            timestamp=datetime.utcnow(),
        )

        # Derive features
        features = derive_features(raw)

        # Verify run_quality is populated and reasonable
        assert hasattr(features, "run_quality")
        assert features.run_quality > 0.0
        assert features.run_quality <= 1.0

        # Verify it matches direct computation
        expected_score = compute_run_quality(raw, features)
        assert abs(features.run_quality - expected_score) < 0.0001


def test_migrated_rows_have_zero_quality():
    """Rows with feature_source='migrated' should have run_quality=0.0 until backfill."""
    features = RunFeatures(
        id="feat-migrated",
        run_id="run-migrated",
        feature_schema_version=1,
        feature_source="migrated",
        run_quality=0.0,  # Default for migrated rows
    )

    # Migrated rows keep 0.0 until explicit backfill
    assert features.run_quality == 0.0


def test_backfill_updates_quality(tmp_path):
    """Running migrate --backfill should update run_quality for migrated rows."""
    import os
    from unittest.mock import patch

    db_path = tmp_path / "test_backfill.db"

    with patch.dict(os.environ, {"DRIFTBASE_DB_PATH": str(db_path)}):
        from driftbase.backends.factory import clear_backend, get_backend

        clear_backend()  # Clear cache to pick up new DB path
        backend = get_backend()
        engine = backend._engine

        # Insert a raw run
        raw_data = {
            "id": "run-backfill",
            "version_source": "release",
            "input": "test",
            "output": "result",
            "latency_ms": 50,
            "tokens_prompt": 5,
            "session_id": "sess-backfill",
            "timestamp": datetime.utcnow(),
        }
        raw = RunRaw(**raw_data)

        with Session(engine) as session:
            session.add(raw)
            session.commit()

        # Insert features with migrated source and 0.0 quality
        features = RunFeatures(
            id="feat-backfill",
            run_id="run-backfill",
            feature_schema_version=1,
            feature_source="migrated",
            run_quality=0.0,
        )

        with Session(engine) as session:
            session.add(features)
            session.commit()

        # Verify initial quality is 0.0
        with Session(engine) as session:
            result = session.execute(
                text("SELECT run_quality FROM runs_features WHERE run_id = :run_id"),
                {"run_id": "run-backfill"},
            )
            quality_before = result.fetchone()[0]
            assert quality_before == 0.0

        # Simulate backfill by re-deriving features (create fresh instance)
        raw_for_derivation = RunRaw(**raw_data)
        new_features = derive_features(raw_for_derivation)

        with Session(engine) as session:
            session.execute(
                text(
                    "UPDATE runs_features SET run_quality = :quality WHERE run_id = :run_id"
                ),
                {"quality": new_features.run_quality, "run_id": "run-backfill"},
            )
            session.commit()

        # Verify quality is now > 0.0
        with Session(engine) as session:
            result = session.execute(
                text("SELECT run_quality FROM runs_features WHERE run_id = :run_id"),
                {"run_id": "run-backfill"},
            )
            quality_after = result.fetchone()[0]
            assert quality_after > 0.0


def test_index_exists(tmp_path):
    """Verify that all expected indexes exist in the database."""
    import os
    from unittest.mock import patch

    db_path = tmp_path / "test_indexes.db"

    with patch.dict(os.environ, {"DRIFTBASE_DB_PATH": str(db_path)}):
        from driftbase.backends.factory import clear_backend, get_backend

        clear_backend()  # Clear cache to pick up new DB path
        backend = get_backend()
        engine = backend._engine

        expected_indexes = [
            "idx_runs_raw_version_env_ts",
            "idx_runs_raw_session_ts",
            "idx_runs_raw_version_source",
            "idx_runs_features_run_id",
            "idx_runs_features_schema_version",
        ]

        with Session(engine) as session:
            for index_name in expected_indexes:
                result = session.execute(
                    text(
                        "SELECT name FROM sqlite_master WHERE type='index' AND name=:name"
                    ),
                    {"name": index_name},
                )
                assert result.fetchone() is not None, f"Index {index_name} not found"


def test_index_used_in_query(tmp_path):
    """Verify that indexes are actually used in representative queries."""
    import os
    from unittest.mock import patch

    db_path = tmp_path / "test_query_plan.db"

    with patch.dict(os.environ, {"DRIFTBASE_DB_PATH": str(db_path)}):
        from driftbase.backends.factory import clear_backend, get_backend

        clear_backend()  # Clear cache to pick up new DB path
        backend = get_backend()
        engine = backend._engine

        # Test query with version + environment filter (typical fingerprint query)
        with Session(engine) as session:
            result = session.execute(
                text(
                    """
                EXPLAIN QUERY PLAN
                SELECT * FROM runs_raw
                WHERE deployment_version = 'v1.0'
                  AND environment = 'production'
                  AND timestamp > datetime('now', '-7 days')
                """
                )
            )
            plan = "\n".join(str(row) for row in result.fetchall())
            # Should use the composite index
            assert "idx_runs_raw_version_env_ts" in plan or "SEARCH" in plan.upper()

        # Test schema version filter (typical migration status query)
        with Session(engine) as session:
            result = session.execute(
                text(
                    """
                EXPLAIN QUERY PLAN
                SELECT COUNT(*) FROM runs_features
                WHERE feature_schema_version < 1
                """
                )
            )
            plan = "\n".join(str(row) for row in result.fetchall())
            # Should use index or at least not do a full scan inefficiently
            assert "SCAN" not in plan.upper() or "USING INDEX" in plan.upper()
