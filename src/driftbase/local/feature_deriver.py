"""
Feature derivation from RunRaw.

This module encapsulates all feature computation logic that was previously
scattered across connector mapping code. Features are derived from immutable
raw trace data and can be recomputed at any time.

For Phase 2a: observation_tree_json is not yet populated, so feature derivation
is limited to what can be computed from input/output text and token counts.
Phase 4 will backfill observation trees and enable full feature derivation.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import uuid4

from driftbase.backends.sqlite import FEATURE_SCHEMA_VERSION, RunFeatures
from driftbase.connectors.mapper import (
    compute_hash,
    compute_verbosity_ratio,
    infer_semantic_cluster,
)

if TYPE_CHECKING:
    from driftbase.backends.sqlite import RunRaw

logger = logging.getLogger(__name__)


def derive_features(raw: RunRaw) -> RunFeatures:
    """
    Derive all computable features from a RunRaw instance.

    Args:
        raw: RunRaw instance with immutable trace data

    Returns:
        RunFeatures instance ready to insert

    Note:
        This function never raises. On any internal error, it returns a sentinel
        RunFeatures with feature_schema_version=-1 and derivation_error set.

    Phase 2a limitations:
        - observation_tree_json is not yet populated (Phase 4)
        - Tool-related features (tool_sequence, loop_count, etc.) cannot be
          derived without observation tree
        - These fields default to empty/zero values for migrated data
        - New ingestion (connectors/decorator) will still compute them at
          ingestion time using observation data available at that point
    """
    try:
        # Parse observation tree if available (Phase 4+)
        observation_tree = None
        if raw.observation_tree_json:
            try:
                observation_tree = json.loads(raw.observation_tree_json)
            except Exception as e:
                logger.debug(
                    f"Failed to parse observation_tree_json for run {raw.id}: {e}"
                )

        # Determine error classification
        error_classification = "ok"
        if raw.raw_status == "error" or raw.raw_error_message:
            error_classification = "trace_error"
        # Could add "inferred_error" logic based on output content keywords

        # Compute input/output hashes and lengths
        input_hash = compute_hash(raw.input)
        output_hash = compute_hash(raw.output)
        input_length = len(raw.input) if raw.input else 0
        output_length = len(raw.output) if raw.output else 0

        # Infer semantic cluster from output
        is_error = error_classification != "ok"
        semantic_cluster = infer_semantic_cluster(raw.output, is_error)

        # Compute verbosity ratio
        verbosity_ratio = compute_verbosity_ratio(
            raw.tokens_prompt or 0, raw.tokens_completion or 0
        )

        # Features that require observation tree (Phase 4+)
        # For now, use defaults for migrated data
        tool_sequence = "[]"
        tool_call_sequence = "[]"
        tool_call_count = 0
        loop_count = 0
        time_to_first_tool_ms = 0
        retry_count = 0
        retry_patterns = "{}"
        fallback_rate = 0.0

        if observation_tree:
            # Phase 4+: derive tool-related features from observation tree
            # This will be implemented when observation trees are available
            logger.debug(
                f"Observation tree available for run {raw.id}, but parsing not yet implemented"
            )

        return RunFeatures(
            id=str(uuid4()),
            run_id=raw.id,
            feature_schema_version=FEATURE_SCHEMA_VERSION,
            derivation_error=None,
            tool_sequence=tool_sequence,
            tool_call_sequence=tool_call_sequence,
            tool_call_count=tool_call_count,
            semantic_cluster=semantic_cluster,
            loop_count=loop_count,
            verbosity_ratio=verbosity_ratio,
            time_to_first_tool_ms=time_to_first_tool_ms,
            fallback_rate=fallback_rate,
            retry_count=retry_count,
            retry_patterns=retry_patterns,
            error_classification=error_classification,
            input_hash=input_hash,
            output_hash=output_hash,
            input_length=input_length,
            output_length=output_length,
            computed_at=datetime.utcnow(),
        )

    except Exception as e:
        # Degrade gracefully - return sentinel with error
        logger.warning(
            f"Feature derivation failed for run {raw.id}: {e}. "
            "Returning sentinel with feature_schema_version=-1"
        )
        return RunFeatures(
            id=str(uuid4()),
            run_id=raw.id,
            feature_schema_version=-1,
            derivation_error=str(e),
            tool_sequence="[]",
            tool_call_sequence="[]",
            tool_call_count=0,
            semantic_cluster="cluster_none",
            loop_count=0,
            verbosity_ratio=0.0,
            time_to_first_tool_ms=0,
            fallback_rate=0.0,
            retry_count=0,
            retry_patterns="{}",
            error_classification="ok",
            input_hash="",
            output_hash="",
            input_length=0,
            output_length=0,
            computed_at=datetime.utcnow(),
        )
