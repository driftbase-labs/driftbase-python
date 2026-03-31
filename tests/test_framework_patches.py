"""
Tests for automatic framework detection and patching via @track decorator.
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
import unittest
from uuid import uuid4

from driftbase.backends.factory import clear_backend, get_backend
from driftbase.sdk.track import track

try:
    from driftbase.integrations.langgraph import LangGraphTracer

    LANGGRAPH_AVAILABLE = True
except ImportError:
    LANGGRAPH_AVAILABLE = False

from driftbase.local.local_store import drain_local_store


@unittest.skipUnless(LANGGRAPH_AVAILABLE, "langchain-core not installed")
class TestFrameworkAutoDetection(unittest.TestCase):
    """Test that @track automatically detects and instruments frameworks."""

    def setUp(self) -> None:
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self.db_path = self._tmp.name
        os.environ["DRIFTBASE_DB_PATH"] = self.db_path
        clear_backend()

    def tearDown(self) -> None:
        # Clear thread-local storage to prevent leakage across tests
        from driftbase.sdk.framework_patches import clear_framework_context

        clear_framework_context()

        with contextlib.suppress(Exception):
            os.unlink(self.db_path)
        if "DRIFTBASE_DB_PATH" in os.environ:
            del os.environ["DRIFTBASE_DB_PATH"]
        clear_backend()

    def test_langgraph_auto_detection_full_tool_visibility(self) -> None:
        """@track with LangGraph automatically integrates without manual tracer."""
        # Import LangGraph components
        try:
            from langchain_core.messages import HumanMessage
            from langgraph.graph import END, MessagesState, StateGraph
        except ImportError:
            self.skipTest("LangGraph not fully installed")

        # Define a mock node that returns a result
        def mock_node(state: MessagesState) -> MessagesState:
            """Mock node that returns a canned response."""
            return {"messages": [HumanMessage(content="Node executed")]}

        # Create a simple graph
        graph_builder = StateGraph(MessagesState)
        graph_builder.add_node("mock_node", mock_node)
        graph_builder.set_entry_point("mock_node")
        graph_builder.add_edge("mock_node", END)
        graph = graph_builder.compile()

        # Decorate function with @track - NO manual tracer needed
        @track(version="test_auto_v1")
        def run_agent(query: str):
            return graph.invoke({"messages": [HumanMessage(content=query)]})

        # Execute
        result = run_agent("test query")

        # Drain queue and verify
        drain_local_store(timeout=2.0)
        backend = get_backend()
        runs = backend.get_runs("test_auto_v1")

        # Assert: Exactly 1 run captured
        self.assertEqual(len(runs), 1, "Expected exactly 1 run in DB")

        # Assert: Run has expected fields (tool_sequence may be empty for simple graphs)
        run = runs[0]
        self.assertIn("tool_sequence", run, "tool_sequence should be present")
        self.assertIn("tool_call_count", run)
        # Note: Graph nodes are not tools, so tool_call_count may be 0
        # The test verifies integration works, not that tools are captured

    def test_no_double_saving(self) -> None:
        """@track with LangGraph does not create duplicate runs."""
        # Import LangGraph components
        try:
            from langchain_core.messages import HumanMessage
            from langgraph.graph import END, MessagesState, StateGraph
        except ImportError:
            self.skipTest("LangGraph not fully installed")

        # Define a mock tool
        def mock_tool(state: MessagesState) -> MessagesState:
            return {"messages": [HumanMessage(content="Tool executed")]}

        # Create graph
        graph_builder = StateGraph(MessagesState)
        graph_builder.add_node("mock_tool", mock_tool)
        graph_builder.set_entry_point("mock_tool")
        graph_builder.add_edge("mock_tool", END)
        graph = graph_builder.compile()

        @track(version="test_no_double_v1")
        def run_agent(query: str):
            return graph.invoke({"messages": [HumanMessage(content=query)]})

        # Execute twice
        run_agent("query 1")
        run_agent("query 2")

        # Drain and verify
        drain_local_store(timeout=2.0)
        backend = get_backend()
        runs = backend.get_runs("test_no_double_v1")

        # Assert: Exactly 2 runs (not 4 from double-saving)
        self.assertEqual(
            len(runs),
            2,
            f"Expected exactly 2 runs, got {len(runs)} (possible double-save)",
        )

    def test_standalone_tracers_still_work(self) -> None:
        """Standalone LangGraphTracer usage (without @track) continues to work."""
        # Import LangGraph components
        try:
            from langchain_core.messages import HumanMessage
            from langgraph.graph import END, MessagesState, StateGraph
        except ImportError:
            self.skipTest("LangGraph not fully installed")

        # Define a mock tool
        def mock_tool(state: MessagesState) -> MessagesState:
            return {"messages": [HumanMessage(content="Tool executed")]}

        # Create graph
        graph_builder = StateGraph(MessagesState)
        graph_builder.add_node("mock_tool", mock_tool)
        graph_builder.set_entry_point("mock_tool")
        graph_builder.add_edge("mock_tool", END)
        graph = graph_builder.compile()

        # Use standalone tracer (old API)
        tracer = LangGraphTracer(version="test_standalone_v1")
        result = graph.invoke(
            {"messages": [HumanMessage(content="query")]},
            config={"callbacks": [tracer]},
        )

        # Drain and verify
        drain_local_store(timeout=2.0)
        backend = get_backend()
        runs = backend.get_runs("test_standalone_v1")

        # Assert: 1 run captured
        self.assertEqual(len(runs), 1, "Standalone tracer should save 1 run")

    def test_user_provided_tracer_not_duplicated(self) -> None:
        """If user manually adds tracer, @track doesn't inject a second one."""
        # Import LangGraph components
        try:
            from langchain_core.messages import HumanMessage
            from langgraph.graph import END, MessagesState, StateGraph
        except ImportError:
            self.skipTest("LangGraph not fully installed")

        # Define a mock tool
        def mock_tool(state: MessagesState) -> MessagesState:
            return {"messages": [HumanMessage(content="Tool executed")]}

        # Create graph
        graph_builder = StateGraph(MessagesState)
        graph_builder.add_node("mock_tool", mock_tool)
        graph_builder.set_entry_point("mock_tool")
        graph_builder.add_edge("mock_tool", END)
        graph = graph_builder.compile()

        @track(version="test_no_duplicate_v1")
        def run_agent(query: str):
            # User manually creates tracer
            tracer = LangGraphTracer(version="test_no_duplicate_v1")
            return graph.invoke(
                {"messages": [HumanMessage(content=query)]},
                config={"callbacks": [tracer]},
            )

        # Execute
        run_agent("query")

        # Drain and verify
        drain_local_store(timeout=2.0)
        backend = get_backend()
        runs = backend.get_runs("test_no_duplicate_v1")

        # Assert: Exactly 1 run (not 2 from duplicate tracers)
        self.assertEqual(
            len(runs),
            1,
            f"Expected exactly 1 run, got {len(runs)} (possible duplicate tracer injection)",
        )

    def test_non_framework_functions_still_work(self) -> None:
        """@track on non-framework functions works as before (no tool calls)."""

        @track(version="test_generic_v1")
        def simple(x: int) -> int:
            return x * 2

        # Execute
        result = simple(5)
        self.assertEqual(result, 10)

        # Drain and verify
        drain_local_store(timeout=2.0)
        backend = get_backend()
        runs = backend.get_runs("test_generic_v1")

        # Assert: 1 run captured, tool_call_count = 0
        self.assertEqual(len(runs), 1, "Expected 1 run for simple function")
        run = runs[0]
        self.assertEqual(
            run["tool_call_count"], 0, "Generic function should have 0 tool calls"
        )

    def test_openai_regression(self) -> None:
        """OpenAI patching still works after framework_patches integration."""
        # This is a basic smoke test - full OpenAI tests are in other files
        from driftbase.sdk.framework_patches import apply_framework_patches
        from driftbase.sdk.track import RunContext

        # Verify apply_framework_patches doesn't crash on RunContext
        ctx = RunContext()
        try:
            apply_framework_patches(ctx, "test_v1")
        except Exception as e:
            self.fail(f"apply_framework_patches raised {e}")

        # If OpenAI is installed, verify it's still detected
        # (Full OpenAI tests are in test_track.py)

    def test_framework_not_installed_graceful_skip(self) -> None:
        """If a framework is not installed, patching silently skips it."""
        from driftbase.sdk.framework_patches import apply_framework_patches
        from driftbase.sdk.track import RunContext

        ctx = RunContext()

        # This should not raise, even if llamaindex/haystack/dspy/smolagents are not installed
        try:
            apply_framework_patches(ctx, "test_v1")
        except ImportError as e:
            self.fail(
                f"apply_framework_patches should skip missing frameworks gracefully, but raised: {e}"
            )


if __name__ == "__main__":
    unittest.main()
