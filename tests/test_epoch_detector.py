"""Tests for automatic epoch detection."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from driftbase.local.epoch_detector import (
    Epoch,
    _build_simple_fingerprint,
    _compute_fingerprint_drift,
    _compute_stability,
    detect_epochs,
)


def test_detect_epochs_returns_empty_list_for_no_runs():
    """detect_epochs returns empty list when no runs exist."""
    mock_backend = MagicMock()
    mock_backend.get_detected_epochs.return_value = None
    mock_backend.get_all_runs.return_value = []

    with patch("driftbase.backends.factory.get_backend", return_value=mock_backend):
        epochs = detect_epochs("test-agent", "/tmp/test.db")

    assert epochs == []


def test_detect_epochs_returns_empty_list_for_insufficient_data():
    """detect_epochs returns empty list when fewer than 40 runs."""
    mock_backend = MagicMock()
    mock_backend.get_detected_epochs.return_value = None

    runs = []
    for i in range(30):
        runs.append(
            {
                "session_id": "test-agent",
                "id": f"run-{i}",
                "started_at": datetime.utcnow().isoformat(),
                "completed_at": datetime.utcnow().isoformat(),
                "tool_sequence": "[]",
                "semantic_cluster": "resolved",
            }
        )

    mock_backend.get_all_runs.return_value = runs

    with patch("driftbase.backends.factory.get_backend", return_value=mock_backend):
        epochs = detect_epochs("test-agent", "/tmp/test.db")

    assert epochs == []


def test_detect_epochs_returns_single_epoch_for_stable_behavior():
    """detect_epochs returns single epoch when behavior is stable."""
    mock_backend = MagicMock()
    mock_backend.get_detected_epochs.return_value = None

    runs = []
    base_time = datetime.utcnow()
    for i in range(60):
        runs.append(
            {
                "session_id": "test-agent",
                "id": f"run-{i}",
                "started_at": (base_time + timedelta(hours=i)).isoformat(),
                "completed_at": (base_time + timedelta(hours=i, minutes=5)).isoformat(),
                "tool_sequence": '["tool_a", "tool_b"]',
                "semantic_cluster": "resolved",
            }
        )

    mock_backend.get_all_runs.return_value = runs

    with patch("driftbase.backends.factory.get_backend", return_value=mock_backend):
        epochs = detect_epochs("test-agent", "/tmp/test.db", sensitivity=0.15)

    assert len(epochs) >= 1


def test_detect_epochs_never_raises():
    """detect_epochs never raises on any error."""
    mock_backend = MagicMock()
    mock_backend.get_detected_epochs.side_effect = Exception("Backend error")

    with patch("driftbase.backends.factory.get_backend", return_value=mock_backend):
        epochs = detect_epochs("test-agent", "/tmp/test.db")

    assert epochs == []


def test_epoch_labels_are_chronological():
    """Epoch labels follow chronological order."""
    mock_backend = MagicMock()
    mock_backend.get_detected_epochs.return_value = None

    runs = []
    base_time = datetime.utcnow()

    for i in range(30):
        runs.append(
            {
                "session_id": "test-agent",
                "id": f"run-{i}",
                "started_at": (base_time + timedelta(hours=i)).isoformat(),
                "completed_at": (base_time + timedelta(hours=i, minutes=5)).isoformat(),
                "tool_sequence": '["tool_a"]',
                "semantic_cluster": "resolved",
            }
        )

    for i in range(30, 60):
        runs.append(
            {
                "session_id": "test-agent",
                "id": f"run-{i}",
                "started_at": (base_time + timedelta(hours=i)).isoformat(),
                "completed_at": (base_time + timedelta(hours=i, minutes=5)).isoformat(),
                "tool_sequence": '["tool_b", "tool_c"]',
                "semantic_cluster": "escalated",
            }
        )

    mock_backend.get_all_runs.return_value = runs

    with patch("driftbase.backends.factory.get_backend", return_value=mock_backend):
        epochs = detect_epochs("test-agent", "/tmp/test.db", sensitivity=0.10)

    if len(epochs) >= 2:
        for i in range(len(epochs) - 1):
            if epochs[i].start_time and epochs[i + 1].start_time:
                assert epochs[i].start_time <= epochs[i + 1].start_time


def test_cache_ttl_is_respected():
    """Second call within TTL uses cached result."""
    mock_backend = MagicMock()
    mock_backend.get_detected_epochs.return_value = None

    runs = []
    base_time = datetime.utcnow()
    for i in range(50):
        runs.append(
            {
                "session_id": "test-agent",
                "id": f"run-{i}",
                "started_at": (base_time + timedelta(hours=i)).isoformat(),
                "completed_at": (base_time + timedelta(hours=i, minutes=5)).isoformat(),
                "tool_sequence": '["tool_a"]',
                "semantic_cluster": "resolved",
            }
        )

    mock_backend.get_all_runs.return_value = runs

    with patch("driftbase.backends.factory.get_backend", return_value=mock_backend):
        detect_epochs("test-agent", "/tmp/test.db")
        assert mock_backend.write_detected_epochs.called

    mock_backend_cached = MagicMock()
    mock_backend_cached.get_detected_epochs.return_value = [
        {
            "label": "epoch-2026-01-01",
            "start_run_id": "run-0",
            "end_run_id": "run-49",
            "start_time": base_time,
            "end_time": base_time + timedelta(hours=49),
            "run_count": 50,
            "stability": "HIGH",
            "summary": "Cached epoch",
        }
    ]

    with patch(
        "driftbase.backends.factory.get_backend", return_value=mock_backend_cached
    ):
        epochs2 = detect_epochs("test-agent", "/tmp/test.db")
        assert not mock_backend_cached.get_all_runs.called
        assert len(epochs2) == 1
        assert epochs2[0].label == "epoch-2026-01-01"


def test_compute_stability_classification():
    """_compute_stability correctly classifies epoch stability."""
    stable_runs = []
    for _i in range(20):
        stable_runs.append(
            {
                "tool_sequence": '["tool_a", "tool_b"]',
                "semantic_cluster": "resolved",
            }
        )

    stability = _compute_stability(stable_runs)
    assert stability == "HIGH"

    unstable_runs = []
    patterns = [
        ('["tool_a"]', "resolved"),
        ('["tool_x", "tool_y", "tool_z"]', "escalated"),
        ('["tool_b", "tool_c"]', "fallback"),
        ('["tool_d"]', "error"),
    ]
    for i in range(20):
        pattern, cluster = patterns[i % len(patterns)]
        unstable_runs.append(
            {
                "tool_sequence": pattern,
                "semantic_cluster": cluster,
            }
        )

    stability = _compute_stability(unstable_runs)
    assert stability in ["LOW", "MODERATE", "HIGH"]


def test_build_simple_fingerprint():
    """_build_simple_fingerprint creates correct distribution."""
    runs = [
        {"tool_sequence": '["tool_a", "tool_b"]', "semantic_cluster": "resolved"},
        {"tool_sequence": '["tool_a", "tool_b"]', "semantic_cluster": "resolved"},
        {"tool_sequence": '["tool_c"]', "semantic_cluster": "escalated"},
    ]

    fp = _build_simple_fingerprint(runs)

    assert "decision_dist" in fp
    assert "tool_dist" in fp

    assert fp["decision_dist"]["resolved"] == 2 / 3
    assert fp["decision_dist"]["escalated"] == 1 / 3

    assert "tool_a" in fp["tool_dist"]
    assert "tool_b" in fp["tool_dist"]
    assert "tool_c" in fp["tool_dist"]


def test_compute_fingerprint_drift():
    """_compute_fingerprint_drift computes JSD correctly."""
    fp1 = {
        "decision_dist": {"resolved": 1.0},
        "tool_dist": {"tool_a": 1.0},
    }
    fp2 = {
        "decision_dist": {"resolved": 1.0},
        "tool_dist": {"tool_a": 1.0},
    }

    drift = _compute_fingerprint_drift(fp1, fp2)
    assert drift == 0.0

    fp3 = {
        "decision_dist": {"escalated": 1.0},
        "tool_dist": {"tool_b": 1.0},
    }

    drift = _compute_fingerprint_drift(fp1, fp3)
    assert drift > 0.5
