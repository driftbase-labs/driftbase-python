"""
OTLP metrics emission for drift scores.

Exports drift metrics in OTLP-compatible format for observability integrations.
Uses local JSON file approach (no external dependencies).
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Verdict string to numeric mapping for gauge metric
VERDICT_VALUES = {
    "SHIP": 0,
    "MONITOR": 1,
    "REVIEW": 2,
    "BLOCK": 3,
}

# Confidence tier to numeric mapping
TIER_VALUES = {
    "TIER1": 1,
    "TIER2": 2,
    "TIER3": 3,
}


def emit_drift_metrics(
    report: Any,
    baseline_version: str,
    current_version: str,
    endpoint: str | None = None,
) -> None:
    """
    Emit drift metrics in OTLP-compatible format.

    Implementation: Local JSON file for scraping (Option C).
    Writes metrics to ~/.driftbase/metrics.json for external collection.

    Args:
        report: DriftReport containing drift scores
        baseline_version: Baseline deployment version
        current_version: Current deployment version
        endpoint: Optional OTLP endpoint (unused in Option C)

    Metrics emitted:
        - driftbase.drift.composite (gauge): Overall drift score
        - driftbase.drift.{dimension} (gauge): Per-dimension scores
        - driftbase.verdict (gauge): 0=SHIP, 1=MONITOR, 2=REVIEW, 3=BLOCK
        - driftbase.confidence_tier (gauge): 1/2/3 for TIER1/TIER2/TIER3

    Attributes (labels):
        - baseline_version
        - current_version
        - environment
        - verdict

    Never raises - logs errors and returns.
    """
    try:
        # Get metrics file path (default: ~/.driftbase/metrics.json)
        metrics_path = os.environ.get(
            "DRIFTBASE_METRICS_PATH",
            str(Path.home() / ".driftbase" / "metrics.json"),
        )

        # Ensure directory exists
        Path(metrics_path).parent.mkdir(parents=True, exist_ok=True)

        # Build common attributes
        attributes = {
            "baseline_version": baseline_version,
            "current_version": current_version,
            "environment": getattr(report, "environment", "production"),
            "verdict": getattr(report, "verdict", "UNKNOWN"),
        }

        # Build metrics payload
        metrics = []
        timestamp = int(datetime.utcnow().timestamp() * 1000)  # Unix timestamp in ms

        # Composite drift score
        metrics.append(
            {
                "name": "driftbase.drift.composite",
                "type": "gauge",
                "value": float(getattr(report, "drift_score", 0.0)),
                "timestamp": timestamp,
                "attributes": attributes,
            }
        )

        # Per-dimension drift scores
        dimension_fields = [
            "decision_drift",
            "latency_drift",
            "error_drift",
            "semantic_drift",
            "tool_distribution_drift",
            "verbosity_drift",
            "loop_depth_drift",
            "output_length_drift",
            "tool_sequence_drift",
            "retry_drift",
            "time_to_first_tool_drift",
            "tool_sequence_transitions_drift",
        ]

        for dim in dimension_fields:
            value = getattr(report, dim, 0.0)
            metrics.append(
                {
                    "name": f"driftbase.drift.{dim.replace('_drift', '')}",
                    "type": "gauge",
                    "value": float(value),
                    "timestamp": timestamp,
                    "attributes": attributes,
                }
            )

        # Verdict metric (numeric)
        verdict_str = getattr(report, "verdict", None)
        if verdict_str and verdict_str in VERDICT_VALUES:
            metrics.append(
                {
                    "name": "driftbase.verdict",
                    "type": "gauge",
                    "value": VERDICT_VALUES[verdict_str],
                    "timestamp": timestamp,
                    "attributes": attributes,
                }
            )

        # Confidence tier metric
        tier_str = getattr(report, "confidence_tier", "TIER3")
        if tier_str in TIER_VALUES:
            metrics.append(
                {
                    "name": "driftbase.confidence_tier",
                    "type": "gauge",
                    "value": TIER_VALUES[tier_str],
                    "timestamp": timestamp,
                    "attributes": attributes,
                }
            )

        # Write metrics to file
        with open(metrics_path, "w") as f:
            json.dump(
                {
                    "format": "driftbase_otlp_v1",
                    "exported_at": datetime.utcnow().isoformat(),
                    "metrics": metrics,
                },
                f,
                indent=2,
            )

        logger.debug(f"Emitted {len(metrics)} metrics to {metrics_path}")

    except Exception as e:
        logger.warning(f"Failed to emit OTLP metrics: {e}")
