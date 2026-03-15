"""
CrewAI explicit adapter for driftbase.

Usage:
    from driftbase.integrations import CrewAITracer
    from crewai import Crew, Agent, Task

    tracer = CrewAITracer(version='v1.0')
    crew = Crew(agents=[agent1, agent2], tasks=[task1, task2])

    tracer.instrument(crew)
    result = crew.kickoff()
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

# Try to import CrewAI - fail only at instantiation time
try:
    import crewai

    _CREWAI_AVAILABLE = True
except ImportError:
    _CREWAI_AVAILABLE = False
    crewai = None  # type: ignore[assignment]


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


if _CREWAI_AVAILABLE:

    class CrewAITracer:
        """
        Explicit CrewAI tracer that patches crew.kickoff().

        This tracer instruments CrewAI crews to capture:
        - Task names as tool calls
        - Latency
        - Outcome

        Args:
            version: Deployment version identifier (e.g., 'v1.0', 'baseline')
            agent_id: Optional agent identifier (defaults to auto-generated session ID)

        Example:
            >>> from driftbase.integrations import CrewAITracer
            >>> from crewai import Crew, Agent, Task
            >>>
            >>> tracer = CrewAITracer(version='v1.0')
            >>> crew = Crew(agents=[agent1, agent2], tasks=[task1, task2])
            >>>
            >>> tracer.instrument(crew)
            >>> result = crew.kickoff()
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

            # Track instrumented crews to avoid double-patching
            self.instrumented_crews = set()

            logger.info(
                f"CrewAITracer initialized: version={self.deployment_version}, "
                f"agent_id={self.session_id}, env={self.environment}"
            )

        def instrument(self, crew: Any) -> None:
            """
            Instrument a CrewAI crew by patching its kickoff method.

            Args:
                crew: CrewAI Crew instance
            """
            # Avoid double-patching
            if id(crew) in self.instrumented_crews:
                logger.debug("Crew already instrumented")
                return

            if not hasattr(crew, "kickoff"):
                logger.warning("Crew has no kickoff method")
                return

            # Store the original method
            original_kickoff = crew.kickoff

            # Create the wrapped method
            @functools.wraps(original_kickoff)
            def traced_kickoff(*args, **kwargs):
                return self._traced_kickoff(crew, original_kickoff, *args, **kwargs)

            # Apply the patch
            crew.kickoff = traced_kickoff
            self.instrumented_crews.add(id(crew))

            logger.info("CrewAI crew instrumented")

        def _traced_kickoff(
            self, crew: Any, original_method: Any, *args, **kwargs
        ) -> Any:
            """Wrapped version of kickoff that tracks execution."""
            started_at = datetime.utcnow()
            start_time = time.perf_counter()
            error_count = 0
            result = None

            # Extract tasks for input hash and tool sequence
            tool_sequence = []
            task_input_hash = ""

            try:
                # Try to extract task information from the crew
                if hasattr(crew, "tasks") and crew.tasks:
                    tasks_info = []
                    for task in crew.tasks:
                        task_name = getattr(task, "description", None) or getattr(
                            task, "name", "unknown_task"
                        )
                        # Truncate long descriptions
                        if isinstance(task_name, str) and len(task_name) > 50:
                            task_name = task_name[:50] + "..."
                        tasks_info.append(task_name)
                        # Use task names/descriptions as "tool calls"
                        tool_sequence.append(task_name)

                    task_input_hash = _hash_content(tasks_info)
                else:
                    task_input_hash = _hash_content({"args": args, "kwargs": kwargs})

            except Exception as e:
                logger.debug(f"Failed to extract task info: {e}")
                task_input_hash = _hash_content({"args": args, "kwargs": kwargs})

            try:
                # Call the original method
                result = original_method(*args, **kwargs)

            except Exception as e:
                error_count = 1
                logger.warning(f"CrewAI kickoff error: {e}")
                raise
            finally:
                end_time = time.perf_counter()
                completed_at = datetime.utcnow()
                latency_ms = int((end_time - start_time) * 1000)

                # Compute output metrics
                output_text = str(result) if result is not None else ""
                output_length = len(output_text)
                output_structure_hash = _compute_structure_hash(result)

                payload = {
                    "session_id": self.session_id,
                    "deployment_version": self.deployment_version,
                    "environment": self.environment,
                    "started_at": started_at,
                    "completed_at": completed_at,
                    "task_input_hash": task_input_hash[:32],
                    "tool_sequence": json.dumps(tool_sequence),
                    "tool_call_count": len(tool_sequence),
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
                        f"CrewAI run saved: tasks={len(tool_sequence)}, "
                        f"latency={latency_ms}ms, errors={error_count}"
                    )
                except Exception as e:
                    _log_track_error("crewai_tracer", f"Failed to save run: {e!r}")

            return result

else:
    # Stub when CrewAI is not installed
    class CrewAITracer:
        """Stub when CrewAI is not installed."""

        def __init__(self, *args: Any, **kwargs: Any):
            raise ImportError(
                "CrewAITracer requires crewai. Install with: pip install crewai"
            )
