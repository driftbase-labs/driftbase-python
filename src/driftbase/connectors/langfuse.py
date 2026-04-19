"""LangFuse trace connector."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from driftbase.connectors.base import ConnectorConfig, TraceConnector
from driftbase.connectors.mapper import (
    compute_verbosity_ratio,
    extract_tool_sequence,
    infer_semantic_cluster,
)

logger = logging.getLogger(__name__)

try:
    from langfuse import Langfuse

    LANGFUSE_AVAILABLE = True
except ImportError:
    LANGFUSE_AVAILABLE = False


class LangFuseConnector(TraceConnector):
    """Connector for importing traces from LangFuse."""

    def __init__(self):
        if not LANGFUSE_AVAILABLE:
            raise ImportError(
                "langfuse package not installed. Run: pip install driftbase"
            )

        public_key = os.getenv("LANGFUSE_PUBLIC_KEY")
        secret_key = os.getenv("LANGFUSE_SECRET_KEY")
        host = os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")

        if not public_key or not secret_key:
            raise ValueError(
                "LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY environment variables must be set"
            )

        try:
            self.client = Langfuse(
                public_key=public_key, secret_key=secret_key, host=host
            )
        except Exception as e:
            raise ValueError(f"Failed to initialize LangFuse client: {e}") from e

    def validate_credentials(self) -> bool:
        """Check if API keys are valid."""
        try:
            # Try to fetch traces (minimal API call)
            self.client.get_traces(limit=1)
            return True
        except Exception as e:
            logger.debug(f"LangFuse credential validation failed: {e}")
            return False

    def list_projects(self) -> list[dict[str, Any]]:
        """
        List available projects with trace counts.
        Returns [{"name": str, "run_count": int}] sorted by run_count desc.
        LangFuse uses projects differently — return the configured project
        with an estimated trace count.
        Returns [] on any error. Never raises.
        """
        try:
            if not LANGFUSE_AVAILABLE:
                return []

            public_key = os.environ.get("LANGFUSE_PUBLIC_KEY", "")
            secret_key = os.environ.get("LANGFUSE_SECRET_KEY", "")

            if not public_key or not secret_key:
                return []

            # Fetch traces to get count
            traces = self.client.get_traces(limit=1)

            # Use pagination total if available
            count = getattr(traces, "total", "unknown")
            if count == "unknown":
                # Try to estimate by fetching a sample
                try:
                    sample = self.client.get_traces(limit=1000)
                    count = len(sample.data) if hasattr(sample, "data") else 0
                except Exception:
                    count = 0

            # LangFuse doesn't have explicit projects in the same way - use env var or default
            project_name = os.environ.get("LANGFUSE_PROJECT", "default")

            return [{"name": project_name, "run_count": count}]
        except Exception as e:
            logger.debug(f"Failed to list projects: {e}")
            return []

    def fetch_traces(self, config: ConnectorConfig) -> list[dict]:
        """Fetch traces from LangFuse."""
        try:
            # Build fetch parameters
            fetch_params: dict[str, Any] = {
                "limit": config.limit,
            }

            # Add time filter if specified
            if config.since:
                fetch_params["from_timestamp"] = config.since

            # Add project filter if the API supports it
            # Note: LangFuse API may use different filter names
            if config.project_name:
                # Try to filter by name or tag
                fetch_params["name"] = config.project_name

            # Fetch traces
            traces_response = self.client.get_traces(**fetch_params)

            # Convert to list of dicts
            results = []
            for trace in traces_response.data:
                trace_dict = trace.dict() if hasattr(trace, "dict") else dict(trace)

                # Fetch observations for this trace
                try:
                    observations_response = self.client.get_observations(
                        trace_id=trace_dict.get("id")
                    )
                    trace_dict["observations"] = [
                        obs.dict() if hasattr(obs, "dict") else dict(obs)
                        for obs in observations_response.data
                    ]
                except Exception as e:
                    logger.warning(
                        f"Failed to fetch observations for trace {trace_dict.get('id')}: {e}"
                    )
                    trace_dict["observations"] = []

                results.append(trace_dict)

            return results
        except Exception as e:
            logger.error(f"Failed to fetch LangFuse traces: {e}")
            return []

    def map_trace(self, trace: dict, config: ConnectorConfig) -> dict | None:
        """Map LangFuse trace to Driftbase schema."""
        try:
            # Extract version from trace metadata
            version = trace.get("release") or trace.get("version")

            if not version:
                # Fall back to epoch label based on timestamp
                timestamp = trace.get("timestamp")
                if timestamp:
                    if isinstance(timestamp, str):
                        dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                    else:
                        dt = timestamp
                    monday = dt - timedelta(days=dt.weekday())
                    version = f"epoch-{monday.date().isoformat()}"
                else:
                    version = "unknown"

            # Compute latency from metadata or observations
            latency_ms = 0
            start_dt = None
            end_dt = None

            timestamp = trace.get("timestamp")
            if timestamp:
                if isinstance(timestamp, str):
                    start_dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                else:
                    start_dt = timestamp

            # Try to get end time from observations or add duration
            observations = trace.get("observations", [])
            if observations:
                # Get latest observation end time
                for obs in observations:
                    obs_end = obs.get("endTime") or obs.get("end_time")
                    if obs_end:
                        if isinstance(obs_end, str):
                            obs_end_dt = datetime.fromisoformat(
                                obs_end.replace("Z", "+00:00")
                            )
                        else:
                            obs_end_dt = obs_end
                        if not end_dt or obs_end_dt > end_dt:
                            end_dt = obs_end_dt

            if not end_dt and start_dt:
                # Use current time as fallback
                end_dt = datetime.utcnow()

            if start_dt and end_dt:
                latency_ms = int((end_dt - start_dt).total_seconds() * 1000)

            # Extract tool sequence from observations
            tool_observations = [
                obs for obs in observations if obs.get("type") == "generation"
            ]  # LangFuse uses "generation" for tool calls
            tool_sequence_json, tool_call_count = extract_tool_sequence(
                tool_observations
            )

            # Token counts from observations
            prompt_tokens = 0
            completion_tokens = 0
            for obs in observations:
                usage = obs.get("usage", {})
                if usage:
                    prompt_tokens += usage.get("input", 0) or 0
                    completion_tokens += usage.get("output", 0) or 0

            # Error detection
            error = False
            error_message = None
            for obs in observations:
                if obs.get("level") == "ERROR":
                    error = True
                    error_message = obs.get("statusMessage") or obs.get("output")
                    break

            # Semantic cluster
            output = trace.get("output") or ""
            output_str = str(output) if output else ""
            semantic_cluster = infer_semantic_cluster(output_str, error)

            # Session ID
            session_id = trace.get("sessionId") or config.project_name
            if config.agent_id:
                session_id = config.agent_id

            # Use start time if available, otherwise current time
            if not start_dt:
                start_dt = datetime.utcnow()
            if not end_dt:
                end_dt = datetime.utcnow()

            return {
                "id": str(uuid4()),  # Generate new UUID for Driftbase
                "external_id": str(trace.get("id", str(uuid4()))),
                "source": "langfuse",
                "session_id": session_id,
                "deployment_version": version,
                "environment": "production",
                "started_at": start_dt,
                "completed_at": end_dt,
                "latency_ms": latency_ms,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "error_count": 1 if error else 0,
                "tool_sequence": tool_sequence_json,
                "tool_call_sequence": tool_sequence_json,
                "tool_call_count": tool_call_count,
                "loop_count": 0,  # Cannot infer from LangFuse
                "time_to_first_tool_ms": 0,  # Cannot infer
                "output_length": len(output_str),
                "semantic_cluster": semantic_cluster,
                "verbosity_ratio": compute_verbosity_ratio(
                    prompt_tokens, completion_tokens
                ),
                "task_input_hash": "",  # No input hash for imports
                "output_structure_hash": "",  # No structure hash
                "raw_output": output_str[:5000],  # Truncate to 5000 chars
                "raw_prompt": "",
                "retry_count": 0,
                "sensitivity": None,
            }
        except Exception as e:
            logger.error(f"Failed to map LangFuse trace {trace.get('id')}: {e}")
            return None
