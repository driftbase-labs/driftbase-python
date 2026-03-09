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
