"""
LlamaIndex explicit adapter for driftbase.

Usage:
    from driftbase.integrations import LlamaIndexTracer
    from llama_index.core.settings import Settings

    tracer = LlamaIndexTracer(version='v1.0', agent_id='rag-engine')
    Settings.callback_manager.add_handler(tracer)

    # Your LlamaIndex code runs normally
    response = query_engine.query("What is LlamaIndex?")
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from datetime import datetime
from typing import Any, Optional
from uuid import uuid4

from driftbase.local.local_store import _log_track_error, enqueue_run

logger = logging.getLogger(__name__)

# Try to import LlamaIndex - fail only at instantiation time
try:
    from llama_index.core.callbacks import BaseCallbackHandler, CBEventType

    _LLAMAINDEX_AVAILABLE = True
except ImportError:
    _LLAMAINDEX_AVAILABLE = False
    BaseCallbackHandler = object  # type: ignore[misc, assignment]
    CBEventType = None  # type: ignore[misc, assignment]


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


if _LLAMAINDEX_AVAILABLE:

    class LlamaIndexTracer(BaseCallbackHandler):
        """
        Explicit LlamaIndex tracer for RAG and agentic workflows.

        Captures comprehensive execution data:
        - Query events (user queries to the index)
        - Retrieval events (documents/nodes retrieved)
        - LLM events (generation calls with token usage)
        - Function/tool calls
        - Embedding operations
        - Synthesis operations

        This provides complete traceability for LlamaIndex-based RAG systems.

        Args:
            version: Deployment version identifier (e.g., 'v1.0', 'baseline')
            agent_id: Optional agent identifier (defaults to auto-generated session ID)

        Example:
            >>> from driftbase.integrations import LlamaIndexTracer
            >>> from llama_index.core import VectorStoreIndex, SimpleDirectoryReader
            >>> from llama_index.core.settings import Settings
            >>>
            >>> tracer = LlamaIndexTracer(version='v1.0')
            >>> Settings.callback_manager.add_handler(tracer)
            >>>
            >>> documents = SimpleDirectoryReader("data").load_data()
            >>> index = VectorStoreIndex.from_documents(documents)
            >>> query_engine = index.as_query_engine()
            >>> response = query_engine.query("What is LlamaIndex?")
        """

        def __init__(
            self,
            version: str,
            agent_id: Optional[str] = None,
        ):
            import os

            super().__init__(event_starts_to_ignore=[], event_ends_to_ignore=[])
            self.deployment_version = version
            self.environment = os.getenv("DRIFTBASE_ENVIRONMENT", "production")
            self.session_id = agent_id or str(uuid4())

            # Execution state
            self.started_at = datetime.utcnow()
            self.events: list[dict[str, Any]] = []
            self.tool_sequence: list[str] = []
            self.queries: list[str] = []
            self.retrieved_nodes: list[dict[str, Any]] = []
            self.error_count = 0
            self.task_input_hash = ""

            # Track active events (for matching start/end)
            self._active_events: dict[str, dict[str, Any]] = {}

            # LM metadata
            self.total_prompt_tokens = 0
            self.total_completion_tokens = 0
            self.llm_calls = 0

            logger.info(
                f"LlamaIndexTracer initialized: version={self.deployment_version}, "
                f"agent_id={self.session_id}, env={self.environment}"
            )

        def on_event_start(
            self,
            event_type: Any,
            payload: Optional[dict] = None,
            event_id: str = "",
            parent_id: str = "",
            **kwargs: Any,
        ) -> str:
            """
            Called when an event starts in LlamaIndex.

            Captures event metadata and starts timing.
            """
            try:
                payload = payload or {}

                # Capture query input from the first QUERY event
                if event_type == CBEventType.QUERY and not self.task_input_hash:
                    query_str = payload.get("query_str") or payload.get("query")
                    if query_str:
                        self.task_input_hash = _hash_content(query_str)
                        self.queries.append(str(query_str))

                # Record event start
                event_data = {
                    "event_id": event_id,
                    "event_type": str(event_type),
                    "parent_id": parent_id,
                    "payload": payload.copy(),
                    "started_at": datetime.utcnow(),
                    "start_time": time.perf_counter(),
                }

                self._active_events[event_id] = event_data

                logger.debug(f"LlamaIndex event started: {event_type} (id: {event_id})")

            except Exception as e:
                logger.debug(f"LlamaIndex tracer on_event_start error: {e}")

            return event_id or ""

        def on_event_end(
            self,
            event_type: Any,
            payload: Optional[dict] = None,
            event_id: str = "",
            **kwargs: Any,
        ) -> None:
            """
            Called when an event ends in LlamaIndex.

            Captures outputs, extracted metadata, and timing.
            """
            try:
                payload = payload or {}

                if event_id not in self._active_events:
                    return

                event_data = self._active_events.pop(event_id)
                end_time = time.perf_counter()
                latency_ms = int((end_time - event_data["start_time"]) * 1000)

                # Extract event-specific metadata
                event_metadata = self._extract_event_metadata(event_type, payload)

                # Build event record
                event_record = {
                    "event_type": str(event_type),
                    "event_id": event_id,
                    "parent_id": event_data.get("parent_id"),
                    "latency_ms": latency_ms,
                    "started_at": event_data["started_at"].isoformat(),
                    "completed_at": datetime.utcnow().isoformat(),
                    "metadata": event_metadata,
                }

                self.events.append(event_record)

                # Update tool sequence for recognizable operations
                operation_name = self._get_operation_name(event_type)
                if operation_name:
                    self.tool_sequence.append(operation_name)

                logger.debug(
                    f"LlamaIndex event completed: {event_type} ({latency_ms}ms)"
                )

            except Exception as e:
                logger.debug(f"LlamaIndex tracer on_event_end error: {e}")

        def start_trace(self, trace_id: Optional[str] = None) -> None:
            """Called when a trace starts (root-level operation)."""
            self.started_at = datetime.utcnow()
            logger.debug(f"LlamaIndex trace started: {trace_id}")

        def end_trace(
            self,
            trace_id: Optional[str] = None,
            trace_map: Optional[dict] = None,
        ) -> None:
            """
            Called when a trace ends (root-level operation completes).

            Triggers save to database.
            """
            try:
                logger.debug(f"LlamaIndex trace ended: {trace_id}")
                self._save_run()
            except Exception as e:
                logger.warning(f"LlamaIndex tracer end_trace error: {e}")
                _log_track_error("llamaindex_tracer", f"end_trace error: {e!r}")

        def _extract_event_metadata(
            self, event_type: Any, payload: dict[str, Any]
        ) -> dict[str, Any]:
            """
            Extract relevant metadata from event payloads.

            Different event types expose different metadata.
            """
            metadata: dict[str, Any] = {}

            try:
                # FUNCTION_CALL - capture tool/function invocations
                if event_type == CBEventType.FUNCTION_CALL:
                    name = (
                        payload.get("function_call") or payload.get("name") or "unknown"
                    )
                    if isinstance(name, dict):
                        name = name.get("name", "unknown")
                    metadata["function_name"] = str(name)

                # RETRIEVE - capture retrieved nodes/documents
                elif event_type == CBEventType.RETRIEVE:
                    nodes = payload.get("nodes") or payload.get("retrieved_nodes")
                    if nodes and isinstance(nodes, list):
                        metadata["retrieved_count"] = len(nodes)
                        # Extract node metadata (hash content for GDPR)
                        for node in nodes[:10]:  # Limit to first 10 for performance
                            node_record = self._process_retrieved_node(node)
                            if node_record:
                                self.retrieved_nodes.append(node_record)

                # LLM - capture model and token usage
                elif event_type == CBEventType.LLM:
                    self.llm_calls += 1

                    # Extract model name
                    model = payload.get("model") or payload.get("model_name")
                    if model:
                        metadata["model"] = str(model)

                    # Extract token usage
                    if "response" in payload:
                        response = payload["response"]
                        if hasattr(response, "raw"):
                            raw = response.raw
                            if hasattr(raw, "usage"):
                                usage = raw.usage
                                prompt_tokens = getattr(usage, "prompt_tokens", 0)
                                completion_tokens = getattr(
                                    usage, "completion_tokens", 0
                                )
                                metadata["prompt_tokens"] = prompt_tokens
                                metadata["completion_tokens"] = completion_tokens
                                self.total_prompt_tokens += prompt_tokens
                                self.total_completion_tokens += completion_tokens

                # EMBEDDING - capture embedding operations
                elif event_type == CBEventType.EMBEDDING:
                    chunks = payload.get("chunks") or payload.get("texts")
                    if chunks:
                        metadata["chunk_count"] = (
                            len(chunks) if isinstance(chunks, list) else 1
                        )

                # QUERY - capture query metadata
                elif event_type == CBEventType.QUERY:
                    query_str = payload.get("query_str") or payload.get("query")
                    if query_str:
                        metadata["query_length"] = len(str(query_str))

                # SYNTHESIZE - capture synthesis operations
                elif event_type == CBEventType.SYNTHESIZE:
                    metadata["synthesis"] = True

            except Exception as e:
                logger.debug(f"Failed to extract event metadata: {e}")

            return metadata

        def _process_retrieved_node(self, node: Any) -> Optional[dict[str, Any]]:
            """
            Process a retrieved node from LlamaIndex.

            Hashes content for GDPR compliance (similar to Haystack approach).
            """
            try:
                # Extract node data
                if hasattr(node, "get_content"):
                    content = node.get_content()
                elif hasattr(node, "text"):
                    content = node.text
                elif isinstance(node, dict):
                    content = node.get("text") or node.get("content", "")
                else:
                    return None

                # Extract metadata
                node_metadata = {}
                if hasattr(node, "metadata"):
                    node_metadata = node.metadata
                elif isinstance(node, dict):
                    node_metadata = node.get("metadata", {})

                # Extract score
                score = None
                if hasattr(node, "score"):
                    score = node.score
                elif isinstance(node, dict):
                    score = node.get("score")

                # GDPR: Hash content instead of storing raw text
                content_str = str(content) if content else ""
                content_hash = hashlib.sha256(content_str.encode()).hexdigest()

                return {
                    "content_hash": content_hash,
                    "content_length": len(content_str),
                    "score": float(score) if score is not None else None,
                    "metadata": node_metadata,
                }

            except Exception as e:
                logger.debug(f"Failed to process retrieved node: {e}")
                return None

        def _get_operation_name(self, event_type: Any) -> Optional[str]:
            """Map LlamaIndex event types to readable operation names."""
            try:
                event_type_str = str(event_type)

                # Map common event types to operation names
                if "QUERY" in event_type_str:
                    return "query"
                elif "RETRIEVE" in event_type_str:
                    return "retrieve"
                elif "LLM" in event_type_str:
                    return "llm"
                elif "EMBEDDING" in event_type_str:
                    return "embedding"
                elif "SYNTHESIZE" in event_type_str:
                    return "synthesize"
                elif "FUNCTION_CALL" in event_type_str:
                    return "function_call"

                return None

            except Exception:
                return None

        def _save_run(self) -> None:
            """
            Persist the LlamaIndex run to local SQLite via enqueue_run.

            Called when the trace ends (operation completes).
            """
            try:
                completed_at = datetime.utcnow()
                latency_ms = int(
                    (completed_at - self.started_at).total_seconds() * 1000
                )

                # Compute output metrics
                total_output_length = sum(
                    node.get("content_length", 0) for node in self.retrieved_nodes
                )
                output_structure = {
                    "events": len(self.events),
                    "retrieved_nodes": len(self.retrieved_nodes),
                    "llm_calls": self.llm_calls,
                }
                output_structure_hash = _compute_structure_hash(output_structure)

                # Build the standard payload
                payload = {
                    "session_id": self.session_id,
                    "deployment_version": self.deployment_version,
                    "environment": self.environment,
                    "started_at": self.started_at,
                    "completed_at": completed_at,
                    "task_input_hash": self.task_input_hash[:32]
                    if self.task_input_hash
                    else "none",
                    "tool_sequence": json.dumps(self.tool_sequence),
                    "tool_call_count": len(self.tool_sequence),
                    "output_length": total_output_length,
                    "output_structure_hash": output_structure_hash[:32],
                    "latency_ms": latency_ms,
                    "error_count": self.error_count,
                    "retry_count": 0,
                    "semantic_cluster": "error" if self.error_count > 0 else "resolved",
                    "prompt_tokens": self.total_prompt_tokens,
                    "completion_tokens": self.total_completion_tokens,
                }

                # LlamaIndex-specific audit trail
                payload["llamaindex_audit_trail"] = json.dumps(
                    {
                        "events": [
                            {
                                "event_type": event["event_type"],
                                "latency_ms": event["latency_ms"],
                                "metadata": event["metadata"],
                            }
                            for event in self.events
                        ],
                        "queries": self.queries,
                        "retrieved_nodes": self.retrieved_nodes,
                        "llm_calls": self.llm_calls,
                        "total_prompt_tokens": self.total_prompt_tokens,
                        "total_completion_tokens": self.total_completion_tokens,
                    }
                )

                enqueue_run(payload)
                logger.info(
                    f"LlamaIndex run saved: events={len(self.events)}, "
                    f"retrieved_nodes={len(self.retrieved_nodes)}, "
                    f"llm_calls={self.llm_calls}, "
                    f"tokens={self.total_prompt_tokens + self.total_completion_tokens}, "
                    f"latency={latency_ms}ms, errors={self.error_count}"
                )

            except Exception as e:
                _log_track_error("llamaindex_tracer", f"Failed to save run: {e!r}")

else:
    # Stub when LlamaIndex is not installed
    class LlamaIndexTracer:
        """Stub when LlamaIndex is not installed."""

        def __init__(self, *args: Any, **kwargs: Any):
            raise ImportError(
                "LlamaIndexTracer requires llama-index. "
                "Install with: pip install llama-index"
            )
