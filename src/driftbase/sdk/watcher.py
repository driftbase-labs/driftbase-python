"""
LangChain/LangGraph callback handler and generic watcher for capturing agent behavioral metadata.

Provides:
- DriftbaseCallbackHandler: LangChain BaseCallbackHandler for framework integration
- DriftbaseWatcher: Generic decorator-based watcher for any function
"""

from __future__ import annotations

import functools
import hashlib
import json
import logging
import time
from datetime import datetime
from typing import Any, Callable, Optional
from uuid import uuid4

from driftbase.local.local_store import _log_track_error, enqueue_run

logger = logging.getLogger(__name__)

try:
    from langchain_core.callbacks import BaseCallbackHandler
    from langchain_core.outputs import LLMResult

    _LANGCHAIN_AVAILABLE = True
except ImportError:
    _LANGCHAIN_AVAILABLE = False
    BaseCallbackHandler = object  # type: ignore[misc, assignment]
    LLMResult = Any  # type: ignore[misc, assignment]


def _hash_content(content: Any) -> str:
    """Compute SHA-256 hash of content."""
    try:
        serialized = json.dumps(content, sort_keys=True, default=str)
    except Exception:
        serialized = repr(content)
    return hashlib.sha256(serialized.encode()).hexdigest()


def _compute_structure_hash(content: Any) -> str:
    """Compute hash of output structure (keys, types) without values."""
    if isinstance(content, dict):
        structure = {k: type(v).__name__ for k, v in content.items()}
    elif isinstance(content, list):
        structure = {"type": "list", "length": len(content)}
    elif isinstance(content, str):
        structure = {"type": "str", "length": len(content)}
    else:
        structure = {"type": type(content).__name__}
    return _hash_content(structure)


class DriftbaseWatcher:
    """Generic watcher for recording function execution behavioral metadata."""

    def __init__(
        self,
        deployment_version: str = "unknown",
        environment: Optional[str] = None,
    ):
        import os

        self.deployment_version = deployment_version
        self.environment = environment or os.getenv(
            "DRIFTBASE_ENVIRONMENT", "production"
        )
        self.session_id = str(uuid4())
        logger.info(
            f"DriftbaseWatcher initialized: version={self.deployment_version}, "
            f"env={self.environment}, session={self.session_id}"
        )

    def observe(self, func: Callable) -> Callable:
        """Decorator that observes function execution and records behavioral metadata."""
        import inspect

        if inspect.iscoroutinefunction(func):

            @functools.wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                return await self._observe_execution_async(func, args, kwargs)

            return async_wrapper
        else:

            @functools.wraps(func)
            def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                return self._observe_execution(func, args, kwargs)

            return sync_wrapper

    def _observe_execution(self, func: Callable, args: tuple, kwargs: dict) -> Any:
        """Internal method to observe synchronous function execution."""
        start_time = time.perf_counter()
        started_at = datetime.utcnow()
        error_count = 0
        result = None

        input_data = {"args": args, "kwargs": kwargs}
        task_input_hash = _hash_content(input_data)

        try:
            result = func(*args, **kwargs)
        except Exception as e:
            error_count = 1
            logger.warning(f"Error in observed function {func.__name__}: {e}")
            raise
        finally:
            end_time = time.perf_counter()
            completed_at = datetime.utcnow()
            latency_ms = int((end_time - start_time) * 1000)

            output_length = len(str(result)) if result is not None else 0
            output_structure_hash = _compute_structure_hash(result)

            payload = {
                "session_id": self.session_id,
                "deployment_version": self.deployment_version,
                "environment": self.environment,
                "started_at": started_at,
                "completed_at": completed_at,
                "task_input_hash": task_input_hash[:32],
                "tool_sequence": "[]",
                "tool_call_count": 0,
                "output_length": output_length,
                "output_structure_hash": output_structure_hash[:32],
                "latency_ms": latency_ms,
                "error_count": error_count,
                "retry_count": 0,
                "semantic_cluster": "resolved",
            }

            try:
                enqueue_run(payload)
            except Exception as e:
                _log_track_error("watcher_observe", f"Failed to enqueue run: {e!r}")

        return result

    async def _observe_execution_async(
        self, func: Callable, args: tuple, kwargs: dict
    ) -> Any:
        """Internal method to observe asynchronous function execution."""
        start_time = time.perf_counter()
        started_at = datetime.utcnow()
        error_count = 0
        result = None

        input_data = {"args": args, "kwargs": kwargs}
        task_input_hash = _hash_content(input_data)

        try:
            result = await func(*args, **kwargs)
        except Exception as e:
            error_count = 1
            logger.warning(f"Error in observed function {func.__name__}: {e}")
            raise
        finally:
            end_time = time.perf_counter()
            completed_at = datetime.utcnow()
            latency_ms = int((end_time - start_time) * 1000)

            output_length = len(str(result)) if result is not None else 0
            output_structure_hash = _compute_structure_hash(result)

            payload = {
                "session_id": self.session_id,
                "deployment_version": self.deployment_version,
                "environment": self.environment,
                "started_at": started_at,
                "completed_at": completed_at,
                "task_input_hash": task_input_hash[:32],
                "tool_sequence": "[]",
                "tool_call_count": 0,
                "output_length": output_length,
                "output_structure_hash": output_structure_hash[:32],
                "latency_ms": latency_ms,
                "error_count": error_count,
                "retry_count": 0,
                "semantic_cluster": "resolved",
            }

            try:
                enqueue_run(payload)
            except Exception as e:
                _log_track_error(
                    "watcher_observe_async", f"Failed to enqueue run: {e!r}"
                )

        return result


if _LANGCHAIN_AVAILABLE:

    class DriftbaseCallbackHandler(BaseCallbackHandler):
        """LangChain callback handler for capturing agent behavioral metadata.

        This handler tracks tool calls during LangChain/LangGraph agent execution
        and records behavioral fingerprints to local SQLite.

        When run_ctx is provided (e.g. from the @track() decorator), tool names
        are appended to run_ctx.tool_calls and the handler does not persist runs
        itself; the decorator builds and enqueues the payload.
        """

        def __init__(
            self,
            deployment_version: str = "unknown",
            environment: Optional[str] = None,
            run_ctx: Optional[Any] = None,
        ):
            super().__init__()
            import os

            self.run_ctx = run_ctx
            self.deployment_version = deployment_version
            self.environment = environment or os.getenv(
                "DRIFTBASE_ENVIRONMENT", "production"
            )
            self.session_id = str(uuid4())

            self.active_runs: dict[str, dict] = {}
            self._run_to_root: dict[str, str] = {}

            if run_ctx is None:
                logger.info(
                    f"DriftbaseCallbackHandler initialized: version={self.deployment_version}, "
                    f"env={self.environment}, session={self.session_id}"
                )

        def _extract_final_ai_content(self, output: Any) -> str:
            """Extract final AI message content from chain output."""
            messages = output.get("messages", []) if isinstance(output, dict) else []
            try:
                from langchain_core.messages import AIMessage

                for m in reversed(messages):
                    if isinstance(m, AIMessage):
                        content = m.content
                        return content if isinstance(content, str) else str(content)
            except Exception:
                pass
            return ""

        def on_chain_start(self, serialized: dict, inputs: dict, **kwargs: Any) -> None:
            """Called when a chain starts."""
            run_id = kwargs.get("run_id")
            parent_run_id = kwargs.get("parent_run_id")
            if run_id is None:
                return
            srid = str(run_id)
            if parent_run_id is None:
                self.active_runs[srid] = {
                    "started_at": datetime.utcnow(),
                    "run_id": str(uuid4()),
                    "task_input_hash": _hash_content(inputs),
                    "tool_sequence": [],
                    "tool_start_times": {},
                    "tool_run_id_to_name": {},
                    "error_count": 0,
                    "retry_count": 0,
                }
                self._run_to_root[srid] = srid
                logger.debug(f"Chain started: run_id={srid}")
            else:
                parent_srid = str(parent_run_id)
                self._run_to_root[srid] = self._run_to_root.get(parent_srid, srid)

        def on_tool_start(
            self, serialized: dict, input_str: str, **kwargs: Any
        ) -> None:
            """Called when a tool starts execution.

            BUG FIX: The tool name is extracted from multiple possible locations:
            1. serialized["name"] - standard LangChain format
            2. kwargs.get("name") - alternative format
            3. The last component of serialized["id"] list - fallback for structured tools
            """
            # Track mode: feed tool_calls to run_ctx for @track() decorator
            if self.run_ctx is not None:
                tool_name = None
                if "name" in serialized and serialized["name"]:
                    tool_name = serialized["name"]
                if not tool_name and "name" in kwargs and kwargs["name"]:
                    tool_name = kwargs["name"]
                if not tool_name:
                    tool_name = "unknown"
                    logger.warning(
                        "Could not extract tool name from serialized=%s, kwargs keys=%s",
                        serialized,
                        list(kwargs.keys()),
                    )
                self.run_ctx.tool_calls.append(
                    {
                        "name": tool_name,
                        "input_hash": _hash_content(input_str)[:16],
                    }
                )
                return

            run_id = kwargs.get("run_id")
            parent_run_id = kwargs.get("parent_run_id")
            root = None
            if parent_run_id is not None:
                root = self._run_to_root.get(str(parent_run_id))
            if root is None and run_id is not None:
                root = self._run_to_root.get(str(run_id))
            if root is None or root not in self.active_runs:
                return

            state = self.active_runs[root]

            # FIX: Extract tool name from multiple possible locations
            tool_name = None

            # Try serialized["name"] first (most common)
            if "name" in serialized and serialized["name"]:
                tool_name = serialized["name"]

            # Try kwargs["name"] as fallback
            if not tool_name and "name" in kwargs and kwargs["name"]:
                tool_name = kwargs["name"]

            # Try extracting from serialized["id"] list (e.g., ["langchain", "tools", "base", "StructuredTool"])
            # The actual tool name might be in a different location
            if (
                not tool_name
                and "id" in serialized
                and isinstance(serialized["id"], list)
            ):
                # Sometimes the tool name is the last component or in a "name" field elsewhere
                pass  # serialized["id"] contains class path, not tool name

            # Default to unknown_tool only if all extraction methods fail
            if not tool_name:
                tool_name = "unknown_tool"
                logger.warning(
                    f"Could not extract tool name from serialized={serialized}, kwargs keys={list(kwargs.keys())}"
                )

            state["tool_start_times"][tool_name] = time.perf_counter()
            if run_id is not None:
                state["tool_run_id_to_name"][str(run_id)] = tool_name
            logger.debug(f"Tool started: {tool_name}")

        def on_tool_end(self, output: str, **kwargs: Any) -> None:
            """Called when a tool completes successfully."""
            run_id = kwargs.get("run_id")
            parent_run_id = kwargs.get("parent_run_id")
            root = None
            if parent_run_id is not None:
                root = self._run_to_root.get(str(parent_run_id))
            if root is None and run_id is not None:
                root = self._run_to_root.get(str(run_id))
            if root is None or root not in self.active_runs:
                return
            state = self.active_runs[root]
            tool_name = state["tool_run_id_to_name"].get(
                str(run_id) if run_id is not None else "", "unknown_tool"
            )
            state["tool_sequence"].append(tool_name)
            logger.debug(f"Tool completed: {tool_name}")

        def on_tool_error(self, error: Exception, **kwargs: Any) -> None:
            """Called when a tool encounters an error."""
            run_id = kwargs.get("run_id")
            parent_run_id = kwargs.get("parent_run_id")
            root = None
            if parent_run_id is not None:
                root = self._run_to_root.get(str(parent_run_id))
            if root is None and run_id is not None:
                root = self._run_to_root.get(str(run_id))
            if root is not None and root in self.active_runs:
                self.active_runs[root]["error_count"] += 1
            tool_name = kwargs.get("name", "unknown_tool")
            logger.warning(f"Tool error in {tool_name}: {error}")

        def on_agent_action(self, action: Any, **kwargs: Any) -> None:
            """Called when an agent takes an action."""
            pass

        def on_agent_finish(self, finish: Any, **kwargs: Any) -> None:
            """Called when an agent finishes (legacy AgentExecutor only)."""
            pass

        def on_chain_end(self, outputs: dict, **kwargs: Any) -> None:
            """Called when a chain ends. Save only when top-level LangGraph agent ends."""
            if self.run_ctx is not None:
                return
            run_id = kwargs.get("run_id")
            if run_id is None:
                return
            srid = str(run_id)
            if srid not in self.active_runs:
                return
            if isinstance(outputs, dict) and "messages" in outputs:
                self._save_run(srid, outputs)
                self.active_runs.pop(srid, None)
                self._run_to_root.pop(srid, None)

        def _save_run(self, run_id_key: str, output: Any) -> None:
            """Persist the run to local SQLite."""
            state = self.active_runs.get(run_id_key)
            if state is None:
                return
            completed_at = datetime.utcnow()
            started_at = state["started_at"]
            latency_ms = int((completed_at - started_at).total_seconds() * 1000)
            output_length = len(str(output))
            output_structure_hash = _compute_structure_hash(output)

            response_text = self._extract_final_ai_content(output)
            cluster_id = "resolved"
            from driftbase.sdk.semantic import is_semantic_available

            if is_semantic_available():
                pass  # TODO: use embedding model for cluster_id when implemented

            payload = {
                "session_id": self.session_id,
                "deployment_version": self.deployment_version,
                "environment": self.environment,
                "started_at": started_at,
                "completed_at": completed_at,
                "task_input_hash": state["task_input_hash"][:32],
                "tool_sequence": json.dumps(state["tool_sequence"]),
                "tool_call_count": len(state["tool_sequence"]),
                "output_length": output_length,
                "output_structure_hash": output_structure_hash[:32],
                "latency_ms": latency_ms,
                "error_count": state["error_count"],
                "retry_count": state["retry_count"],
                "semantic_cluster": cluster_id,
            }

            try:
                enqueue_run(payload)
                logger.info(
                    f"AgentRun saved: tools={payload['tool_call_count']}, "
                    f"latency={latency_ms}ms, errors={state['error_count']}"
                )
            except Exception as e:
                _log_track_error("callback_handler", f"Failed to save run: {e!r}")

else:

    class DriftbaseCallbackHandler:
        """Stub when LangChain is not installed."""

        def __init__(self, *args: Any, **kwargs: Any):
            raise ImportError(
                "DriftbaseCallbackHandler requires langchain-core. "
                "Install with: pip install langchain-core"
            )
