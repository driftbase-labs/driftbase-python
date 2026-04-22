"""
Run quality scoring for trace data completeness and reliability.

Computes a 0.0-1.0 quality score for each run based on:
- Version clarity (how version was resolved)
- Data completeness (input, output, latency, tokens)
- Feature derivability (whether features computed successfully)
- Observation richness (tool usage, semantic clustering, retry data)

This score is stored but NOT used in fingerprint weighting yet (Phase 2c).
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from driftbase.backends.sqlite import RunFeatures, RunRaw

logger = logging.getLogger(__name__)


def compute_run_quality(raw: RunRaw, features: RunFeatures) -> float:
    """
    Compute a quality score (0.0-1.0) for a run based on completeness signals.

    This score measures how reliable and complete the trace data is for drift
    analysis. Higher scores indicate runs with clear version provenance, complete
    observability data, successful feature derivation, and rich behavioral signals.

    The score is a weighted average of four components:

    **Version Clarity (weight: 0.25)**
    How was the deployment version resolved?
    - release/tag: 1.0 (explicit version tagging)
    - env: 0.7 (environment variable fallback)
    - epoch: 0.3 (time-bucketed fallback)
    - unknown/none: 0.0 (no version information)

    **Data Completeness (weight: 0.25)**
    How much raw trace data was captured?
    - Has non-empty input: +0.25
    - Has non-empty output: +0.25
    - Has latency_ms > 0: +0.20
    - Has token counts (prompt/completion/total): +0.15
    - Has session_id: +0.15
    (sum capped at 1.0)

    **Feature Derivability (weight: 0.25)**
    Did feature derivation succeed?
    - feature_schema_version > 0: 1.0 (success)
    - feature_schema_version == -1: 0.0 (failed)

    **Observation Richness (weight: 0.25)**
    How much behavioral signal is available?
    - Has tool_sequence with >= 1 tool: +0.4
    - Has tool_call_count > 0: +0.2
    - Has semantic_cluster != "unknown": +0.2
    - Has retry_count or loop_count data: +0.2
    (sum capped at 1.0)

    Args:
        raw: RunRaw record (immutable trace data)
        features: RunFeatures record (derived features)

    Returns:
        Quality score between 0.0 and 1.0, rounded to 4 decimal places.
        Returns 0.0 on any exception (never raises).

    Examples:
        Perfect quality run (all data present, explicit version):
        >>> raw = RunRaw(
        ...     version_source="release",
        ...     input="query",
        ...     output="result",
        ...     latency_ms=150,
        ...     tokens_prompt=10,
        ...     session_id="sess-123"
        ... )
        >>> features = RunFeatures(
        ...     feature_schema_version=1,
        ...     tool_sequence='["tool_a", "tool_b"]',
        ...     tool_call_count=2,
        ...     semantic_cluster="resolved",
        ...     retry_count=1
        ... )
        >>> compute_run_quality(raw, features)
        1.0

        Minimal quality run (no version, empty data, failed features):
        >>> raw = RunRaw(version_source="unknown", input="", output="")
        >>> features = RunFeatures(feature_schema_version=-1)
        >>> compute_run_quality(raw, features)
        0.0
    """
    try:
        # Component 1: Version Clarity (0.25 weight)
        version_source = (raw.version_source or "unknown").lower()
        if version_source in ("release", "tag"):
            version_clarity = 1.0
        elif version_source == "env":
            version_clarity = 0.7
        elif version_source == "epoch":
            version_clarity = 0.3
        else:  # "unknown", "none", None, or other
            version_clarity = 0.0

        # Component 2: Data Completeness (0.25 weight)
        data_completeness = 0.0
        if raw.input and raw.input.strip():
            data_completeness += 0.25
        if raw.output and raw.output.strip():
            data_completeness += 0.25
        if raw.latency_ms and raw.latency_ms > 0:
            data_completeness += 0.20
        if (
            (raw.tokens_prompt and raw.tokens_prompt > 0)
            or (raw.tokens_completion and raw.tokens_completion > 0)
            or (raw.tokens_total and raw.tokens_total > 0)
        ):
            data_completeness += 0.15
        if raw.session_id and raw.session_id.strip():
            data_completeness += 0.15
        data_completeness = min(data_completeness, 1.0)

        # Component 3: Feature Derivability (0.25 weight)
        if features.feature_schema_version > 0:
            feature_derivability = 1.0
        else:  # -1 or 0 (failed or not attempted)
            feature_derivability = 0.0

        # Component 4: Observation Richness (0.25 weight)
        observation_richness = 0.0

        # Parse tool_sequence JSON
        try:
            tool_seq = json.loads(features.tool_sequence)
            if isinstance(tool_seq, list) and len(tool_seq) >= 1:
                observation_richness += 0.4
        except (json.JSONDecodeError, TypeError):
            pass

        if features.tool_call_count and features.tool_call_count > 0:
            observation_richness += 0.2

        semantic = (features.semantic_cluster or "unknown").lower()
        if semantic != "unknown" and semantic != "cluster_none":
            observation_richness += 0.2

        if (features.retry_count and features.retry_count > 0) or (
            features.loop_count and features.loop_count > 0
        ):
            observation_richness += 0.2

        observation_richness = min(observation_richness, 1.0)

        # Weighted average
        score = (
            0.25 * version_clarity
            + 0.25 * data_completeness
            + 0.25 * feature_derivability
            + 0.25 * observation_richness
        )

        # Round to 4 decimal places
        return round(score, 4)

    except Exception as e:
        logger.warning(
            f"Failed to compute run_quality for run_id={raw.id}: {e}. Returning 0.0."
        )
        return 0.0
