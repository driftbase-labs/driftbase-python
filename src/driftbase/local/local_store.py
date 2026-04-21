"""
Local persistence for the @track() decorator via pluggable backends.
Also defines AgentRun, BehavioralFingerprint, DriftReport for local drift computation.

Writes runs via get_backend().write_run(payload) in a background thread so capture
adds negligible latency. Backend is chosen by DRIFTBASE_BACKEND (default: sqlite).
"""

from __future__ import annotations

import atexit
import contextlib
import logging
import os
import queue
import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from driftbase.backends.factory import get_backend

logger = logging.getLogger(__name__)


@dataclass
class AgentRun:
    """Single agent run for fingerprinting (matches backend run dict shape)."""

    id: str
    session_id: str
    deployment_version: str
    environment: str
    started_at: datetime
    completed_at: datetime
    task_input_hash: str
    tool_sequence: str
    tool_call_count: int
    output_length: int
    output_structure_hash: str
    latency_ms: int
    error_count: int
    retry_count: int
    semantic_cluster: str
    raw_prompt: str = ""
    raw_output: str = ""
    # New behavioral metrics
    loop_count: int = 0
    time_to_first_tool_ms: int = 0
    verbosity_ratio: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0


@dataclass
class BehavioralFingerprint:
    """Behavioral fingerprint for a deployment version / time window."""

    id: str = ""
    deployment_version: str = ""
    environment: str = ""
    window_start: datetime | None = None
    window_end: datetime | None = None
    sample_count: int = 0
    tool_sequence_distribution: str = "{}"
    avg_tool_call_count: float = 0.0
    p50_latency_ms: int = 0
    p95_latency_ms: int = 0
    p99_latency_ms: int = 0
    avg_output_length: float = 0.0
    error_rate: float = 0.0
    retry_rate: float = 0.0
    top_tool_sequences: str = "{}"
    semantic_cluster_distribution: str = "{}"
    # New behavioral metrics
    avg_loop_count: float = 0.0
    p95_loop_count: float = 0.0
    avg_retry_count: float = 0.0
    avg_verbosity_ratio: float = 0.0
    avg_time_to_first_tool_ms: float = 0.0
    fallback_rate: float = 0.0


@dataclass
class DriftReport:
    """Drift comparison result between two fingerprints."""

    baseline_fingerprint_id: str = ""
    current_fingerprint_id: str = ""
    drift_score: float = 0.0
    severity: str = "none"
    decision_drift: float = 0.0
    latency_drift: float = 0.0
    error_drift: float = 0.0
    output_drift: float = 0.0
    semantic_drift: float = 0.0
    escalation_rate_delta: float = (
        0.0  # current_escalated_frac - baseline_escalated_frac
    )
    summary: str = ""
    # Bootstrap confidence interval (95%)
    drift_score_lower: float = 0.0
    drift_score_upper: float = 0.0
    confidence_interval_pct: int = 95
    sample_size_warning: bool = False
    bootstrap_iterations: int = 0
    # Context values for before→after display
    baseline_escalation_rate: float = 0.0
    current_escalation_rate: float = 0.0
    baseline_p95_latency_ms: float = 0.0
    current_p95_latency_ms: float = 0.0
    baseline_error_rate: float = 0.0
    current_error_rate: float = 0.0
    baseline_dominant_tool: str = ""
    current_dominant_tool: str = ""
    # New behavioral drift dimensions
    verbosity_drift: float = 0.0
    loop_depth_drift: float = 0.0
    output_length_drift: float = 0.0
    tool_sequence_drift: float = 0.0
    retry_drift: float = 0.0
    planning_latency_drift: float = 0.0
    tool_sequence_transitions_drift: float = 0.0
    # Context values for new dimensions
    baseline_avg_verbosity_ratio: float = 0.0
    current_avg_verbosity_ratio: float = 0.0
    baseline_avg_loop_count: float = 0.0
    current_avg_loop_count: float = 0.0
    baseline_avg_output_length: float = 0.0
    current_avg_output_length: float = 0.0
    baseline_avg_retry_count: float = 0.0
    current_avg_retry_count: float = 0.0
    baseline_avg_time_to_first_tool_ms: float = 0.0
    current_avg_time_to_first_tool_ms: float = 0.0
    # Calibration metadata
    inferred_use_case: str = "GENERAL"
    use_case_confidence: float = 0.0
    calibration_method: str = "default"
    calibrated_weights: dict[str, float] | None = None
    composite_thresholds: dict[str, float] | None = None
    baseline_n: int = 0
    # Confidence tier metadata
    confidence_tier: str = "TIER3"  # TIER1 | TIER2 | TIER3
    eval_n: int = 0  # Number of eval runs
    indicative_signal: dict[str, str] | None = None  # Directional signals for TIER2
    runs_needed: int = 0  # Runs needed to reach next tier
    limiting_version: str = ""  # Which version has fewer runs
    baseline_version: str = ""
    eval_version: str = ""
    # Blend metadata
    blend_method: str = "general_fallback"
    behavioral_signals: dict[str, float] | None = None
    # Learned weights metadata
    learned_weights_available: bool = False
    learned_weights_n: int = 0
    top_predictors: list[str] | None = None
    # Correlation adjustment metadata
    correlated_pairs: list[tuple[str, str, float]] = field(default_factory=list)
    correlation_adjusted: bool = False
    # Root cause analysis
    root_cause: Any = None  # RootCauseReport | None (Any to avoid circular import)
    # Rollback suggestion
    rollback_suggestion: Any = (
        None  # RollbackSuggestion | None (Any to avoid circular import)
    )
    # Anomaly detection
    anomaly_signal: Any = None  # AnomalySignal | None (Any to avoid circular import)
    anomaly_override: bool = False
    anomaly_override_reason: str = ""
    # Adaptive power analysis fields
    min_runs_needed: int = 50  # computed via power analysis
    min_runs_per_dimension: dict = field(default_factory=dict)  # {dim: min_runs}
    dimension_significance: dict = field(
        default_factory=dict
    )  # {dim: "reliable"|"indicative"|"insufficient"}
    reliable_dimension_count: int = 0  # how many dims have reached significance
    total_dimension_count: int = 12
    significance_pct: float = 0.0  # reliable_count / total_count
    power_analysis_used: bool = False  # True when power analysis computed the threshold
    limiting_dimension: str = ""  # dimension needing most runs
    partial_tier3: bool = False  # True when 8+ dims reliable but not all
    warnings: list[str] = field(default_factory=list)  # List of warning messages


def _parse_datetime_for_run(v: Any) -> datetime:
    """Parse started_at/completed_at from run dict for AgentRun."""
    if v is None:
        return datetime.utcnow()
    if isinstance(v, datetime):
        return v
    if isinstance(v, str):
        return datetime.fromisoformat(v.replace("Z", "+00:00"))
    return datetime.utcnow()


def run_dict_to_agent_run(d: dict[str, Any]) -> AgentRun:
    """Convert a run dict from get_runs() to an AgentRun for fingerprinting."""
    return AgentRun(
        id=str(d.get("id", "")),
        session_id=str(d.get("session_id", "")),
        deployment_version=str(d.get("deployment_version", "unknown")),
        environment=str(d.get("environment", "production")),
        started_at=_parse_datetime_for_run(d.get("started_at")),
        completed_at=_parse_datetime_for_run(d.get("completed_at")),
        task_input_hash=str(d.get("task_input_hash", "")),
        tool_sequence=str(d.get("tool_sequence", "[]")),
        tool_call_count=int(d.get("tool_call_count", 0)),
        output_length=int(d.get("output_length", 0)),
        output_structure_hash=str(d.get("output_structure_hash", "")),
        latency_ms=int(d.get("latency_ms", 0)),
        error_count=int(d.get("error_count", 0)),
        retry_count=int(d.get("retry_count", 0)),
        semantic_cluster=str(d.get("semantic_cluster", "cluster_none")),
        raw_prompt=str(d.get("raw_prompt", "") or ""),
        raw_output=str(d.get("raw_output", "") or ""),
        # New behavioral metrics with safe defaults
        loop_count=int(d.get("loop_count", 0)),
        time_to_first_tool_ms=int(d.get("time_to_first_tool_ms", 0)),
        verbosity_ratio=float(d.get("verbosity_ratio", 0.0)),
        prompt_tokens=int(d.get("prompt_tokens", 0)),
        completion_tokens=int(d.get("completion_tokens", 0)),
    )


def _log_dir() -> str:
    return os.path.dirname(
        os.path.expanduser(os.getenv("DRIFTBASE_DB_PATH", "~/.driftbase/runs.db"))
    )


def _log_track_error(context: str, message: str) -> None:
    log_dir = _log_dir()
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, "errors.log")
    try:
        with open(log_file, "a") as f:
            f.write(f"[{datetime.utcnow().isoformat()}] {context}: {message}\n")
    except Exception:
        pass


_write_queue: queue.Queue[dict[str, Any] | None] = queue.Queue(
    maxsize=int(os.getenv("DRIFTBASE_MAX_QUEUE_SIZE", "1000"))
)
_worker: threading.Thread | None = None
_drop_counter: int = 0
_batch_counter: int = 0  # Track batches written to trigger periodic pruning

BATCH_SIZE = 10
BATCH_TIMEOUT_S = 0.05  # 50ms
PRUNE_EVERY_N_BATCHES = (
    100  # Only prune once every 100 batches to avoid excessive COUNT queries
)


def _flush_batch(batch: list[dict[str, Any]]) -> None:
    """Write a batch of runs in one transaction. Must not raise."""
    if not batch:
        return
    try:
        get_backend().write_runs(batch)
    except Exception as e:
        logger.debug("Local store write failed: %s", e)
        _log_track_error("local_store_write", str(e))


def _prune_if_needed() -> None:
    """
    Trigger retention pruning on the backend if needed.

    This runs in the background worker thread and is called periodically
    (once every PRUNE_EVERY_N_BATCHES) to avoid excessive overhead.
    The backend will check the count before deleting.

    Must never raise - all exceptions are caught to prevent worker crashes.
    """
    try:
        backend = get_backend()
        # Check if backend has prune_if_needed method (SQLite backend)
        if hasattr(backend, "prune_if_needed"):
            backend.prune_if_needed()
    except Exception as e:
        logger.debug("Retention pruning failed: %s", e)
        # Never crash the worker thread


def _check_budgets_for_batch(batch: list[dict[str, Any]]) -> None:
    """
    Check budgets for all agent_id + version combinations in the batch.

    This runs in the background worker thread after runs are written.
    Must never raise - all exceptions are caught to prevent worker crashes.
    """
    if not batch:
        return

    try:
        from driftbase.config import get_settings
        from driftbase.local.budget import (
            check_budget,
            format_breach_warning,
            parse_budget,
        )

        backend = get_backend()
        settings = get_settings()
        window = settings.DRIFTBASE_BUDGET_WINDOW

        # Get unique agent_id + version pairs from batch
        agent_versions = set()
        for payload in batch:
            agent_id = payload.get("session_id", "")
            version = payload.get("deployment_version", "unknown")
            if agent_id and version:
                agent_versions.add((agent_id, version))

        # Check budgets for each unique agent_id + version
        for agent_id, version in agent_versions:
            try:
                # Load budget config from SQLite
                budget_config_row = backend.get_budget_config(agent_id, version)
                if not budget_config_row:
                    continue

                budget_dict = budget_config_row.get("config", {})
                if not budget_dict:
                    continue

                budget_config = parse_budget(budget_dict)
                if not budget_config.limits:
                    continue

                # Load last N runs for this agent_id + version
                runs = backend.get_runs(
                    deployment_version=version,
                    environment=None,
                    limit=window,
                )

                # Filter by session_id to match agent_id
                runs = [r for r in runs if r.get("session_id") == agent_id]

                if len(runs) < 5:
                    # Need at least 5 runs before checking budgets
                    continue

                # Check budget
                breaches = check_budget(budget_config, runs, window)

                # Write breaches and log warnings
                for breach in breaches:
                    breach_dict = {
                        "agent_id": breach.agent_id,
                        "version": breach.version,
                        "dimension": breach.dimension,
                        "budget_key": breach.budget_key,
                        "limit": breach.limit,
                        "actual": breach.actual,
                        "direction": breach.direction,
                        "run_count": breach.run_count,
                        "breached_at": breach.breached_at,
                    }
                    backend.write_budget_breach(breach_dict)

                    # Log warning to console
                    warning = format_breach_warning(breach)
                    logger.warning(f"[driftbase] {warning}")

            except Exception as e:
                logger.debug(f"Budget check failed for {agent_id}/{version}: {e}")
                # Never crash the worker thread

    except Exception as e:
        logger.debug(f"Budget batch check failed: {e}")
        # Never crash the worker thread


def _worker_loop() -> None:
    """
    Background worker loop that processes queued runs in batches.

    After writing each batch, increments a counter and triggers retention
    pruning once every PRUNE_EVERY_N_BATCHES to avoid excessive overhead.
    Also checks budgets after each batch is written.
    """
    global _batch_counter
    batch: list[dict[str, Any]] = []
    while True:
        try:
            payload = _write_queue.get(timeout=BATCH_TIMEOUT_S)
            if payload is None:
                if batch:
                    _flush_batch(batch)
                    _check_budgets_for_batch(batch)
                    _batch_counter += 1
                    # Prune after final batch on shutdown if counter threshold reached
                    if _batch_counter >= PRUNE_EVERY_N_BATCHES:
                        _prune_if_needed()
                        _batch_counter = 0
                break
            batch.append(payload)
            if len(batch) >= BATCH_SIZE:
                _flush_batch(batch)
                _check_budgets_for_batch(batch)
                _batch_counter += 1
                # Check if it's time to prune (once every 100 batches)
                if _batch_counter >= PRUNE_EVERY_N_BATCHES:
                    _prune_if_needed()
                    _batch_counter = 0
                batch = []
        except queue.Empty:
            if batch:
                _flush_batch(batch)
                _check_budgets_for_batch(batch)
                _batch_counter += 1
                # Check if it's time to prune
                if _batch_counter >= PRUNE_EVERY_N_BATCHES:
                    _prune_if_needed()
                    _batch_counter = 0
                batch = []


def enqueue_run(payload: dict[str, Any]) -> None:
    """Enqueue an agent run for non-blocking write. Safe to call from any thread."""
    global _worker, _drop_counter
    if _worker is None:
        _worker = threading.Thread(target=_worker_loop, daemon=True)
        _worker.start()
    try:
        _write_queue.put_nowait(payload)
    except queue.Full:
        try:
            _drop_counter += 1
            if _drop_counter >= 100:
                logger.warning(
                    "Driftbase: 100 telemetry payloads dropped — background writer cannot keep up. "
                    "Consider reducing agent throughput or increasing DRIFTBASE_MAX_QUEUE_SIZE."
                )
                _drop_counter = 0
        except Exception:
            pass  # Never crash the host application
        _log_track_error("enqueue_run", "Queue full — run dropped")


def shutdown_local_store() -> None:
    """Signal the worker to stop (e.g. at exit). Pending runs may still be written."""
    with contextlib.suppress(queue.Full):
        _write_queue.put_nowait(None)


def drain_local_store(timeout: float = 2.0) -> None:
    """Signal shutdown and block until the write worker has flushed and exited. Use in tests to avoid time.sleep."""
    global _worker
    with contextlib.suppress(queue.Full):
        _write_queue.put_nowait(None)
    if _worker is not None:
        _worker.join(timeout=timeout)
        _worker = None


atexit.register(shutdown_local_store)
