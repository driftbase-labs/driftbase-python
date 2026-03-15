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
from driftbase.sdk.watcher import DriftbaseCallbackHandler


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
        """With LangGraph auto-detected, decorated function gets tool calls recorded."""
        import sys
        from uuid import uuid4

        import driftbase.sdk.watcher as watcher_module

        mock_graph = MagicMock()
        mock_graph.invoke.return_value = {"result": "ok"}

        # Create a mock handler that simulates DriftbaseCallbackHandler behavior
        def create_mock_handler(run_ctx=None, **kwargs):
            handler = MagicMock()
            handler.run_ctx = run_ctx
            handler.session_id = str(uuid4())
            handler.deployment_version = "unknown"
            handler.environment = "production"
            handler.active_runs = {}
            handler._run_to_root = {}
            if run_ctx is not None:
                # Inject tool call into context
                run_ctx.tool_calls.append({"name": "mock_tool", "latency_ms": 42})
            return handler

        # Mock both sys.modules and the handler creation
        mock_langchain = MagicMock()
        mock_langchain.callbacks.BaseCallbackHandler = object

        with (
            patch.dict(
                sys.modules,
                {
                    "langgraph": MagicMock(),
                    "langchain_core": mock_langchain,
                    "langchain_core.callbacks": mock_langchain.callbacks,
                },
            ),
            patch.object(watcher_module, "_LANGCHAIN_AVAILABLE", True),
            patch.object(
                watcher_module,
                "DriftbaseCallbackHandler",
                side_effect=create_mock_handler,
            ),
        ):
            # The 'langgraph' type hint string guarantees the auto-detector triggers perfectly
            @track(version="test_langgraph")
            def run_agent(
                state: "langgraph",  # type: ignore[name-defined]  # noqa: F821, UP037
                config=None,
            ):
                return mock_graph.invoke(state, config=config)

            run_agent("dummy_state")

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
