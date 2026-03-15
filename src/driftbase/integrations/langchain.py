"""
LangChain explicit adapter for driftbase.

Usage:
    from driftbase.integrations import LangChainTracer

    tracer = LangChainTracer(version='v1.0', agent_id='customer-support')
    result = chain.invoke(input, config={'callbacks': [tracer]})
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from datetime import datetime
from typing import Any
from uuid import uuid4

from driftbase.local.local_store import _log_track_error, enqueue_run

logger = logging.getLogger(__name__)

# Try to import LangChain - fail only at instantiation time
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


if _LANGCHAIN_AVAILABLE:

    class LangChainTracer(BaseCallbackHandler):
        """
        Explicit LangChain tracer that captures tool calls, latency, token usage, and outcomes.

        This is a guaranteed fallback when auto-detection fails - the developer imports it
        directly and passes it to LangChain.

        Args:
            version: Deployment version identifier (e.g., 'v1.0', 'baseline')
            agent_id: Optional agent identifier (defaults to auto-generated session ID)

        Example:
            >>> from driftbase.integrations import LangChainTracer
            >>> tracer = LangChainTracer(version='v1.0')
            >>> chain.invoke(input, config={'callbacks': [tracer]})
        """

        def __init__(
            self,
            version: str,
            agent_id: str | None = None,
        ):
            super().__init__()
            import os

            self.deployment_version = version
            self.environment = os.getenv("DRIFTBASE_ENVIRONMENT", "production")
            self.session_id = agent_id or str(uuid4())

            # Track active runs
            self.active_runs: dict[str, dict] = {}
            self._run_to_root: dict[str, str] = {}

            # Track token usage per run
            self.token_usage: dict[str, dict] = {}

            logger.info(
                f"LangChainTracer initialized: version={self.deployment_version}, "
                f"agent_id={self.session_id}, env={self.environment}"
            )

        def on_chain_start(self, serialized: dict, inputs: dict, **kwargs: Any) -> None:
            """Called when a chain starts."""
            run_id = kwargs.get("run_id")
            parent_run_id = kwargs.get("parent_run_id")
            if run_id is None:
                return

            srid = str(run_id)

            if parent_run_id is None:
                # Root run
                self.active_runs[srid] = {
                    "started_at": datetime.utcnow(),
                    "task_input_hash": _hash_content(inputs),
                    "tool_sequence": [],
                    "tool_start_times": {},
                    "tool_run_id_to_name": {},
                    "error_count": 0,
                    "retry_count": 0,
                    "total_tokens": 0,
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                }
                self._run_to_root[srid] = srid
                logger.debug(f"LangChain chain started: run_id={srid}")
            else:
                # Child run - link to root
                parent_srid = str(parent_run_id)
                self._run_to_root[srid] = self._run_to_root.get(parent_srid, srid)

        def on_tool_start(
            self, serialized: dict, input_str: str, **kwargs: Any
        ) -> None:
            """Called when a tool starts execution."""
            run_id = kwargs.get("run_id")
            parent_run_id = kwargs.get("parent_run_id")

            # Find root run
            root = None
            if parent_run_id is not None:
                root = self._run_to_root.get(str(parent_run_id))
            if root is None and run_id is not None:
                root = self._run_to_root.get(str(run_id))
            if root is None or root not in self.active_runs:
                return

            state = self.active_runs[root]

            # Extract tool name
            tool_name = None
            if "name" in serialized and serialized["name"]:
                tool_name = serialized["name"]
            if not tool_name and "name" in kwargs and kwargs["name"]:
                tool_name = kwargs["name"]
            if not tool_name:
                tool_name = "unknown_tool"
                logger.warning(
                    f"Could not extract tool name from serialized={serialized}"
                )

            # Record start time for latency tracking
            state["tool_start_times"][tool_name] = time.perf_counter()
            if run_id is not None:
                state["tool_run_id_to_name"][str(run_id)] = tool_name

            logger.debug(f"LangChain tool started: {tool_name}")

        def on_tool_end(self, output: str, **kwargs: Any) -> None:
            """Called when a tool completes successfully."""
            run_id = kwargs.get("run_id")
            parent_run_id = kwargs.get("parent_run_id")

            # Find root run
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
            logger.debug(f"LangChain tool completed: {tool_name}")

        def on_tool_error(self, error: Exception, **kwargs: Any) -> None:
            """Called when a tool encounters an error."""
            run_id = kwargs.get("run_id")
            parent_run_id = kwargs.get("parent_run_id")

            # Find root run
            root = None
            if parent_run_id is not None:
                root = self._run_to_root.get(str(parent_run_id))
            if root is None and run_id is not None:
                root = self._run_to_root.get(str(run_id))

            if root is not None and root in self.active_runs:
                self.active_runs[root]["error_count"] += 1

            logger.warning(f"LangChain tool error: {error}")

        def on_llm_start(
            self, serialized: dict, prompts: list[str], **kwargs: Any
        ) -> None:
            """Called when an LLM starts."""
            pass  # Track token usage in on_llm_end

        def on_llm_end(self, response: LLMResult, **kwargs: Any) -> None:
            """Called when an LLM completes - capture token usage."""
            run_id = kwargs.get("run_id")
            parent_run_id = kwargs.get("parent_run_id")

            # Find root run
            root = None
            if parent_run_id is not None:
                root = self._run_to_root.get(str(parent_run_id))
            if root is None and run_id is not None:
                root = self._run_to_root.get(str(run_id))
            if root is None or root not in self.active_runs:
                return

            state = self.active_runs[root]

            # Extract token usage from LLM response
            if hasattr(response, "llm_output") and response.llm_output:
                token_usage = response.llm_output.get("token_usage", {})
                if token_usage:
                    state["total_tokens"] += token_usage.get("total_tokens", 0)
                    state["prompt_tokens"] += token_usage.get("prompt_tokens", 0)
                    state["completion_tokens"] += token_usage.get(
                        "completion_tokens", 0
                    )

        def on_chain_end(self, outputs: dict, **kwargs: Any) -> None:
            """Called when a chain ends - save the run if it's a root chain."""
            run_id = kwargs.get("run_id")
            if run_id is None:
                return

            srid = str(run_id)
            if srid not in self.active_runs:
                return

            # Only save root-level chains
            if isinstance(outputs, dict) and "messages" in outputs:
                self._save_run(srid, outputs)
                self.active_runs.pop(srid, None)
                self._run_to_root.pop(srid, None)

        def _save_run(self, run_id_key: str, output: Any) -> None:
            """Persist the run to local SQLite via enqueue_run."""
            state = self.active_runs.get(run_id_key)
            if state is None:
                return

            completed_at = datetime.utcnow()
            started_at = state["started_at"]
            latency_ms = int((completed_at - started_at).total_seconds() * 1000)
            output_length = len(str(output))
            output_structure_hash = _compute_structure_hash(output)

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
                "semantic_cluster": "resolved",
            }

            try:
                enqueue_run(payload)
                logger.info(
                    f"LangChain run saved: tools={payload['tool_call_count']}, "
                    f"latency={latency_ms}ms, tokens={state['total_tokens']}, "
                    f"errors={state['error_count']}"
                )
            except Exception as e:
                _log_track_error("langchain_tracer", f"Failed to save run: {e!r}")

else:
    # Stub when LangChain is not installed
    class LangChainTracer:
        """Stub when LangChain is not installed."""

        def __init__(self, *args: Any, **kwargs: Any):
            raise ImportError(
                "LangChainTracer requires langchain-core. "
                "Install with: pip install langchain-core"
            )
