"""
LangGraph explicit adapter for driftbase.

LangGraph uses the same callback system as LangChain, so this is an alias with
LangGraph-specific documentation.

Usage:
    from driftbase.integrations import LangGraphTracer

    tracer = LangGraphTracer(version='v1.0', agent_id='support-agent')
    result = graph.invoke(input, config={'callbacks': [tracer]})
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

# Try to import LangChain (LangGraph uses langchain_core callbacks)
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

    class LangGraphTracer(BaseCallbackHandler):
        """
        Explicit LangGraph tracer that captures tool calls, latency, token usage, and outcomes.

        LangGraph uses the same callback system as LangChain, so this tracer works identically
        to LangChainTracer but with LangGraph-specific documentation and naming.

        Args:
            version: Deployment version identifier (e.g., 'v1.0', 'baseline')
            agent_id: Optional agent identifier (defaults to auto-generated session ID)

        Example:
            >>> from driftbase.integrations import LangGraphTracer
            >>> tracer = LangGraphTracer(version='v1.0')
            >>> graph.invoke(input, config={'callbacks': [tracer]})
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
                f"LangGraphTracer initialized: version={self.deployment_version}, "
                f"agent_id={self.session_id}, env={self.environment}"
            )

        def on_chain_start(self, serialized: dict, inputs: dict, **kwargs: Any) -> None:
            """Called when a graph node starts."""
            run_id = kwargs.get("run_id")
            parent_run_id = kwargs.get("parent_run_id")
            name = serialized.get("name", "unknown")

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
                logger.debug(
                    f"[TRACER] ROOT chain_start: name={name}, run_id={srid[:8]}"
                )
            else:
                # Child run - link to root
                parent_srid = str(parent_run_id)
                root = self._run_to_root.get(parent_srid, srid)
                self._run_to_root[srid] = root
                logger.debug(
                    f"[TRACER] CHILD chain_start: name={name}, run_id={srid[:8]}, parent={parent_srid[:8]}, root={root[:8]}"
                )

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

            # FIX: Add tool's run_id to _run_to_root mapping so on_tool_end can find it
            if root is not None and run_id is not None:
                self._run_to_root[str(run_id)] = root

            # Extract tool name
            tool_name = None
            if "name" in serialized and serialized["name"]:
                tool_name = serialized["name"]
            if not tool_name and "name" in kwargs and kwargs["name"]:
                tool_name = kwargs["name"]
            if not tool_name:
                tool_name = "unknown_tool"

            logger.debug(
                f"[TRACER] tool_start: tool={tool_name}, run_id={str(run_id)[:8] if run_id else 'None'}, "
                f"parent={str(parent_run_id)[:8] if parent_run_id else 'None'}, root={root[:8] if root else 'None'}"
            )

            if root is None or root not in self.active_runs:
                logger.debug(
                    "[TRACER] tool_start: root not found or not in active_runs, skipping"
                )
                return

            state = self.active_runs[root]

            # Record start time for latency tracking
            state["tool_start_times"][tool_name] = time.perf_counter()
            if run_id is not None:
                state["tool_run_id_to_name"][str(run_id)] = tool_name

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
                logger.debug(
                    f"[TRACER] tool_end: run_id={str(run_id)[:8] if run_id else 'None'}, "
                    f"root not found or not in active_runs"
                )
                return

            state = self.active_runs[root]
            tool_name = state["tool_run_id_to_name"].get(
                str(run_id) if run_id is not None else "", "unknown_tool"
            )
            state["tool_sequence"].append(tool_name)
            logger.debug(f"[TRACER] tool_end: tool={tool_name}, root={root[:8]}")

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

            logger.warning(f"LangGraph tool error: {error}")

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
            """Called when a graph completes - save the run if it's a root graph."""
            run_id = kwargs.get("run_id")
            parent_run_id = kwargs.get("parent_run_id")

            if run_id is None:
                logger.debug("[TRACER] chain_end: run_id is None, skipping")
                return

            srid = str(run_id)
            has_messages = isinstance(outputs, dict) and "messages" in outputs
            in_active = srid in self.active_runs
            root_mapping = self._run_to_root.get(srid)
            is_root = root_mapping == srid
            has_no_parent = parent_run_id is None

            logger.debug(
                f"[TRACER] chain_end: run_id={srid[:8]}, "
                f"in_active={in_active}, root_mapping={root_mapping[:8] if root_mapping else None}, "
                f"is_root={is_root}, has_no_parent={has_no_parent}, has_messages={has_messages}"
            )

            if srid not in self.active_runs:
                logger.debug(
                    f"[TRACER] chain_end: run_id={srid[:8]} not in active_runs, skipping"
                )
                return

            # Root detection: a run is root if either:
            # 1. It maps to itself in _run_to_root (primary check)
            # 2. It has no parent_run_id AND is in active_runs (fallback for edge cases)
            is_root_run = (self._run_to_root.get(srid) == srid) or (
                parent_run_id is None and srid in self.active_runs
            )

            if not is_root_run:
                logger.debug(
                    f"[TRACER] chain_end: run_id={srid[:8]} is not root, skipping save"
                )
                return

            # Only save when we have messages (which indicates graph completion)
            if isinstance(outputs, dict) and "messages" in outputs:
                logger.info(f"[TRACER] *** SAVING RUN: run_id={srid[:8]} ***")
                self._save_run(srid, outputs)
                self.active_runs.pop(srid, None)
                # Clean up all mappings pointing to this root
                to_remove = [k for k, v in self._run_to_root.items() if v == srid]
                for k in to_remove:
                    self._run_to_root.pop(k, None)
                logger.debug(f"[TRACER] Cleaned up {len(to_remove)} mappings")
            else:
                logger.debug(
                    f"[TRACER] chain_end: run_id={srid[:8]} has no messages, skipping save"
                )

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
                "prompt_tokens": state.get("prompt_tokens", 0),
                "completion_tokens": state.get("completion_tokens", 0),
            }

            try:
                enqueue_run(payload)
                logger.info(
                    f"LangGraph run saved: tools={payload['tool_call_count']}, "
                    f"latency={latency_ms}ms, tokens={state['total_tokens']}, "
                    f"errors={state['error_count']}"
                )
            except Exception as e:
                _log_track_error("langgraph_tracer", f"Failed to save run: {e!r}")

else:
    # Stub when LangChain is not installed
    class LangGraphTracer:
        """Stub when LangChain is not installed."""

        def __init__(self, *args: Any, **kwargs: Any):
            raise ImportError(
                "LangGraphTracer requires langchain-core. "
                "Install with: pip install langchain-core"
            )
