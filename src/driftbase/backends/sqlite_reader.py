"""
Lazy feature derivation reader for runs_raw + runs_features.

This module provides read operations that automatically derive missing features
on-demand when reading runs from the database. Features are derived once and
cached in runs_features for subsequent reads.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from sqlalchemy import text
from sqlmodel import Session

from driftbase.backends.sqlite import FEATURE_SCHEMA_VERSION, RunFeatures, RunRaw
from driftbase.local.feature_deriver import derive_features

if TYPE_CHECKING:
    from driftbase.backends.sqlite import SQLiteBackend

logger = logging.getLogger(__name__)


def get_runs_with_features(
    backend: SQLiteBackend,
    deployment_version: str | None = None,
    environment: str | None = None,
    limit: int = 1000,
    include_all_sources: bool = False,
) -> list[dict[str, Any]]:
    """
    Query runs_raw with LEFT JOIN to runs_features, deriving missing features on-demand.

    Args:
        backend: SQLiteBackend instance
        deployment_version: Filter by deployment version
        environment: Filter by environment
        limit: Maximum number of runs to return
        include_all_sources: If False, only include connector-sourced runs

    Returns:
        List of run dicts combining raw + feature fields

    Note:
        - Missing features are derived via derive_features() and inserted
        - Stale features (feature_schema_version < current) are re-derived
        - Failed derivations (feature_schema_version == -1) are not retried
    """
    engine = backend._engine

    with Session(engine) as session:
        # Build query with LEFT JOIN
        query = """
            SELECT
                r.id,
                r.external_id,
                r.source,
                r.ingestion_source,
                r.session_id,
                r.deployment_version,
                r.version_source,
                r.environment,
                r.timestamp,
                r.input,
                r.output,
                r.latency_ms,
                r.tokens_prompt,
                r.tokens_completion,
                r.tokens_total,
                r.raw_status,
                r.raw_error_message,
                r.observation_tree_json,
                r.ingested_at,
                r.raw_schema_version,
                f.id as feature_id,
                f.feature_schema_version,
                f.derivation_error,
                f.tool_sequence,
                f.tool_call_sequence,
                f.tool_call_count,
                f.semantic_cluster,
                f.loop_count,
                f.verbosity_ratio,
                f.time_to_first_tool_ms,
                f.fallback_rate,
                f.retry_count,
                f.retry_patterns,
                f.error_classification,
                f.input_hash,
                f.output_hash,
                f.input_length,
                f.output_length,
                f.computed_at
            FROM runs_raw r
            LEFT JOIN runs_features f ON r.id = f.run_id
            WHERE 1=1
        """

        params: dict[str, Any] = {}

        if deployment_version is not None:
            query += " AND r.deployment_version = :deployment_version"
            params["deployment_version"] = deployment_version

        if environment is not None:
            query += " AND r.environment = :environment"
            params["environment"] = environment

        if not include_all_sources:
            query += " AND r.ingestion_source = :ingestion_source"
            params["ingestion_source"] = "connector"

        query += " ORDER BY r.timestamp DESC LIMIT :limit"
        params["limit"] = limit

        result = session.execute(text(query), params)
        rows = result.fetchall()

        # Convert rows to dicts and derive missing features
        run_dicts = []
        for row in rows:
            # Check if features need derivation
            needs_derivation = False
            if row.feature_id is None:
                # No features row exists
                needs_derivation = True
                logger.debug(f"Run {row.id}: features missing, will derive")
            elif (
                row.feature_schema_version is not None
                and row.feature_schema_version < FEATURE_SCHEMA_VERSION
                and row.feature_schema_version != -1
            ):
                # Features are stale (old schema version)
                needs_derivation = True
                logger.debug(
                    f"Run {row.id}: features stale (v{row.feature_schema_version}), will re-derive"
                )
            elif row.feature_schema_version == -1:
                # Previous derivation failed, don't retry
                logger.debug(
                    f"Run {row.id}: derivation previously failed, skipping retry"
                )

            if needs_derivation:
                # Build RunRaw instance from row
                raw = RunRaw(
                    id=row.id,
                    external_id=row.external_id,
                    source=row.source,
                    ingestion_source=row.ingestion_source,
                    session_id=row.session_id,
                    deployment_version=row.deployment_version,
                    version_source=row.version_source,
                    environment=row.environment,
                    timestamp=row.timestamp,
                    input=row.input or "",
                    output=row.output or "",
                    latency_ms=row.latency_ms,
                    tokens_prompt=row.tokens_prompt,
                    tokens_completion=row.tokens_completion,
                    tokens_total=row.tokens_total,
                    raw_status=row.raw_status,
                    raw_error_message=row.raw_error_message,
                    observation_tree_json=row.observation_tree_json,
                    ingested_at=row.ingested_at,
                    raw_schema_version=row.raw_schema_version,
                )

                # Derive features
                features = derive_features(raw)

                # Insert features
                try:
                    session.add(features)
                    session.commit()
                    logger.debug(f"Run {row.id}: features derived and saved")

                    # Use the newly derived features in the result
                    feature_data = features
                except Exception as e:
                    logger.warning(f"Failed to insert features for run {row.id}: {e}")
                    session.rollback()
                    # Use default features on failure
                    feature_data = features
            else:
                # Use existing features from the row
                feature_data = None

            # Build result dict combining raw + features
            # This matches the format returned by _row_to_run_dict() in sqlite.py
            run_dict = {
                "id": row.id,
                "external_id": row.external_id,
                "source": row.source,
                "ingestion_source": row.ingestion_source,
                "session_id": row.session_id,
                "deployment_version": row.deployment_version,
                "version_source": row.version_source,
                "environment": row.environment,
                "started_at": row.timestamp,  # Map timestamp to started_at for compatibility
                "completed_at": row.timestamp,  # Use same timestamp (latency is separate)
                "latency_ms": row.latency_ms,
                "prompt_tokens": row.tokens_prompt,
                "completion_tokens": row.tokens_completion,
                "raw_prompt": row.input,  # Map input to raw_prompt for compatibility
                "raw_output": row.output,  # Map output to raw_output for compatibility
            }

            # Add features (either from row or newly derived)
            if feature_data:
                # Newly derived features
                run_dict.update(
                    {
                        "tool_sequence": feature_data.tool_sequence,
                        "tool_call_sequence": feature_data.tool_call_sequence,
                        "tool_call_count": feature_data.tool_call_count,
                        "semantic_cluster": feature_data.semantic_cluster,
                        "loop_count": feature_data.loop_count,
                        "verbosity_ratio": feature_data.verbosity_ratio,
                        "time_to_first_tool_ms": feature_data.time_to_first_tool_ms,
                        "retry_count": feature_data.retry_count,
                        "error_count": (
                            1 if feature_data.error_classification != "ok" else 0
                        ),
                        "task_input_hash": feature_data.input_hash,
                        "output_structure_hash": feature_data.output_hash,
                        "output_length": feature_data.output_length,
                    }
                )
            else:
                # Use features from existing row
                run_dict.update(
                    {
                        "tool_sequence": row.tool_sequence or "[]",
                        "tool_call_sequence": row.tool_call_sequence or "[]",
                        "tool_call_count": row.tool_call_count or 0,
                        "semantic_cluster": row.semantic_cluster or "cluster_none",
                        "loop_count": row.loop_count or 0,
                        "verbosity_ratio": row.verbosity_ratio or 0.0,
                        "time_to_first_tool_ms": row.time_to_first_tool_ms or 0,
                        "retry_count": row.retry_count or 0,
                        "error_count": (1 if row.error_classification != "ok" else 0),
                        "task_input_hash": row.input_hash or "",
                        "output_structure_hash": row.output_hash or "",
                        "output_length": row.output_length or 0,
                    }
                )

            run_dicts.append(run_dict)

        return run_dicts
