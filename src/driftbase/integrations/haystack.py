"""
Haystack (deepset) explicit adapter for driftbase.

Usage:
    from driftbase.integrations import HaystackTracer
    from haystack import Pipeline
    from haystack.tracing import enable_tracing

    tracer = HaystackTracer(version='v1.0', agent_id='rag-pipeline')
    enable_tracing(tracer)

    pipeline = Pipeline()
    # ... add components
    result = pipeline.run({"query": "What are GDPR requirements?"})
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import Any
from uuid import uuid4

from driftbase.local.local_store import _log_track_error, enqueue_run

logger = logging.getLogger(__name__)

# Try to import Haystack - fail only at instantiation time
try:
    from haystack.tracing import Span, Tracer

    _HAYSTACK_AVAILABLE = True
except ImportError:
    _HAYSTACK_AVAILABLE = False
    Tracer = object  # type: ignore[misc, assignment]
    Span = object  # type: ignore[misc, assignment]


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


if _HAYSTACK_AVAILABLE:

    class DriftbaseSpan(Span):
        """
        Custom span implementation for Haystack tracing.

        Accumulates component execution data (inputs, outputs, retrieved documents).
        """

        def __init__(
            self,
            operation_name: str,
            parent_tracer: HaystackTracer,
            tags: dict[str, Any] | None = None,
            parent_span: DriftbaseSpan | None = None,
        ):
            self.operation_name = operation_name
            self.parent_tracer = parent_tracer
            self.parent_span = parent_span
            self._tags: dict[str, Any] = tags or {}
            self.started_at = datetime.utcnow()
            self.is_root = parent_span is None

            logger.debug(f"Haystack span started: {operation_name}")

        def set_tag(self, key: str, value: Any) -> None:
            """
            Haystack calls this to attach component input/output data.

            We extract relevant data here and forward to the tracer.
            """
            self._tags[key] = value

            # Extract retrieved documents from retriever components
            if key == "output" and isinstance(value, dict):
                documents = value.get("documents")
                if documents and isinstance(documents, list):
                    self._process_retrieved_documents(documents)

            # Track embedder execution but discard vectors
            if key == "output" and "embedding" in str(value).lower():
                # Log that embedder ran, but don't store the vector array
                logger.debug(
                    f"Haystack embedder component executed: {self.operation_name}"
                )
                # Explicitly drop vector data before storage
                if isinstance(value, dict) and "embedding" in value:
                    # Replace vector array with metadata only
                    value_copy = value.copy()
                    embedding = value_copy.get("embedding")
                    if isinstance(embedding, list) and len(embedding) > 0:
                        value_copy["embedding"] = {
                            "type": "vector",
                            "dimensions": len(embedding),
                            "dropped": True,  # Signal that we intentionally discarded this
                        }
                    self._tags[key] = value_copy

        def get_tags(self) -> dict[str, Any]:
            """Return all accumulated tags."""
            return self._tags

        def _process_retrieved_documents(self, documents: list[Any]) -> None:
            """
            Extract metadata from retrieved documents.

            GDPR-compliant approach:
            - Hash document content instead of storing raw text
            - Keep metadata (source, score, etc.)
            - Optionally store full text if record_full_text=True
            """
            for doc in documents:
                try:
                    # Extract document data (Haystack Document object or dict)
                    if hasattr(doc, "content"):
                        content = doc.content
                        metadata = getattr(doc, "meta", {}) or {}
                        score = getattr(doc, "score", None)
                    elif isinstance(doc, dict):
                        content = doc.get("content", "")
                        metadata = doc.get("meta", {})
                        score = doc.get("score")
                    else:
                        continue

                    # GDPR compliance: Hash content by default
                    content_str = str(content) if content else ""
                    content_hash = hashlib.sha256(content_str.encode()).hexdigest()

                    doc_record = {
                        "content_hash": content_hash,
                        "content_length": len(content_str),
                        "score": float(score) if score is not None else None,
                        "metadata": metadata,
                    }

                    # Opt-in: Store full text if explicitly requested
                    if self.parent_tracer.record_full_text:
                        doc_record["content"] = content_str

                    self.parent_tracer.retrieved_chunks.append(doc_record)
                    logger.debug(
                        f"Haystack: Retrieved document (hash={content_hash[:12]}, "
                        f"score={score}, source={metadata.get('source', 'unknown')})"
                    )

                except Exception as e:
                    logger.warning(f"Failed to process retrieved document: {e}")

        def __enter__(self) -> DriftbaseSpan:
            """Enter span context."""
            self.parent_tracer._span_stack.append(self)
            return self

        def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
            """
            Exit span context.

            If this is the root span, trigger pipeline completion.
            """
            if (
                self.parent_tracer._span_stack
                and self.parent_tracer._span_stack[-1] == self
            ):
                self.parent_tracer._span_stack.pop()

            # Record component execution
            component_data = {
                "name": self.operation_name,
                "started_at": self.started_at.isoformat(),
                "completed_at": datetime.utcnow().isoformat(),
                "tags": self._tags,
            }

            # Track errors
            if exc_type is not None:
                self.parent_tracer.error_count += 1
                component_data["error"] = str(exc_val)
                logger.warning(
                    f"Haystack component failed: {self.operation_name} - {exc_val}"
                )

            self.parent_tracer.component_sequence.append(component_data)
            self.parent_tracer.tool_sequence.append(self.operation_name)

            # If this is the root span, save the run
            if self.is_root and not self.parent_tracer._span_stack:
                self.parent_tracer._save_run()

    class HaystackTracer(Tracer):
        """
        Explicit Haystack tracer for GDPR-compliant RAG monitoring.

        Captures pipeline execution with focus on retrieval auditability:
        - Component execution sequence
        - Retrieved document metadata (hashed content by default)
        - Filters and parameters
        - Latency and errors

        This provides complete traceability for on-premise RAG systems used by
        German and Dutch enterprises requiring data sovereignty.

        Args:
            version: Deployment version identifier (e.g., 'v1.0', 'baseline')
            agent_id: Optional agent identifier (defaults to auto-generated session ID)
            record_full_text: If True, store full document text (GDPR liability). Default: False

        Example:
            >>> from driftbase.integrations import HaystackTracer
            >>> from haystack import Pipeline
            >>> from haystack.tracing import enable_tracing
            >>>
            >>> tracer = HaystackTracer(version='v1.0')
            >>> enable_tracing(tracer)
            >>>
            >>> pipeline = Pipeline()
            >>> # ... add components (retriever, prompt builder, LLM, etc.)
            >>> result = pipeline.run({"query": "What are GDPR requirements?"})
        """

        def __init__(
            self,
            version: str,
            agent_id: str | None = None,
            record_full_text: bool = False,
        ):
            import os

            self.deployment_version = version
            self.environment = os.getenv("DRIFTBASE_ENVIRONMENT", "production")
            self.session_id = agent_id or str(uuid4())
            self.record_full_text = record_full_text

            # Pipeline execution state
            self.started_at = datetime.utcnow()
            self.component_sequence: list[dict[str, Any]] = []
            self.tool_sequence: list[str] = []
            self.retrieved_chunks: list[dict[str, Any]] = []
            self.error_count = 0
            self.task_input_hash = ""

            # Span management (for nested components)
            self._span_stack: list[DriftbaseSpan] = []

            if record_full_text:
                logger.warning(
                    "HaystackTracer: record_full_text=True - Raw document content will be stored. "
                    "This creates GDPR liability if handling personal data."
                )

            logger.info(
                f"HaystackTracer initialized: version={self.deployment_version}, "
                f"agent_id={self.session_id}, env={self.environment}, "
                f"record_full_text={record_full_text}"
            )

        @contextmanager
        def trace(
            self,
            operation_name: str,
            tags: dict[str, Any] | None = None,
            parent_span: DriftbaseSpan | None = None,
        ) -> Iterator[DriftbaseSpan]:
            """
            Context manager called by Haystack for each component execution.

            Yields a DriftbaseSpan that accumulates component data.
            """
            # Capture pipeline input from the first root span
            if not self.task_input_hash and tags:
                query = tags.get("input", {})
                if query:
                    self.task_input_hash = _hash_content(query)

            # Use the current span as parent if none specified
            if parent_span is None and self._span_stack:
                parent_span = self._span_stack[-1]

            span = DriftbaseSpan(operation_name, self, tags, parent_span)
            with span:
                yield span

        def current_span(self) -> DriftbaseSpan | None:
            """Return the current active span, or None if no span is active."""
            return self._span_stack[-1] if self._span_stack else None

        def _save_run(self) -> None:
            """
            Persist the pipeline run to local SQLite via enqueue_run.

            Called when the root span exits (pipeline completes).
            """
            try:
                completed_at = datetime.utcnow()
                latency_ms = int(
                    (completed_at - self.started_at).total_seconds() * 1000
                )

                # Compute output metrics
                output_length = sum(
                    chunk.get("content_length", 0) for chunk in self.retrieved_chunks
                )
                output_structure = {
                    "components": len(self.component_sequence),
                    "retrieved_docs": len(self.retrieved_chunks),
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
                    "output_length": output_length,
                    "output_structure_hash": output_structure_hash[:32],
                    "latency_ms": latency_ms,
                    "error_count": self.error_count,
                    "retry_count": 0,
                    "semantic_cluster": "error" if self.error_count > 0 else "resolved",
                }

                # GDPR-compliant RAG audit trail
                # Documents are hashed by default; full text only if opt-in
                payload["rag_audit_trail"] = json.dumps(
                    {
                        "component_sequence": [
                            {
                                "name": comp["name"],
                                "started_at": comp["started_at"],
                                "completed_at": comp["completed_at"],
                                "error": comp.get("error"),
                            }
                            for comp in self.component_sequence
                        ],
                        "retrieved_chunks": self.retrieved_chunks,
                        "retrieved_documents_count": len(self.retrieved_chunks),
                        "record_full_text": self.record_full_text,
                    }
                )

                enqueue_run(payload)
                logger.info(
                    f"Haystack run saved: components={len(self.component_sequence)}, "
                    f"retrieved_docs={len(self.retrieved_chunks)}, "
                    f"latency={latency_ms}ms, errors={self.error_count}"
                )

            except Exception as e:
                _log_track_error("haystack_tracer", f"Failed to save run: {e!r}")

else:
    # Stub when Haystack is not installed
    class HaystackTracer:
        """Stub when Haystack is not installed."""

        def __init__(self, *args: Any, **kwargs: Any):
            raise ImportError(
                "HaystackTracer requires haystack-ai. "
                "Install with: pip install haystack-ai"
            )
