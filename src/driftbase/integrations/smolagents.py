"""
smolagents (Hugging Face) explicit adapter for driftbase.

Usage:
    from driftbase.integrations import SmolagentsTracer
    from smolagents import ToolCallingAgent

    tracer = SmolagentsTracer(version='v1.0', agent_id='research-agent')
    agent = ToolCallingAgent(
        model=model,
        tools=[...],
        step_callbacks=[tracer]
    )
    result = agent.run("Task description")
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from datetime import datetime
from typing import Any, Optional
from uuid import uuid4

from driftbase.local.local_store import enqueue_run, _log_track_error

logger = logging.getLogger(__name__)

# Try to import smolagents - fail only at instantiation time
try:
    from smolagents.memory import MemoryStep, ActionStep, PlanningStep, FinalAnswerStep
    from smolagents.agents import MultiStepAgent
    _SMOLAGENTS_AVAILABLE = True
except ImportError:
    _SMOLAGENTS_AVAILABLE = False
    MemoryStep = Any  # type: ignore[misc, assignment]
    ActionStep = Any  # type: ignore[misc, assignment]
    PlanningStep = Any  # type: ignore[misc, assignment]
    FinalAnswerStep = Any  # type: ignore[misc, assignment]
    MultiStepAgent = Any  # type: ignore[misc, assignment]


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


if _SMOLAGENTS_AVAILABLE:
    class SmolagentsTracer:
        """
        Explicit smolagents tracer that hooks into step_callbacks.

        Captures code-first execution for EU AI Act compliance:
        - Generated Python code blocks (full text for local audit trail)
        - Sandbox execution outputs (stdout, results, errors)
        - Planning steps (the "why" - model reasoning)
        - Action steps (the "what" - code execution)

        This provides complete auditability for high-risk AI systems under Article 72.

        Args:
            version: Deployment version identifier (e.g., 'v1.0', 'baseline')
            agent_id: Optional agent identifier (defaults to auto-generated session ID)

        Example:
            >>> from driftbase.integrations import SmolagentsTracer
            >>> from smolagents import ToolCallingAgent
            >>>
            >>> tracer = SmolagentsTracer(version='v1.0')
            >>> agent = ToolCallingAgent(
            ...     model=model,
            ...     tools=[search_tool, calculator],
            ...     step_callbacks=[tracer]
            ... )
            >>> result = agent.run("What is 15% of 1240?")
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

            # Accumulate steps across the agent run
            self.started_at = datetime.utcnow()
            self.steps: list[dict[str, Any]] = []
            self.planning_steps: list[str] = []
            self.code_blocks: list[str] = []
            self.execution_outputs: list[str] = []
            self.tool_sequence: list[str] = []
            self.error_count = 0
            self.task_input_hash = ""
            self.final_answer: Any = None

            logger.info(
                f"SmolagentsTracer initialized: version={self.deployment_version}, "
                f"agent_id={self.session_id}, env={self.environment}"
            )

        def __call__(self, step: MemoryStep, agent: MultiStepAgent) -> None:
            """
            Callback invoked after each step completes or fails.

            Accumulates step data and triggers _save_run() when FinalAnswerStep is detected.
            """
            try:
                # Capture task input from the first step
                if not self.task_input_hash and hasattr(agent, 'task'):
                    self.task_input_hash = _hash_content(agent.task)

                # Extract step type and data
                step_type = type(step).__name__
                step_data: dict[str, Any] = {
                    "type": step_type,
                    "timestamp": datetime.utcnow().isoformat(),
                }

                # Handle PlanningStep - capture the "why"
                if isinstance(step, PlanningStep):
                    model_output = getattr(step, "model_output", None)
                    if model_output:
                        plan_text = str(model_output)
                        self.planning_steps.append(plan_text)
                        step_data["plan"] = plan_text
                        self.tool_sequence.append(f"plan_{len(self.planning_steps)}")
                        logger.debug(f"smolagents: Captured planning step {len(self.planning_steps)}")

                # Handle ActionStep - capture the "what"
                elif isinstance(step, ActionStep):
                    # Extract generated code
                    code_action = getattr(step, "code_action", None)
                    if code_action:
                        self.code_blocks.append(code_action)
                        step_data["code"] = code_action  # Full code for local audit trail
                        logger.debug(f"smolagents: Captured code block {len(self.code_blocks)}")

                    # Extract sandbox execution output
                    action_output = getattr(step, "action_output", None)
                    if action_output is not None:
                        output_str = str(action_output)
                        self.execution_outputs.append(output_str)
                        step_data["output"] = output_str
                        logger.debug(f"smolagents: Captured execution output")

                    # Extract observations (context from the environment)
                    observations = getattr(step, "observations", None)
                    if observations:
                        step_data["observations"] = str(observations)

                    # Track errors for compliance reporting
                    error = getattr(step, "error", None)
                    if error is not None:
                        self.error_count += 1
                        step_data["error"] = str(error)
                        logger.warning(f"smolagents: Action step failed with error: {error}")

                    # Add to tool sequence
                    self.tool_sequence.append(f"code_{len(self.code_blocks)}")

                # Handle FinalAnswerStep - trigger save
                elif isinstance(step, FinalAnswerStep):
                    # Extract the final answer
                    self.final_answer = getattr(step, "answer", None)
                    step_data["answer"] = str(self.final_answer) if self.final_answer else ""
                    logger.debug(f"smolagents: Captured final answer")

                    # Accumulate this step, then save the run
                    self.steps.append(step_data)
                    self._save_run()
                    return  # Early exit - run is complete

                # Accumulate all steps
                self.steps.append(step_data)

            except Exception as e:
                logger.warning(f"smolagents tracer callback error: {e}")
                _log_track_error("smolagents_tracer", f"Callback error: {e!r}")

        def _save_run(self) -> None:
            """
            Persist the agent run to local SQLite via enqueue_run.

            Called when FinalAnswerStep is detected.
            """
            try:
                completed_at = datetime.utcnow()
                latency_ms = int((completed_at - self.started_at).total_seconds() * 1000)

                # Compute output metrics
                output_text = str(self.final_answer) if self.final_answer else ""
                output_length = len(output_text)
                output_structure_hash = _compute_structure_hash(self.final_answer)

                # Build the standard payload
                payload = {
                    "session_id": self.session_id,
                    "deployment_version": self.deployment_version,
                    "environment": self.environment,
                    "started_at": self.started_at,
                    "completed_at": completed_at,
                    "task_input_hash": self.task_input_hash[:32] if self.task_input_hash else "none",
                    "tool_sequence": json.dumps(self.tool_sequence),
                    "tool_call_count": len(self.tool_sequence),
                    "output_length": output_length,
                    "output_structure_hash": output_structure_hash[:32],
                    "latency_ms": latency_ms,
                    "error_count": self.error_count,
                    "retry_count": 0,
                    "semantic_cluster": "error" if self.error_count > 0 else "resolved",
                }

                # EU AI Act compliance: Store full audit trail in local SQLite
                # (This will be truncated/hashed when syncing to Azure Cloud)
                payload["code_audit_trail"] = json.dumps({
                    "planning_steps": self.planning_steps,
                    "code_blocks": self.code_blocks,
                    "execution_outputs": self.execution_outputs,
                    "steps": self.steps,
                })

                enqueue_run(payload)
                logger.info(
                    f"smolagents run saved: code_blocks={len(self.code_blocks)}, "
                    f"planning_steps={len(self.planning_steps)}, "
                    f"latency={latency_ms}ms, errors={self.error_count}"
                )

            except Exception as e:
                _log_track_error("smolagents_tracer", f"Failed to save run: {e!r}")

else:
    # Stub when smolagents is not installed
    class SmolagentsTracer:
        """Stub when smolagents is not installed."""
        def __init__(self, *args: Any, **kwargs: Any):
            raise ImportError(
                "SmolagentsTracer requires smolagents. "
                "Install with: pip install smolagents"
            )
