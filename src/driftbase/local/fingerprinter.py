"""Computes behavioral fingerprints from agent execution data."""

import json
import logging
from collections import Counter
from datetime import datetime, timedelta
from typing import Optional

from driftbase.config import get_settings
from driftbase.local.local_store import AgentRun, BehavioralFingerprint

try:
    from driftbase.store import DriftbaseStore, get_store
except ImportError:
    DriftbaseStore = None  # type: ignore[misc, assignment]
    get_store = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)


def _compute_percentile(values: list[int], percentile: int) -> int:
    """Compute a percentile from a list of values.

    Args:
        values: List of integer values.
        percentile: Percentile to compute (0-100).

    Returns:
        The percentile value.
    """
    if not values:
        return 0
    sorted_values = sorted(values)
    index = int(len(sorted_values) * percentile / 100)
    index = min(index, len(sorted_values) - 1)
    return sorted_values[index]


def build_fingerprint_from_runs(
    runs: list[AgentRun],
    window_start: datetime,
    window_end: datetime,
    deployment_version: str,
    environment: str,
) -> BehavioralFingerprint:
    """Build a behavioral fingerprint from a list of runs (does not save to store).

    Used by compute_fingerprint and by temporal baseline logic (same version, two windows).

    Args:
        runs: AgentRun instances for the window.
        window_start: Start of the time window.
        window_end: End of the time window.
        deployment_version: Deployment version label.
        environment: Environment label.

    Returns:
        BehavioralFingerprint instance (not persisted).
    """
    tool_sequences = [run.tool_sequence for run in runs]
    sequence_counts = Counter(tool_sequences)
    total_sequences = len(tool_sequences)

    tool_sequence_distribution = {
        seq: count / total_sequences for seq, count in sequence_counts.items()
    }

    top_sequences = dict(sequence_counts.most_common(10))
    top_tool_sequences = {
        seq: count / total_sequences for seq, count in top_sequences.items()
    }

    semantic_clusters = [
        getattr(run, "semantic_cluster", "cluster_none") for run in runs
    ]
    semantic_counts = Counter(semantic_clusters)
    total_semantic = len(semantic_clusters)
    semantic_cluster_distribution = (
        {c: cnt / total_semantic for c, cnt in semantic_counts.items()}
        if total_semantic
        else {}
    )

    tool_call_counts = [run.tool_call_count for run in runs]
    avg_tool_call_count = sum(tool_call_counts) / len(tool_call_counts)

    latencies = [run.latency_ms for run in runs]
    p50_latency_ms = _compute_percentile(latencies, 50)
    p95_latency_ms = _compute_percentile(latencies, 95)
    p99_latency_ms = _compute_percentile(latencies, 99)

    output_lengths = [run.output_length for run in runs]
    avg_output_length = sum(output_lengths) / len(output_lengths)

    error_counts = [run.error_count for run in runs]
    error_rate = sum(error_counts) / len(runs)

    retry_counts = [run.retry_count for run in runs]
    retry_rate = sum(retry_counts) / len(runs)

    return BehavioralFingerprint(
        deployment_version=deployment_version,
        environment=environment,
        window_start=window_start,
        window_end=window_end,
        sample_count=len(runs),
        tool_sequence_distribution=json.dumps(tool_sequence_distribution),
        avg_tool_call_count=avg_tool_call_count,
        p50_latency_ms=p50_latency_ms,
        p95_latency_ms=p95_latency_ms,
        p99_latency_ms=p99_latency_ms,
        avg_output_length=avg_output_length,
        error_rate=error_rate,
        retry_rate=retry_rate,
        top_tool_sequences=json.dumps(top_tool_sequences),
        semantic_cluster_distribution=json.dumps(semantic_cluster_distribution),
    )


def compute_fingerprint(
    deployment_version: str,
    environment: str,
    window_hours: int = 24,
    store: Optional[DriftbaseStore] = None,
) -> Optional[BehavioralFingerprint]:
    """Synchronous wrapper; runs async compute_fingerprint_async. Prefer compute_fingerprint_async in async code."""
    import asyncio

    return asyncio.run(
        compute_fingerprint_async(
            deployment_version=deployment_version,
            environment=environment,
            window_hours=window_hours,
            store=store,
        )
    )


async def compute_fingerprint_async(
    deployment_version: str,
    environment: str,
    window_hours: int = 24,
    store: Optional[DriftbaseStore] = None,
) -> Optional[BehavioralFingerprint]:
    """Compute a behavioral fingerprint for a deployment version.

    Args:
        deployment_version: The deployment version to fingerprint.
        environment: The environment to filter by.
        window_hours: Number of hours to look back for runs.
        store: Optional DriftbaseStore instance (creates new if not provided).

    Returns:
        BehavioralFingerprint instance or None if insufficient data.
    """
    settings = get_settings()
    min_samples = settings.DRIFTBASE_MIN_SAMPLES

    if store is None:
        from driftbase.store import get_store

        store = get_store()

    window_end = datetime.utcnow()
    window_start = window_end - timedelta(hours=window_hours)

    runs = await store.get_runs_in_window(
        deployment_version=deployment_version,
        environment=environment,
        window_start=window_start,
        window_end=window_end,
    )

    if len(runs) < min_samples:
        logger.warning(
            f"Insufficient samples for fingerprint: {len(runs)} < {min_samples} "
            f"(version={deployment_version}, env={environment})"
        )
        return None

    fingerprint = build_fingerprint_from_runs(
        runs, window_start, window_end, deployment_version, environment
    )
    saved_fingerprint = await store.save_fingerprint(fingerprint)
    logger.info(
        f"Computed fingerprint for {deployment_version} in {environment}: "
        f"{len(runs)} samples, avg_tools={saved_fingerprint.avg_tool_call_count:.1f}, "
        f"p95_latency={saved_fingerprint.p95_latency_ms}ms"
    )

    return saved_fingerprint


def compute_temporal_fingerprints(
    deployment_version: str,
    environment: str,
    baseline_days: Optional[int] = None,
    current_hours: Optional[int] = None,
    store: Optional[DriftbaseStore] = None,
) -> tuple[Optional[BehavioralFingerprint], Optional[BehavioralFingerprint]]:
    """Synchronous wrapper; runs async compute_temporal_fingerprints_async."""
    import asyncio

    return asyncio.run(
        compute_temporal_fingerprints_async(
            deployment_version=deployment_version,
            environment=environment,
            baseline_days=baseline_days,
            current_hours=current_hours,
            store=store,
        )
    )


async def compute_temporal_fingerprints_async(
    deployment_version: str,
    environment: str,
    baseline_days: Optional[int] = None,
    current_hours: Optional[int] = None,
    store: Optional[DriftbaseStore] = None,
) -> tuple[Optional[BehavioralFingerprint], Optional[BehavioralFingerprint]]:
    """Compute rolling-baseline and current-window fingerprints for the same deployment version.

    Used to detect silent LLM provider drift when code version does not change: compare
    "trailing baseline" (e.g. last 7 days) vs "current window" (e.g. last 12 hours).

    Args:
        deployment_version: The deployment version (same for both windows).
        environment: The environment to filter by.
        baseline_days: Number of days for the rolling baseline window (default from settings).
        current_hours: Number of hours for the current window (default from settings).
        store: Optional DriftbaseStore instance.

    Returns:
        (baseline_fingerprint, current_fingerprint), both saved. Either may be None if
        insufficient samples in that window.
    """
    settings = get_settings()
    min_samples = settings.DRIFTBASE_MIN_SAMPLES
    baseline_days = (
        baseline_days if baseline_days is not None else settings.DRIFTBASE_BASELINE_DAYS
    )
    current_hours = (
        current_hours if current_hours is not None else settings.DRIFTBASE_CURRENT_HOURS
    )

    if store is None:
        from driftbase.store import get_store

        store = get_store()

    now = datetime.utcnow()
    baseline_start = now - timedelta(days=baseline_days)
    baseline_end = now
    current_start = now - timedelta(hours=current_hours)
    current_end = now

    baseline_runs = await store.get_runs_in_window(
        deployment_version=deployment_version,
        environment=environment,
        window_start=baseline_start,
        window_end=baseline_end,
    )
    current_runs = await store.get_runs_in_window(
        deployment_version=deployment_version,
        environment=environment,
        window_start=current_start,
        window_end=current_end,
    )

    baseline_fp: Optional[BehavioralFingerprint] = None
    current_fp: Optional[BehavioralFingerprint] = None

    if len(baseline_runs) >= min_samples:
        baseline_fp = build_fingerprint_from_runs(
            baseline_runs, baseline_start, baseline_end, deployment_version, environment
        )
        baseline_fp = await store.save_fingerprint(baseline_fp)
        logger.info(
            f"Temporal baseline fingerprint: {deployment_version} in {environment}, "
            f"{len(baseline_runs)} samples over {baseline_days}d"
        )
    else:
        logger.warning(
            f"Insufficient samples for temporal baseline: {len(baseline_runs)} < {min_samples} "
            f"(version={deployment_version}, env={environment}, window={baseline_days}d)"
        )

    if len(current_runs) >= min_samples:
        current_fp = build_fingerprint_from_runs(
            current_runs, current_start, current_end, deployment_version, environment
        )
        current_fp = await store.save_fingerprint(current_fp)
        logger.info(
            f"Temporal current fingerprint: {deployment_version} in {environment}, "
            f"{len(current_runs)} samples over {current_hours}h"
        )
    else:
        logger.warning(
            f"Insufficient samples for temporal current: {len(current_runs)} < {min_samples} "
            f"(version={deployment_version}, env={environment}, window={current_hours}h)"
        )

    return (baseline_fp, current_fp)


def compute_temporal_baseline_drift(
    deployment_version: str,
    environment: str,
    baseline_days: Optional[int] = None,
    current_hours: Optional[int] = None,
    store: Optional[DriftbaseStore] = None,
):
    """Synchronous wrapper; runs async compute_temporal_baseline_drift_async."""
    import asyncio

    return asyncio.run(
        compute_temporal_baseline_drift_async(
            deployment_version=deployment_version,
            environment=environment,
            baseline_days=baseline_days,
            current_hours=current_hours,
            store=store,
        )
    )


async def compute_temporal_baseline_drift_async(
    deployment_version: str,
    environment: str,
    baseline_days: Optional[int] = None,
    current_hours: Optional[int] = None,
    store: Optional[DriftbaseStore] = None,
):
    """Compute drift between rolling baseline and current window (same deployment version).

    Persists both fingerprints and the drift report. Use this to detect silent provider
    updates when the code version has not changed.

    Returns:
        DriftReport if both windows have sufficient samples and drift was computed;
        None otherwise.
    """
    from driftbase.local.diff import compute_drift

    settings = get_settings()
    if store is None:
        from driftbase.store import get_store

        store = get_store()

    baseline_fp, current_fp = await compute_temporal_fingerprints_async(
        deployment_version=deployment_version,
        environment=environment,
        baseline_days=baseline_days,
        current_hours=current_hours,
        store=store,
    )

    if baseline_fp is None or current_fp is None:
        return None

    drift_report = compute_drift(baseline_fp, current_fp)
    await store.save_drift_report(drift_report)
    logger.info(
        f"Temporal baseline drift for {deployment_version} in {environment}: "
        f"score={drift_report.drift_score:.2f}, severity={drift_report.severity}"
    )
    return drift_report
