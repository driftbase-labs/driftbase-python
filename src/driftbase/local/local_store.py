"""
Local persistence for the @track() decorator via pluggable backends.
Also defines AgentRun, BehavioralFingerprint, DriftReport for local drift computation.

Writes runs via get_backend().write_run(payload) in a background thread so capture
adds negligible latency. Backend is chosen by DRIFTBASE_BACKEND (default: sqlite).
"""

from __future__ import annotations

import atexit
import logging
import os
import queue
import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

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


@dataclass
class BehavioralFingerprint:
    """Behavioral fingerprint for a deployment version / time window."""
    id: str = ""
    deployment_version: str = ""
    environment: str = ""
    window_start: Optional[datetime] = None
    window_end: Optional[datetime] = None
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
    escalation_rate_delta: float = 0.0  # current_escalated_frac - baseline_escalated_frac
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
    )


def _log_dir() -> str:
    return os.path.dirname(os.path.expanduser(os.getenv("DRIFTBASE_DB_PATH", "~/.driftbase/runs.db")))


def _log_track_error(context: str, message: str) -> None:
    log_dir = _log_dir()
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, "errors.log")
    try:
        with open(log_file, "a") as f:
            f.write("[%s] %s: %s\n" % (datetime.utcnow().isoformat(), context, message))
    except Exception:
        pass


_write_queue: queue.Queue[Optional[dict[str, Any]]] = queue.Queue(maxsize=500)
_worker: Optional[threading.Thread] = None

BATCH_SIZE = 10
BATCH_TIMEOUT_S = 0.05  # 50ms


def _flush_batch(batch: list[dict[str, Any]]) -> None:
    """Write a batch of runs in one transaction. Must not raise."""
    if not batch:
        return
    try:
        get_backend().write_runs(batch)
    except Exception as e:
        logger.debug("Local store write failed: %s", e)
        _log_track_error("local_store_write", str(e))


def _worker_loop() -> None:
    batch: list[dict[str, Any]] = []
    while True:
        try:
            payload = _write_queue.get(timeout=BATCH_TIMEOUT_S)
            if payload is None:
                if batch:
                    _flush_batch(batch)
                break
            batch.append(payload)
            if len(batch) >= BATCH_SIZE:
                _flush_batch(batch)
                batch = []
        except queue.Empty:
            if batch:
                _flush_batch(batch)
                batch = []


def enqueue_run(payload: dict[str, Any]) -> None:
    """Enqueue an agent run for non-blocking write. Safe to call from any thread."""
    global _worker
    if _worker is None:
        _worker = threading.Thread(target=_worker_loop, daemon=True)
        _worker.start()
    try:
        _write_queue.put_nowait(payload)
    except queue.Full:
        logger.warning("Local store queue full — run dropped")
        _log_track_error("enqueue_run", "Queue full — run dropped")


def shutdown_local_store() -> None:
    """Signal the worker to stop (e.g. at exit). Pending runs may still be written."""
    try:
        _write_queue.put_nowait(None)
    except queue.Full:
        pass


def drain_local_store(timeout: float = 2.0) -> None:
    """Signal shutdown and block until the write worker has flushed and exited. Use in tests to avoid time.sleep."""
    global _worker
    try:
        _write_queue.put_nowait(None)
    except queue.Full:
        pass
    if _worker is not None:
        _worker.join(timeout=timeout)
        _worker = None


atexit.register(shutdown_local_store)
