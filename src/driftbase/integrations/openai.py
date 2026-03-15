"""
OpenAI explicit adapter for driftbase.

Usage:
    from driftbase.integrations import OpenAITracer
    from openai import OpenAI

    client = OpenAI()
    with OpenAITracer(version='v1.0'):
        response = client.chat.completions.create(
            model="gpt-4",
            messages=[{"role": "user", "content": "Hello"}]
        )
"""

from __future__ import annotations

import functools
import hashlib
import json
import logging
import time
from datetime import datetime
from typing import Any, Optional
from uuid import uuid4

from driftbase.local.local_store import _log_track_error, enqueue_run

logger = logging.getLogger(__name__)

# Try to import OpenAI - fail only at instantiation time
try:
    import openai

    _OPENAI_AVAILABLE = True
except ImportError:
    _OPENAI_AVAILABLE = False
    openai = None  # type: ignore[assignment]


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


if _OPENAI_AVAILABLE:

    class OpenAITracer:
        """
        Explicit OpenAI tracer that monkey-patches openai.chat.completions.create.

        This is a context manager that intercepts OpenAI calls and captures:
        - Model name
        - Tool calls
        - Token usage
        - Latency

        Args:
            version: Deployment version identifier (e.g., 'v1.0', 'baseline')
            agent_id: Optional agent identifier (defaults to auto-generated session ID)

        Example:
            >>> from driftbase.integrations import OpenAITracer
            >>> from openai import OpenAI
            >>>
            >>> client = OpenAI()
            >>> with OpenAITracer(version='v1.0'):
            ...     response = client.chat.completions.create(
            ...         model="gpt-4",
            ...         messages=[{"role": "user", "content": "Hello"}]
            ...     )
        """

        def __init__(
            self,
            version: str,
            agent_id: Optional[str] = None,
        ):
            import os

            self.deployment_version = version
            self.environment = os.getenv("DRIFTBASE_ENVIRONMENT", "production")
            self.session_id = agent_id or str(uuid4())

            self.original_create = None
            self._patched = False

            logger.info(
                f"OpenAITracer initialized: version={self.deployment_version}, "
                f"agent_id={self.session_id}, env={self.environment}"
            )

        def __enter__(self):
            """Enter context manager - patch openai.chat.completions.create."""
            try:
                # Store the original method
                self.original_create = (
                    openai.resources.chat.completions.Completions.create
                )

                # Create the patched method
                @functools.wraps(self.original_create)
                def patched_create(completions_self, *args, **kwargs):
                    return self._traced_create(completions_self, *args, **kwargs)

                # Apply the patch
                openai.resources.chat.completions.Completions.create = patched_create
                self._patched = True
                logger.debug("OpenAI client patched")
            except AttributeError as e:
                logger.warning(f"Failed to patch OpenAI client: {e}")

            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            """Exit context manager - restore original method."""
            if self._patched and self.original_create is not None:
                openai.resources.chat.completions.Completions.create = (
                    self.original_create
                )
                self._patched = False
                logger.debug("OpenAI client unpatched")
            return False

        def _traced_create(self, completions_self, *args, **kwargs):
            """Wrapped version of openai.chat.completions.create that tracks calls."""
            started_at = datetime.utcnow()
            start_time = time.perf_counter()
            error_count = 0
            response = None

            # Extract messages for input hash
            messages = kwargs.get("messages", [])
            task_input_hash = _hash_content(messages)

            # Extract model
            model = kwargs.get("model", "unknown")

            try:
                # Call the original method
                response = self.original_create(completions_self, *args, **kwargs)
            except Exception as e:
                error_count = 1
                logger.warning(f"OpenAI API error: {e}")
                raise
            finally:
                end_time = time.perf_counter()
                completed_at = datetime.utcnow()
                latency_ms = int((end_time - start_time) * 1000)

                # Extract response data
                tool_sequence = []
                tool_call_count = 0
                total_tokens = 0
                prompt_tokens = 0
                completion_tokens = 0
                output_text = ""

                if response is not None:
                    try:
                        # Extract tool calls
                        if hasattr(response, "choices") and len(response.choices) > 0:
                            choice = response.choices[0]
                            if hasattr(choice, "message"):
                                message = choice.message

                                # Extract text content
                                if hasattr(message, "content") and message.content:
                                    output_text = message.content

                                # Extract tool calls
                                if (
                                    hasattr(message, "tool_calls")
                                    and message.tool_calls
                                ):
                                    for tool_call in message.tool_calls:
                                        if hasattr(tool_call, "function"):
                                            tool_name = tool_call.function.name
                                            tool_sequence.append(tool_name)
                                    tool_call_count = len(tool_sequence)

                        # Extract token usage
                        if hasattr(response, "usage"):
                            usage = response.usage
                            total_tokens = getattr(usage, "total_tokens", 0)
                            prompt_tokens = getattr(usage, "prompt_tokens", 0)
                            completion_tokens = getattr(usage, "completion_tokens", 0)

                    except Exception as e:
                        logger.debug(f"Failed to extract response data: {e}")

                output_length = len(output_text)
                output_structure_hash = _compute_structure_hash(
                    {
                        "model": model,
                        "tool_calls": tool_sequence,
                        "output_length": output_length,
                    }
                )

                payload = {
                    "session_id": self.session_id,
                    "deployment_version": self.deployment_version,
                    "environment": self.environment,
                    "started_at": started_at,
                    "completed_at": completed_at,
                    "task_input_hash": task_input_hash[:32],
                    "tool_sequence": json.dumps(tool_sequence),
                    "tool_call_count": tool_call_count,
                    "output_length": output_length,
                    "output_structure_hash": output_structure_hash[:32],
                    "latency_ms": latency_ms,
                    "error_count": error_count,
                    "retry_count": 0,
                    "semantic_cluster": "resolved",
                }

                try:
                    enqueue_run(payload)
                    logger.info(
                        f"OpenAI run saved: model={model}, tools={tool_call_count}, "
                        f"latency={latency_ms}ms, tokens={total_tokens}, errors={error_count}"
                    )
                except Exception as e:
                    _log_track_error("openai_tracer", f"Failed to save run: {e!r}")

            return response

else:
    # Stub when OpenAI is not installed
    class OpenAITracer:
        """Stub when OpenAI is not installed."""

        def __init__(self, *args: Any, **kwargs: Any):
            raise ImportError(
                "OpenAITracer requires openai. Install with: pip install openai"
            )
