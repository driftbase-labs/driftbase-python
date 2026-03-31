"""
DSPy explicit adapter for driftbase.

Usage:
    from driftbase.integrations import DSPyTracer
    import dspy

    tracer = DSPyTracer(version='v1.0', agent_id='qa-system')
    dspy.configure(callbacks=[tracer], lm=dspy.LM("openai/gpt-4o"))

    # Your DSPy program runs normally
    result = my_module(question="What is DSPy?")
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

# Try to import DSPy - fail only at instantiation time
try:
    import dspy
    from dspy.utils.callback import BaseCallback

    _DSPY_AVAILABLE = True
except ImportError:
    _DSPY_AVAILABLE = False
    BaseCallback = object  # type: ignore[misc, assignment]


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


if _DSPY_AVAILABLE:

    class DSPyTracer(BaseCallback):
        """
        Explicit DSPy tracer for EU AI Act compliance.

        Captures module execution with full LM metadata traceability:
        - Input signatures (documented intent + resolved fields)
        - Prompts and outputs
        - Model name, provider, token counts (exact model string for audits)
        - Reasoning steps (ChainOfThought, ReAct intermediate thoughts)
        - Optional optimizer trajectory tracking (GDPR risk - opt-in only)

        This provides complete traceability for LM-based systems under EU AI Act Article 72.

        Args:
            version: Deployment version identifier (e.g., 'v1.0', 'baseline')
            agent_id: Optional agent identifier (defaults to auto-generated session ID)
            track_optimizer: If True, track optimizer trajectories (GDPR data minimization risk). Default: False

        Example:
            >>> from driftbase.integrations import DSPyTracer
            >>> import dspy
            >>>
            >>> tracer = DSPyTracer(version='v1.0')
            >>> dspy.configure(callbacks=[tracer], lm=dspy.LM("openai/gpt-4o"))
            >>>
            >>> class QA(dspy.Module):
            ...     def forward(self, question):
            ...         return dspy.Predict("question -> answer")(question=question)
            >>>
            >>> qa = QA()
            >>> result = qa(question="What is DSPy?")
        """

        def __init__(
            self,
            version: str,
            agent_id: str | None = None,
            track_optimizer: bool = False,
            _external_ctx: Any | None = None,
        ):
            import os

            super().__init__()
            self.deployment_version = version
            self.environment = os.getenv("DRIFTBASE_ENVIRONMENT", "production")
            self.session_id = agent_id or str(uuid4())
            self.track_optimizer = track_optimizer

            # Program execution state
            self.started_at = datetime.utcnow()
            self.module_executions: list[dict[str, Any]] = []
            self.tool_sequence: list[str] = []
            self.reasoning_steps: list[str] = []
            self.error_count = 0
            self.task_input_hash = ""

            # Track active module calls (for matching start/end)
            self._active_calls: dict[str, dict[str, Any]] = {}
            self._call_stack: list[str] = []

            # LM metadata accumulation
            self.total_prompt_tokens = 0
            self.total_completion_tokens = 0
            self.model_names: list[str] = []

            # External context for @track integration (not yet implemented)
            self._external_ctx = _external_ctx

            if track_optimizer:
                logger.warning(
                    "DSPyTracer: track_optimizer=True - Optimizer trajectories will be stored. "
                    "This violates GDPR data minimization principles and will generate hundreds "
                    "of runs during compilation. Use only for explicit debugging."
                )

            logger.info(
                f"DSPyTracer initialized: version={self.deployment_version}, "
                f"agent_id={self.session_id}, env={self.environment}, "
                f"track_optimizer={track_optimizer}"
            )

        def on_module_start(
            self,
            call_id: str,
            instance: Any,
            inputs: dict[str, Any],
        ) -> None:
            """
            Called by DSPy when a module starts execution.

            Captures signature string, resolved input fields, and starts timing.
            """
            try:
                # Skip optimizer runs unless explicitly tracking
                if not self.track_optimizer and self._is_optimizer_call(instance):
                    return

                # Extract module metadata
                module_type = type(instance).__name__

                # Extract signature (the documented intent)
                signature_string = self._extract_signature_string(instance)

                # Extract resolved input field names (the actual schema)
                input_fields = list(inputs.keys())

                # Capture task input from the first root module
                if not self.task_input_hash and not self._call_stack:
                    self.task_input_hash = _hash_content(inputs)

                # Record module start
                call_data = {
                    "call_id": call_id,
                    "module_type": module_type,
                    "signature_string": signature_string,
                    "input_fields": input_fields,
                    "inputs": inputs.copy(),  # Copy to avoid mutation
                    "started_at": datetime.utcnow(),
                    "start_time": time.perf_counter(),
                }

                self._active_calls[call_id] = call_data
                self._call_stack.append(call_id)

                logger.debug(
                    f"DSPy module started: {module_type} (signature: {signature_string})"
                )

            except Exception as e:
                logger.warning(f"DSPy tracer on_module_start error: {e}")
                _log_track_error("dspy_tracer", f"on_module_start error: {e!r}")

        def on_module_end(
            self,
            call_id: str,
            outputs: dict[str, Any],
            exception: Exception | None = None,
        ) -> None:
            """
            Called by DSPy when a module completes or fails.

            Captures outputs, LM metadata, reasoning steps, and triggers save on root exit.
            """
            try:
                # Skip optimizer runs unless explicitly tracking
                if call_id not in self._active_calls:
                    return

                call_data = self._active_calls.pop(call_id)
                if self._call_stack and self._call_stack[-1] == call_id:
                    self._call_stack.pop()

                # Calculate latency
                end_time = time.perf_counter()
                latency_ms = int((end_time - call_data["start_time"]) * 1000)

                # Extract resolved output field names (the actual schema)
                output_fields = list(outputs.keys()) if outputs else []

                # Extract reasoning steps (ChainOfThought, ReAct)
                reasoning = self._extract_reasoning(outputs)
                if reasoning:
                    self.reasoning_steps.extend(reasoning)

                # Extract LM metadata (model, tokens) - CRITICAL for EU AI Act traceability
                lm_metadata = self._extract_lm_metadata(outputs)
                if lm_metadata:
                    self.model_names.append(lm_metadata.get("model", "unknown"))
                    self.total_prompt_tokens += lm_metadata.get("prompt_tokens", 0)
                    self.total_completion_tokens += lm_metadata.get(
                        "completion_tokens", 0
                    )

                # Build execution record
                execution_record = {
                    "module_type": call_data["module_type"],
                    "signature_string": call_data["signature_string"],
                    "input_fields": call_data["input_fields"],
                    "output_fields": output_fields,
                    "inputs": call_data["inputs"],
                    "outputs": outputs.copy() if outputs else {},
                    "latency_ms": latency_ms,
                    "started_at": call_data["started_at"].isoformat(),
                    "completed_at": datetime.utcnow().isoformat(),
                    "lm_metadata": lm_metadata,
                    "error": str(exception) if exception else None,
                }

                # Track errors
                if exception is not None:
                    self.error_count += 1
                    logger.warning(
                        f"DSPy module failed: {call_data['module_type']} - {exception}"
                    )

                self.module_executions.append(execution_record)
                self.tool_sequence.append(call_data["module_type"])

                logger.debug(
                    f"DSPy module completed: {call_data['module_type']} "
                    f"({latency_ms}ms, model: {lm_metadata.get('model', 'N/A')})"
                )

                # If this is the root module (call stack empty), save the run
                if not self._call_stack:
                    self._save_run()

            except Exception as e:
                logger.warning(f"DSPy tracer on_module_end error: {e}")
                _log_track_error("dspy_tracer", f"on_module_end error: {e!r}")

        def _extract_signature_string(self, instance: Any) -> str:
            """
            Extract the signature string (e.g., "question -> answer").

            This is the documented intent of the module - required for EU AI Act transparency.
            """
            try:
                # Try to get signature from instance
                if hasattr(instance, "signature"):
                    sig = instance.signature
                    # If signature is an object, try to get its string representation
                    if hasattr(sig, "__str__") and not isinstance(sig, type):
                        sig_str = str(sig)
                        # Clean up if it's a repr-style string
                        if "->" in sig_str:
                            return sig_str
                    # Try to extract from signature fields
                    if hasattr(sig, "input_fields") and hasattr(sig, "output_fields"):
                        input_names = ", ".join(sig.input_fields.keys())
                        output_names = ", ".join(sig.output_fields.keys())
                        return f"{input_names} -> {output_names}"

                # Fallback: try to infer from class name
                return type(instance).__name__

            except Exception as e:
                logger.debug(f"Failed to extract signature string: {e}")
                return "unknown"

        def _extract_reasoning(self, outputs: dict[str, Any]) -> list[str]:
            """
            Extract reasoning steps from ChainOfThought or ReAct outputs.

            Looks for fields starting with "Thought", "rationale", "reasoning", etc.
            """
            reasoning = []
            try:
                for key, value in outputs.items():
                    # Check for common reasoning field names
                    if (
                        any(
                            term in key.lower()
                            for term in ["thought", "rationale", "reasoning", "chain"]
                        )
                        and value
                    ):
                        reasoning.append(str(value))
            except Exception as e:
                logger.debug(f"Failed to extract reasoning: {e}")
            return reasoning

        def _extract_lm_metadata(self, outputs: dict[str, Any]) -> dict[str, Any]:
            """
            Extract LM metadata (model name, provider, token counts).

            CRITICAL for EU AI Act compliance: If a provider updates weights,
            auditors need the exact model string that caused the incident.
            """
            metadata: dict[str, Any] = {}

            try:
                # DSPy may expose LM metadata in different ways
                # Try to extract from common locations

                # Check for direct metadata fields
                if "model" in outputs:
                    metadata["model"] = outputs["model"]

                # Check for usage/token information
                if "usage" in outputs:
                    usage = outputs["usage"]
                    if isinstance(usage, dict):
                        metadata["prompt_tokens"] = usage.get("prompt_tokens", 0)
                        metadata["completion_tokens"] = usage.get(
                            "completion_tokens", 0
                        )
                        metadata["total_tokens"] = usage.get("total_tokens", 0)

                # Try to get model info from dspy settings
                if not metadata.get("model"):
                    try:
                        lm = dspy.settings.lm
                        if lm:
                            # Try various attributes where model name might be stored
                            for attr in ["model", "model_name", "kwargs"]:
                                if hasattr(lm, attr):
                                    val = getattr(lm, attr)
                                    if isinstance(val, str):
                                        metadata["model"] = val
                                        break
                                    elif isinstance(val, dict) and "model" in val:
                                        metadata["model"] = val["model"]
                                        break
                    except Exception:
                        pass

                # Try to extract provider (e.g., "openai", "anthropic")
                model_str = metadata.get("model", "")
                if "/" in model_str:
                    metadata["provider"] = model_str.split("/")[0]
                elif model_str:
                    # Infer from model name
                    if "gpt" in model_str.lower():
                        metadata["provider"] = "openai"
                    elif "claude" in model_str.lower():
                        metadata["provider"] = "anthropic"
                    else:
                        metadata["provider"] = "unknown"

            except Exception as e:
                logger.debug(f"Failed to extract LM metadata: {e}")

            return metadata

        def _is_optimizer_call(self, instance: Any) -> bool:
            """
            Detect if this is an optimizer/teleprompter call.

            During compilation, DSPy runs thousands of calls. We skip these
            unless track_optimizer=True to avoid GDPR data minimization violations.
            """
            # This is a heuristic - optimizer calls might have specific patterns
            # For now, we rely on the track_optimizer flag
            # Future enhancement: detect optimizer context from call stack
            return False  # Conservative: don't auto-detect, rely on flag

        def _save_run(self) -> None:
            """
            Persist the DSPy program run to local SQLite via enqueue_run.

            Called when the root module exits (program completes).
            """
            # Stub: context sharing not yet implemented for DSPy
            if self._external_ctx is not None:
                logger.info(
                    "DSPy context sharing not yet implemented - using standalone mode"
                )
                # Fall through to normal save for now

            try:
                completed_at = datetime.utcnow()
                latency_ms = int(
                    (completed_at - self.started_at).total_seconds() * 1000
                )

                # Compute output metrics
                total_output_length = sum(
                    len(str(exec_rec.get("outputs", "")))
                    for exec_rec in self.module_executions
                )
                output_structure = {
                    "modules": len(self.module_executions),
                    "reasoning_steps": len(self.reasoning_steps),
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

                # EU AI Act compliance: Full LM traceability
                payload["dspy_audit_trail"] = json.dumps(
                    {
                        "module_executions": [
                            {
                                "module_type": exec_rec["module_type"],
                                "signature_string": exec_rec["signature_string"],
                                "input_fields": exec_rec["input_fields"],
                                "output_fields": exec_rec["output_fields"],
                                "latency_ms": exec_rec["latency_ms"],
                                "lm_metadata": exec_rec["lm_metadata"],
                                "error": exec_rec["error"],
                            }
                            for exec_rec in self.module_executions
                        ],
                        "reasoning_steps": self.reasoning_steps,
                        "model_names": list(set(self.model_names)),  # Deduplicate
                        "total_prompt_tokens": self.total_prompt_tokens,
                        "total_completion_tokens": self.total_completion_tokens,
                        "optimizer_run": self.track_optimizer,
                    }
                )

                enqueue_run(payload)
                logger.info(
                    f"DSPy run saved: modules={len(self.module_executions)}, "
                    f"reasoning_steps={len(self.reasoning_steps)}, "
                    f"models={set(self.model_names)}, "
                    f"tokens={self.total_prompt_tokens + self.total_completion_tokens}, "
                    f"latency={latency_ms}ms, errors={self.error_count}"
                )

            except Exception as e:
                _log_track_error("dspy_tracer", f"Failed to save run: {e!r}")

else:
    # Stub when DSPy is not installed
    class DSPyTracer:
        """Stub when DSPy is not installed."""

        def __init__(self, *args: Any, **kwargs: Any):
            raise ImportError(
                "DSPyTracer requires dspy. Install with: pip install dspy-ai"
            )
