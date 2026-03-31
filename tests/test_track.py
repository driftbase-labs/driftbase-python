"""
Tests for LangGraph tracer integration.
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
import unittest
from uuid import uuid4

from driftbase.backends.factory import clear_backend, get_backend
from driftbase.integrations.langgraph import LangGraphTracer
from driftbase.local.local_store import drain_local_store


class TestTrackLangGraph(unittest.TestCase):
    """Test that LangGraphTracer captures tool calls correctly."""

    def setUp(self) -> None:
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self.db_path = self._tmp.name
        os.environ["DRIFTBASE_DB_PATH"] = self.db_path
        clear_backend()

    def tearDown(self) -> None:
        with contextlib.suppress(Exception):
            os.unlink(self.db_path)
        if "DRIFTBASE_DB_PATH" in os.environ:
            del os.environ["DRIFTBASE_DB_PATH"]
        clear_backend()

    def test_langgraph_tracer_captures_tool_sequence(self) -> None:
        """LangGraphTracer correctly captures tool calls and writes run to backend."""
        # Create tracer
        tracer = LangGraphTracer(version="test_v1")

        # Generate IDs for the callback chain
        root_run_id = uuid4()
        tool_run_id = uuid4()

        # Simulate callback chain: chain_start (root) -> tool_start -> tool_end -> chain_end
        tracer.on_chain_start(
            serialized={"name": "test_graph"},
            inputs={"query": "test input"},
            run_id=root_run_id,
            parent_run_id=None,
        )

        tracer.on_tool_start(
            serialized={"name": "mock_tool"},
            input_str="tool input",
            run_id=tool_run_id,
            parent_run_id=root_run_id,
        )

        tracer.on_tool_end(
            output="tool output",
            run_id=tool_run_id,
            parent_run_id=root_run_id,
        )

        tracer.on_chain_end(
            outputs={"messages": ["done"]},
            run_id=root_run_id,
            parent_run_id=None,
        )

        # Drain queue and verify run was written
        drain_local_store(timeout=2.0)
        backend = get_backend()
        last = backend.get_last_run()

        self.assertIsNotNone(last, "expected one run to be written")

        tool_sequence = last.get("tool_sequence") or "[]"
        tools = json.loads(tool_sequence)

        self.assertIsInstance(tools, list)
        self.assertIn(
            "mock_tool", tools, f"tool_sequence should contain 'mock_tool', got {tools}"
        )


if __name__ == "__main__":
    unittest.main()
