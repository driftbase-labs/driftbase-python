"""Tests for connector infrastructure."""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from driftbase.connectors.base import ConnectorConfig, SyncResult
from driftbase.connectors.mapper import (
    compute_verbosity_ratio,
    extract_tool_sequence,
    infer_semantic_cluster,
)

# Check if optional connector packages are available
try:
    from driftbase.connectors.langfuse import LANGFUSE_AVAILABLE
except ImportError:
    LANGFUSE_AVAILABLE = False


def test_infer_semantic_cluster_error():
    """Semantic cluster inference identifies errors."""
    assert infer_semantic_cluster("some output", error=True) == "error"


def test_infer_semantic_cluster_escalated():
    """Semantic cluster inference identifies escalations."""
    assert infer_semantic_cluster("I need to escalate this", error=False) == "escalated"
    assert infer_semantic_cluster("Transfer to human agent", error=False) == "escalated"
    assert infer_semantic_cluster("Unable to help", error=False) == "escalated"


def test_infer_semantic_cluster_resolved():
    """Semantic cluster inference identifies resolved cases."""
    assert (
        infer_semantic_cluster("Task completed successfully", error=False) == "resolved"
    )
    assert infer_semantic_cluster("Here is your answer", error=False) == "resolved"


def test_infer_semantic_cluster_unknown():
    """Semantic cluster inference handles unknown cases."""
    assert infer_semantic_cluster(None, error=False) == "unknown"
    assert infer_semantic_cluster("", error=False) == "unknown"


def test_compute_verbosity_ratio():
    """Verbosity ratio computation."""
    assert compute_verbosity_ratio(100, 200) == 2.0
    assert compute_verbosity_ratio(100, 50) == 0.5
    assert compute_verbosity_ratio(0, 100) == 0.0
    assert compute_verbosity_ratio(100, 0) == 0.0


def test_extract_tool_sequence():
    """Tool sequence extraction from observations."""
    observations = [
        {"name": "tool_a"},
        {"name": "tool_b"},
        {"name": "tool_a"},
    ]
    tool_seq, count = extract_tool_sequence(observations)
    assert count == 3
    assert '["tool_a", "tool_b", "tool_a"]' in tool_seq


def test_extract_tool_sequence_with_function_format():
    """Tool sequence extraction handles different formats."""
    observations = [
        {"function": {"name": "tool_a"}},
        {"tool_name": "tool_b"},
        {"name": "tool_c"},
    ]
    tool_seq, count = extract_tool_sequence(observations)
    assert count == 3


def test_extract_tool_sequence_empty():
    """Tool sequence extraction handles empty input."""
    tool_seq, count = extract_tool_sequence([])
    assert count == 0
    assert tool_seq == "[]"


def test_connector_config_defaults():
    """ConnectorConfig has sensible defaults."""
    config = ConnectorConfig(project_name="test-project")
    assert config.project_name == "test-project"
    assert config.since is None
    assert config.limit == 500
    assert config.agent_id is None


def test_sync_result_success():
    """SyncResult tracks success state."""
    result = SyncResult(
        success=True, traces_fetched=10, runs_written=8, skipped=2, errors=[]
    )
    assert result.success is True
    assert result.traces_fetched == 10
    assert result.runs_written == 8
    assert result.skipped == 2
    assert len(result.errors) == 0


def test_sync_result_with_errors():
    """SyncResult can track errors."""
    result = SyncResult(
        success=False,
        traces_fetched=0,
        runs_written=0,
        skipped=0,
        errors=["API key invalid"],
    )
    assert result.success is False
    assert len(result.errors) == 1
    assert "API key invalid" in result.errors[0]


# Langfuse connector tests (with mocking)


@pytest.mark.skipif(not LANGFUSE_AVAILABLE, reason="langfuse extra not installed")
@patch("os.getenv")
def test_langfuse_connector_missing_api_keys(mock_getenv):
    """LangFuse connector requires both public and secret keys."""
    mock_getenv.side_effect = lambda key: None

    with pytest.raises(ValueError, match="LANGFUSE_PUBLIC_KEY"):
        from driftbase.connectors.langfuse import LangFuseConnector

        LangFuseConnector()


@pytest.mark.skipif(not LANGFUSE_AVAILABLE, reason="langfuse extra not installed")
@patch("driftbase.connectors.langfuse.Langfuse")
@patch("os.getenv")
def test_langfuse_validate_credentials_success(mock_getenv, mock_langfuse_class):
    """LangFuse credential validation succeeds with valid keys."""
    mock_getenv.side_effect = lambda key: {
        "LANGFUSE_PUBLIC_KEY": "pk-test",
        "LANGFUSE_SECRET_KEY": "sk-test",
        "LANGFUSE_HOST": "https://cloud.langfuse.com",
    }.get(key)

    mock_client = MagicMock()
    mock_client.get_traces.return_value = MagicMock(data=[])
    mock_langfuse_class.return_value = mock_client

    from driftbase.connectors.langfuse import LangFuseConnector

    connector = LangFuseConnector()
    assert connector.validate_credentials() is True


@pytest.mark.skipif(not LANGFUSE_AVAILABLE, reason="langfuse extra not installed")
@patch("driftbase.connectors.langfuse.Langfuse")
@patch("os.getenv")
def test_langfuse_map_trace_basic(mock_getenv, mock_langfuse_class):
    """LangFuse trace mapping produces valid Driftbase run."""
    mock_getenv.side_effect = lambda key: {
        "LANGFUSE_PUBLIC_KEY": "pk-test",
        "LANGFUSE_SECRET_KEY": "sk-test",
        "LANGFUSE_HOST": "https://cloud.langfuse.com",
    }.get(key)
    mock_langfuse_class.return_value = MagicMock()

    from driftbase.connectors.langfuse import LangFuseConnector

    connector = LangFuseConnector()
    config = ConnectorConfig(project_name="test-project")

    trace = {
        "id": "trace-456",
        "timestamp": "2026-03-01T10:00:00Z",
        "release": "v2.0",
        "output": "Task completed",
        "observations": [
            {
                "type": "generation",
                "name": "validate_input",
                "usage": {"input": 50, "output": 100},
            },
            {
                "type": "generation",
                "name": "process_request",
                "usage": {"input": 100, "output": 150},
            },
        ],
    }

    run = connector.map_trace(trace, config)

    assert run is not None
    assert run["external_id"] == "trace-456"
    assert run["source"] == "langfuse"
    assert run["deployment_version"] == "v2.0"
    assert run["prompt_tokens"] == 150
    assert run["completion_tokens"] == 250
    assert run["error_count"] == 0
    assert run["tool_call_count"] == 2
