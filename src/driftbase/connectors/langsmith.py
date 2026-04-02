"""LangSmith trace connector."""

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
    from langsmith import Client as LangSmithClient

    LANGSMITH_AVAILABLE = True
except ImportError:
    LANGSMITH_AVAILABLE = False


class LangSmithConnector(TraceConnector):
    """Connector for importing traces from LangSmith."""

    def __init__(self):
        if not LANGSMITH_AVAILABLE:
            raise ImportError(
                "langsmith extra not installed. Run: pip install driftbase[langsmith]"
            )

        api_key = os.getenv("LANGSMITH_API_KEY")
        if not api_key:
            raise ValueError("LANGSMITH_API_KEY environment variable not set")

        try:
            self.client = LangSmithClient(api_key=api_key)
        except Exception as e:
            raise ValueError(f"Failed to initialize LangSmith client: {e}") from e

    def validate_credentials(self) -> bool:
        """Check if API key is valid."""
        try:
            # Try to list projects (minimal API call)
            list(self.client.list_projects(limit=1))
            return True
        except Exception as e:
            logger.debug(f"LangSmith credential validation failed: {e}")
            return False

    def list_projects(self) -> list[dict[str, Any]]:
        """
        List available projects with run counts.
        Returns [{"name": str, "run_count": int}] sorted by run_count desc.
        Returns [] on any error. Never raises.
        """
        try:
            if not LANGSMITH_AVAILABLE:
                return []

            projects = list(self.client.list_projects())
            result = []

            for p in projects:
                try:
                    # Get run count for this project
                    runs = list(self.client.list_runs(project_name=p.name, limit=1))
                    # LangSmith doesn't provide a direct count API, so we estimate
                    # by fetching a small sample. For better UX, we could paginate
                    # but that's slow. Instead, use a heuristic.
                    count = getattr(p, "run_count", 0)
                    if count == 0:
                        # Try to get count from recent runs
                        try:
                            recent_runs = list(
                                self.client.list_runs(project_name=p.name, limit=1000)
                            )
                            count = len(recent_runs)
                        except Exception:
                            count = 0

                    result.append({"name": p.name, "run_count": count})
                except Exception as e:
                    logger.debug(f"Failed to get run count for project {p.name}: {e}")
                    result.append({"name": p.name, "run_count": 0})

            return sorted(result, key=lambda x: x["run_count"], reverse=True)
        except Exception as e:
            logger.debug(f"Failed to list projects: {e}")
            return []

    def fetch_traces(self, config: ConnectorConfig) -> list[dict]:
        """Fetch chain-level runs from LangSmith."""
        try:
            # Fetch runs with run_type="chain" (top-level only)
            runs = list(
                self.client.list_runs(
                    project_name=config.project_name,
                    run_type="chain",
                    limit=config.limit,
                    start_time=config.since,
                )
            )

            # For each run, fetch child runs to extract tools
            results = []
            for run in runs:
                try:
                    # Fetch child runs
                    children = list(
                        self.client.list_runs(
                            project_name=config.project_name,
                            parent_run_id=run.id,
                        )
                    )

                    # Convert to dict and attach children
                    run_dict = run.dict() if hasattr(run, "dict") else dict(run)
                    run_dict["child_runs"] = [
                        c.dict() if hasattr(c, "dict") else dict(c) for c in children
                    ]
                    results.append(run_dict)
                except Exception as e:
                    logger.warning(
                        f"Failed to fetch children for run {run.id}: {e}, including run without children"
                    )
                    run_dict = run.dict() if hasattr(run, "dict") else dict(run)
                    run_dict["child_runs"] = []
                    results.append(run_dict)

            return results
        except Exception as e:
            logger.error(f"Failed to fetch LangSmith traces: {e}")
            return []

    def map_trace(self, trace: dict, config: ConnectorConfig) -> dict | None:
        """Map LangSmith run to Driftbase schema."""
        try:
            # Extract version from tags (first tag matching "version:*" or epoch)
            version = None
            tags = trace.get("tags", [])
            for tag in tags:
                if isinstance(tag, str) and tag.startswith("version:"):
                    version = tag.split(":", 1)[1]
                    break

            if not version:
                # Fall back to epoch label based on start time
                start_time = trace.get("start_time")
                if start_time:
                    if isinstance(start_time, str):
                        dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
                    else:
                        dt = start_time
                    monday = dt - timedelta(days=dt.weekday())
                    version = f"epoch-{monday.date().isoformat()}"
                else:
                    version = "unknown"

            # Compute latency
            start_time = trace.get("start_time")
            end_time = trace.get("end_time")
            latency_ms = 0
            start_dt = None
            end_dt = None

            if start_time and end_time:
                try:
                    if isinstance(start_time, str):
                        start_dt = datetime.fromisoformat(
                            start_time.replace("Z", "+00:00")
                        )
                    else:
                        start_dt = start_time

                    if isinstance(end_time, str):
                        end_dt = datetime.fromisoformat(end_time.replace("Z", "+00:00"))
                    else:
                        end_dt = end_time

                    latency_ms = int((end_dt - start_dt).total_seconds() * 1000)
                except Exception as e:
                    logger.debug(f"Failed to compute latency: {e}")
                    latency_ms = 0

            # Extract tool sequence from child runs
            child_runs = trace.get("child_runs", [])
            tool_observations = [c for c in child_runs if c.get("run_type") == "tool"]
            tool_sequence_json, tool_call_count = extract_tool_sequence(
                tool_observations
            )

            # Token counts
            prompt_tokens = trace.get("prompt_tokens", 0) or 0
            completion_tokens = trace.get("completion_tokens", 0) or 0

            # Error detection
            error = trace.get("error") is not None
            error_message = str(trace["error"]) if error else None

            # Semantic cluster
            output = trace.get("outputs", {})
            output_str = str(output) if output else ""
            semantic_cluster = infer_semantic_cluster(output_str, error)

            # Session ID
            session_id = trace.get("session_name") or config.project_name
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
                "source": "langsmith",
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
                "loop_count": 0,  # Cannot infer from LangSmith
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
            logger.error(f"Failed to map LangSmith trace {trace.get('id')}: {e}")
            return None
