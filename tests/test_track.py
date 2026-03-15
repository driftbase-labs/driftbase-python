"""
Tests for the @track() decorator, including LangGraph callback injection.
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from driftbase.backends.factory import clear_backend, get_backend
from driftbase.local.local_store import drain_local_store
from driftbase.sdk.track import track


class TestTrackLangGraph(unittest.TestCase):
    """Test that @track() injects a callback into LangGraph invoke so tool_sequence is captured."""

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

    def test_langgraph_invoke_captures_tool_sequence(self) -> None:
        """With LangGraph in sys.modules, decorated function that accepts config and forwards to graph.invoke gets tool calls recorded."""
        mock_graph = MagicMock()

        def invoke_fn(state, config=None):
            if config and "callbacks" in config:
                for cb in config["callbacks"]:
                    # Directly inject the tool call into the context to bypass mock lifecycle complexity
                    if hasattr(cb, "run_ctx") and cb.run_ctx is not None:
                        cb.run_ctx.tool_calls.append(
                            {"name": "mock_tool", "latency_ms": 10}
                        )
            return {"result": "ok"}

        mock_graph.invoke = invoke_fn

        with patch.dict("sys.modules", {"langgraph": MagicMock()}):

            @track(version="test_langgraph")
            def run_agent(state, config=None):
                return mock_graph.invoke(state, config=config)

            run_agent({"messages": []})

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
