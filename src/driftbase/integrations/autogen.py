"""
AutoGen explicit adapter for driftbase.

Usage:
    from driftbase.integrations import AutoGenTracer
    from autogen import AssistantAgent, UserProxyAgent

    tracer = AutoGenTracer(version='v1.0')
    assistant = AssistantAgent(name="assistant", llm_config=llm_config)
    user_proxy = UserProxyAgent(name="user")

    tracer.instrument(assistant)
    user_proxy.initiate_chat(assistant, message="Hello")
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

# Try to import AutoGen - fail only at instantiation time
try:
    import autogen

    _AUTOGEN_AVAILABLE = True
except ImportError:
    _AUTOGEN_AVAILABLE = False
    autogen = None  # type: ignore[assignment]


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


if _AUTOGEN_AVAILABLE:

    class AutoGenTracer:
        """
        Explicit AutoGen tracer that patches agent.generate_reply().

        This tracer instruments AutoGen agents to capture:
        - Tool/function calls
        - Latency per interaction
        - Token usage
        - Outcome

        Args:
            version: Deployment version identifier (e.g., 'v1.0', 'baseline')
            agent_id: Optional agent identifier (defaults to auto-generated session ID)

        Example:
            >>> from driftbase.integrations import AutoGenTracer
            >>> from autogen import AssistantAgent, UserProxyAgent
            >>>
            >>> tracer = AutoGenTracer(version='v1.0')
            >>> assistant = AssistantAgent(name="assistant", llm_config=llm_config)
            >>> user_proxy = UserProxyAgent(name="user")
            >>>
            >>> tracer.instrument(assistant)
            >>> user_proxy.initiate_chat(assistant, message="Hello")
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

            # Track instrumented agents to avoid double-patching
            self.instrumented_agents = set()

            logger.info(
                f"AutoGenTracer initialized: version={self.deployment_version}, "
                f"agent_id={self.session_id}, env={self.environment}"
            )

        def instrument(self, agent: Any) -> None:
            """
            Instrument an AutoGen agent by patching its generate_reply method.

            Args:
                agent: AutoGen agent instance (AssistantAgent, UserProxyAgent, etc.)
            """
            # Avoid double-patching
            if id(agent) in self.instrumented_agents:
                logger.debug(f"Agent {agent.name} already instrumented")
                return

            if not hasattr(agent, "generate_reply"):
                logger.warning(f"Agent {agent.name} has no generate_reply method")
                return

            # Store the original method
            original_generate_reply = agent.generate_reply

            # Create the wrapped method
            @functools.wraps(original_generate_reply)
            def traced_generate_reply(messages=None, sender=None, config=None):
                return self._traced_generate_reply(
                    agent, original_generate_reply, messages, sender, config
                )

            # Apply the patch
            agent.generate_reply = traced_generate_reply
            self.instrumented_agents.add(id(agent))

            logger.info(f"AutoGen agent '{agent.name}' instrumented")

        def _traced_generate_reply(
            self,
            agent: Any,
            original_method: Any,
            messages: Any,
            sender: Any,
            config: Any,
        ) -> Any:
            """Wrapped version of generate_reply that tracks calls."""
            started_at = datetime.utcnow()
            start_time = time.perf_counter()
            error_count = 0
            response = None

            # Extract messages for input hash
            task_input_hash = _hash_content(messages)

            # Track tool calls
            tool_sequence = []
            tool_call_count = 0

            try:
                # Call the original method
                response = original_method(
                    messages=messages, sender=sender, config=config
                )

                # Try to extract tool calls from the response
                if isinstance(response, dict):
                    # Check for function calls in the response
                    if "function_call" in response:
                        func_name = response["function_call"].get(
                            "name", "unknown_function"
                        )
                        tool_sequence.append(func_name)
                        tool_call_count = 1
                    elif "tool_calls" in response and isinstance(
                        response["tool_calls"], list
                    ):
                        for tool_call in response["tool_calls"]:
                            if isinstance(tool_call, dict) and "function" in tool_call:
                                func_name = tool_call["function"].get(
                                    "name", "unknown_function"
                                )
                                tool_sequence.append(func_name)
                        tool_call_count = len(tool_sequence)

            except Exception as e:
                error_count = 1
                logger.warning(f"AutoGen generate_reply error: {e}")
                raise
            finally:
                end_time = time.perf_counter()
                completed_at = datetime.utcnow()
                latency_ms = int((end_time - start_time) * 1000)

                # Compute output metrics
                output_text = str(response) if response is not None else ""
                output_length = len(output_text)
                output_structure_hash = _compute_structure_hash(response)

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
                        f"AutoGen run saved: agent={agent.name}, tools={tool_call_count}, "
                        f"latency={latency_ms}ms, errors={error_count}"
                    )
                except Exception as e:
                    _log_track_error("autogen_tracer", f"Failed to save run: {e!r}")

            return response

else:
    # Stub when AutoGen is not installed
    class AutoGenTracer:
        """Stub when AutoGen is not installed."""

        def __init__(self, *args: Any, **kwargs: Any):
            raise ImportError(
                "AutoGenTracer requires pyautogen. Install with: pip install pyautogen"
            )
