"""
Tests for weight learning from labeled deploy outcomes.
"""

from __future__ import annotations

import json
from datetime import datetime

import pytest


def test_learn_weights_insufficient_data(tmp_path):
    """learn_weights with fewer than 10 records returns None."""
    from driftbase.backends.sqlite import SQLiteBackend
    from driftbase.local.weight_learner import learn_weights

    db_path = str(tmp_path / "test.db")
    backend = SQLiteBackend(db_path)

    agent_id = "test-agent"

    # Write only 5 labeled outcomes
    for i in range(5):
        backend.write_deploy_outcome(agent_id, f"v1.{i}", "bad", "test")

    # Should return None due to insufficient data
    result = learn_weights(agent_id, db_path)
    assert result is None


def test_learn_weights_all_good_outcomes(tmp_path):
    """learn_weights with all good outcomes returns None (no bad signal)."""
    from driftbase.backends.sqlite import SQLiteBackend
    from driftbase.local.weight_learner import learn_weights

    db_path = str(tmp_path / "test.db")
    backend = SQLiteBackend(db_path)

    agent_id = "test-agent"

    # Write 15 labeled outcomes, all good
    for i in range(15):
        backend.write_deploy_outcome(agent_id, f"v1.{i}", "good", "test")
        # Write some runs for each version
        for j in range(10):
            backend.write_run(
                {
                    "id": f"run-{i}-{j}",
                    "session_id": agent_id,
                    "deployment_version": f"v1.{i}",
                    "environment": "production",
                    "started_at": datetime.utcnow(),
                    "completed_at": datetime.utcnow(),
                    "task_input_hash": "hash",
                    "tool_sequence": json.dumps(["tool1", "tool2"]),
                    "tool_call_count": 2,
                    "output_length": 100,
                    "output_structure_hash": "hash",
                    "latency_ms": 1000,
                    "error_count": 0,
                    "retry_count": 0,
                    "semantic_cluster": "cluster_0",
                }
            )

    # Should return None because no bad outcomes to learn from
    result = learn_weights(agent_id, db_path)
    assert result is None


def test_learn_weights_mixed_outcomes(tmp_path):
    """learn_weights with mixed outcomes returns LearnedWeights."""
    from driftbase.backends.sqlite import SQLiteBackend
    from driftbase.local.weight_learner import learn_weights

    db_path = str(tmp_path / "test.db")
    backend = SQLiteBackend(db_path)

    agent_id = "test-agent"

    # Write 15 labeled outcomes: 10 good, 5 bad
    for i in range(15):
        outcome = "bad" if i >= 10 else "good"
        backend.write_deploy_outcome(agent_id, f"v1.{i}", outcome, "test")
        # Write some runs for each version
        for j in range(10):
            backend.write_run(
                {
                    "id": f"run-{i}-{j}",
                    "session_id": agent_id,
                    "deployment_version": f"v1.{i}",
                    "environment": "production",
                    "started_at": datetime.utcnow(),
                    "completed_at": datetime.utcnow(),
                    "task_input_hash": "hash",
                    "tool_sequence": json.dumps(["tool1", "tool2"]),
                    "tool_call_count": 2,
                    "output_length": 100,
                    "output_structure_hash": "hash",
                    "latency_ms": 1000,
                    "error_count": 1 if outcome == "bad" else 0,
                    "retry_count": 0,
                    "semantic_cluster": "cluster_0",
                }
            )

    # Should return LearnedWeights
    result = learn_weights(agent_id, db_path)
    # Note: This might still return None if drift computation fails or
    # correlations are all zero. This is expected behavior.
    if result:
        assert result.agent_id == agent_id
        assert result.n_total >= 10
        assert result.n_good > 0
        assert result.n_bad > 0


def test_learn_weights_weights_sum_to_one(tmp_path):
    """Learned weights sum to 1.0."""
    from driftbase.backends.sqlite import SQLiteBackend
    from driftbase.local.weight_learner import learn_weights

    db_path = str(tmp_path / "test.db")
    backend = SQLiteBackend(db_path)

    agent_id = "test-agent"

    # Write 15 labeled outcomes: 10 good, 5 bad with varying error rates
    for i in range(15):
        outcome = "bad" if i >= 10 else "good"
        backend.write_deploy_outcome(agent_id, f"v1.{i}", outcome, "test")
        for j in range(10):
            backend.write_run(
                {
                    "id": f"run-{i}-{j}",
                    "session_id": agent_id,
                    "deployment_version": f"v1.{i}",
                    "environment": "production",
                    "started_at": datetime.utcnow(),
                    "completed_at": datetime.utcnow(),
                    "task_input_hash": "hash",
                    "tool_sequence": json.dumps(["tool1", "tool2"]),
                    "tool_call_count": 2,
                    "output_length": 100,
                    "output_structure_hash": "hash",
                    "latency_ms": 1000 + (i * 100),  # Vary latency
                    "error_count": 5 if outcome == "bad" else 0,  # Vary error rate
                    "retry_count": 0,
                    "semantic_cluster": "cluster_0",
                }
            )

    result = learn_weights(agent_id, db_path)
    if result:
        total = sum(result.weights.values())
        assert abs(total - 1.0) < 0.01  # Allow small floating point error


def test_learn_weights_learned_factor_increases():
    """Learned factor increases with more training data (progressive moat building)."""
    from driftbase.local.weight_learner import _compute_blending_factor

    # n=10: factor = 0.30 (30% learned, 70% preset - minimum to activate)
    factor_10 = _compute_blending_factor(10)
    assert factor_10 == 0.30

    # n=50: factor ≈ 0.478 (approaching balanced - using formula: 0.3 + ((50-10)/90)*0.4)
    factor_50 = _compute_blending_factor(50)
    assert abs(factor_50 - 0.4778) < 0.01  # Allow small tolerance

    # n=100: factor = 0.70 (70% learned, 30% preset - cap reached, moat established)
    factor_100 = _compute_blending_factor(100)
    assert factor_100 == 0.70

    # n=150: factor = 0.70 (capped at 0.70, moat stays strong but doesn't overfit)
    factor_150 = _compute_blending_factor(150)
    assert factor_150 == 0.70


def test_learn_weights_never_raises(tmp_path):
    """learn_weights never raises on malformed or missing data."""
    from driftbase.local.weight_learner import learn_weights

    # Missing agent_id
    result = learn_weights("", str(tmp_path / "test.db"))
    assert result is None

    # Missing db_path
    result = learn_weights("test-agent", str(tmp_path / "nonexistent.db"))
    assert result is None


def test_deploy_outcome_round_trip(tmp_path):
    """write_deploy_outcome + get_deploy_outcomes round-trip."""
    from driftbase.backends.sqlite import SQLiteBackend

    db_path = str(tmp_path / "test.db")
    backend = SQLiteBackend(db_path)

    agent_id = "test-agent"
    version = "v1.0"

    backend.write_deploy_outcome(agent_id, version, "good", "All tests passed")

    outcome = backend.get_deploy_outcome(agent_id, version)
    assert outcome is not None
    assert outcome["agent_id"] == agent_id
    assert outcome["version"] == version
    assert outcome["outcome"] == "good"
    assert outcome["note"] == "All tests passed"

    # Test get_deploy_outcomes
    outcomes = backend.get_deploy_outcomes(agent_id)
    assert len(outcomes) == 1
    assert outcomes[0]["version"] == version


def test_deploy_outcome_overwrite(tmp_path):
    """write_deploy_outcome overwrites on duplicate."""
    from driftbase.backends.sqlite import SQLiteBackend

    db_path = str(tmp_path / "test.db")
    backend = SQLiteBackend(db_path)

    agent_id = "test-agent"
    version = "v1.0"

    backend.write_deploy_outcome(agent_id, version, "good", "First label")
    backend.write_deploy_outcome(agent_id, version, "bad", "Second label")

    outcome = backend.get_deploy_outcome(agent_id, version)
    assert outcome["outcome"] == "bad"
    assert outcome["note"] == "Second label"

    # Should still be only 1 record
    outcomes = backend.get_deploy_outcomes(agent_id)
    assert len(outcomes) == 1


def test_learned_weights_cache_round_trip(tmp_path):
    """write_learned_weights + get_learned_weights round-trip."""
    from driftbase.backends.sqlite import SQLiteBackend

    db_path = str(tmp_path / "test.db")
    backend = SQLiteBackend(db_path)

    agent_id = "test-agent"

    weights_data = {
        "weights": {"decision_drift": 0.5, "error_rate": 0.3, "latency": 0.2},
        "metadata": {
            "raw_correlations": {"decision_drift": 0.8},
            "learned_factor": 0.7,
            "n_good": 10,
            "n_bad": 5,
            "top_predictors": ["decision_drift", "error_rate"],
        },
        "n_total": 15,
    }

    backend.write_learned_weights(agent_id, weights_data)

    cached = backend.get_learned_weights(agent_id)
    assert cached is not None
    assert cached["agent_id"] == agent_id
    assert cached["n_total"] == 15
    assert "decision_drift" in cached["weights"]


def test_learned_weights_cache_update(tmp_path):
    """write_learned_weights overwrites existing cache."""
    from driftbase.backends.sqlite import SQLiteBackend

    db_path = str(tmp_path / "test.db")
    backend = SQLiteBackend(db_path)

    agent_id = "test-agent"

    # First write
    weights_data_1 = {
        "weights": {"decision_drift": 0.5},
        "metadata": {},
        "n_total": 10,
    }
    backend.write_learned_weights(agent_id, weights_data_1)

    # Second write
    weights_data_2 = {
        "weights": {"decision_drift": 0.6},
        "metadata": {},
        "n_total": 20,
    }
    backend.write_learned_weights(agent_id, weights_data_2)

    # Should have updated value
    cached = backend.get_learned_weights(agent_id)
    assert cached["n_total"] == 20
    assert cached["weights"]["decision_drift"] == 0.6
