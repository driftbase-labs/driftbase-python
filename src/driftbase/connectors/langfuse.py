"""LangFuse trace connector."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from driftbase.connectors.base import ConnectorConfig, TraceConnector
from driftbase.connectors.mapper import (
    compute_hash,
    compute_verbosity_ratio,
    detect_retry_patterns,
    extract_tool_sequence,
    extract_tools_from_tree,
    infer_semantic_cluster,
)

logger = logging.getLogger(__name__)

try:
    from langfuse import Langfuse

    LANGFUSE_AVAILABLE = True
except ImportError:
    LANGFUSE_AVAILABLE = False


def _build_observation_tree(observations: list[dict]) -> dict | None:
    """
    Build hierarchical observation tree from flat Langfuse observations.

    Args:
        observations: List of observation dicts from Langfuse

    Returns:
        Tree structure with each node containing:
        - id, type, name, input, output, metadata
        - children: list of child nodes

    Note:
        Returns None if observations is empty or tree build fails.
        Preserves ALL observation types (generation, span, event).
    """
    if not observations:
        return None

    try:
        # Index observations by ID for fast lookup
        obs_by_id = {obs.get("id"): obs for obs in observations if obs.get("id")}

        # Build parent->children mapping
        children_map: dict[str | None, list[dict]] = {}
        for obs in observations:
            parent_id = obs.get("parent_observation_id") or obs.get(
                "parentObservationId"
            )
            if parent_id not in children_map:
                children_map[parent_id] = []
            children_map[parent_id].append(obs)

        def build_node(obs: dict) -> dict:
            """Recursively build tree node with children."""
            node = {
                "id": obs.get("id"),
                "type": obs.get("type"),
                "name": obs.get("name"),
                "input": obs.get("input"),
                "output": obs.get("output"),
                "metadata": obs.get("metadata", {}),
                "start_time": obs.get("startTime") or obs.get("start_time"),
                "end_time": obs.get("endTime") or obs.get("end_time"),
                "level": obs.get("level"),
                "status_message": obs.get("statusMessage") or obs.get("status_message"),
            }

            # Add children recursively
            obs_id = obs.get("id")
            if obs_id and obs_id in children_map:
                node["children"] = [build_node(child) for child in children_map[obs_id]]
            else:
                node["children"] = []

            return node

        # Find root observations (those with no parent or parent not in set)
        roots = children_map.get(None, [])

        # If no explicit None-parent roots, find orphans (parent_id not in obs_by_id)
        if not roots:
            for obs in observations:
                parent_id = obs.get("parent_observation_id") or obs.get(
                    "parentObservationId"
                )
                if parent_id and parent_id not in obs_by_id:
                    roots.append(obs)

        # If still no roots, use first observation
        if not roots and observations:
            roots = [observations[0]]

        # Build tree structure
        if len(roots) == 1:
            return build_node(roots[0])
        else:
            # Multiple roots - wrap in container
            return {
                "id": "root",
                "type": "trace",
                "name": "trace_root",
                "children": [build_node(root) for root in roots],
            }

    except Exception as e:
        logger.warning(f"Failed to build observation tree: {e}")
        return None


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
            # Extract version from trace metadata (try multiple fields)
            # Track the source for version resolution transparency
            version_source = "none"
            version = None

            # Priority 1: release field
            if trace.get("release"):
                version = trace.get("release")
                version_source = "release"
            # Priority 2: version:X.Y.Z tag or metadata.version
            elif trace.get("version"):
                version = trace.get("version")
                version_source = "tag"
            elif trace.get("metadata", {}).get("deployment_version"):
                version = trace.get("metadata", {}).get("deployment_version")
                version_source = "tag"
            elif trace.get("metadata", {}).get("version"):
                version = trace.get("metadata", {}).get("version")
                version_source = "tag"
            elif trace.get("metadata", {}).get("release"):
                version = trace.get("metadata", {}).get("release")
                version_source = "release"
            # Priority 3: DRIFTBASE_VERSION environment variable
            elif os.getenv("DRIFTBASE_VERSION"):
                version = os.getenv("DRIFTBASE_VERSION")
                version_source = "env"

            # Priority 4: Fall back to epoch label based on timestamp
            if not version:
                timestamp = trace.get("timestamp")
                if timestamp:
                    if isinstance(timestamp, str):
                        dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                    else:
                        dt = timestamp
                    monday = dt - timedelta(days=dt.weekday())
                    version = f"epoch-{monday.date().isoformat()}"
                    version_source = "epoch"
                else:
                    version = "unknown"
                    version_source = "none"

            # Extract metadata early for various field extraction
            metadata = trace.get("metadata", {})

            # Extract environment from metadata
            environment = metadata.get("environment", "production")

            # Extract model information
            model = trace.get("model") or metadata.get("model") or "unknown"

            # Compute latency - prefer metadata.latency_ms, then trace.latency, then calculate from timestamps
            latency_ms_from_metadata = metadata.get("latency_ms")
            if latency_ms_from_metadata is not None:
                latency_ms = int(latency_ms_from_metadata)
            else:
                latency_raw = trace.get("latency")
                if latency_raw is not None:
                    latency_ms = int(float(latency_raw))
                else:
                    # Fall back to timestamp calculation
                    latency_ms = 0

            start_dt = None
            end_dt = None

            timestamp = trace.get("timestamp") or trace.get("startTime")
            if timestamp:
                if isinstance(timestamp, str):
                    start_dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                else:
                    start_dt = timestamp

            # Try to get end time from observations, trace.endTime, or calculate from latency
            observations = trace.get("observations", [])

            # Check trace-level endTime first
            end_time_field = trace.get("endTime") or trace.get("end_time")
            if end_time_field:
                if isinstance(end_time_field, str):
                    end_dt = datetime.fromisoformat(
                        end_time_field.replace("Z", "+00:00")
                    )
                else:
                    end_dt = end_time_field

            # If no trace-level end time, check observations
            if not end_dt and observations:
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

            # Calculate latency from timestamps if not already set
            if latency_ms == 0 and start_dt and end_dt:
                latency_ms = int((end_dt - start_dt).total_seconds() * 1000)

            # If still no end time, calculate from start + latency
            if not end_dt and start_dt and latency_ms > 0:
                end_dt = start_dt + timedelta(milliseconds=latency_ms)
            elif not end_dt and start_dt:
                # Use current time as fallback
                end_dt = datetime.now(tz=timezone.utc)

            # Build observation tree first (Phase 4 - needed for enhanced tool extraction)
            observation_tree = _build_observation_tree(observations)

            # Extract tool sequence - use tree-based extraction if available (additive)
            tool_observations = [
                obs for obs in observations if obs.get("type") == "generation"
            ]  # LangFuse uses "generation" for tool calls

            # Legacy extraction (baseline)
            legacy_tools_json, legacy_tool_count = extract_tool_sequence(
                tool_observations
            )

            # Tree-based extraction (Phase 4 additive enhancement)
            tree_tools = extract_tools_from_tree(observation_tree)

            # Merge: start with legacy, then add any new tools from tree
            legacy_tools = json.loads(legacy_tools_json) if legacy_tools_json else []
            all_tools = legacy_tools.copy()

            # Add tree tools that aren't already in legacy (preserves order)
            for tool in tree_tools:
                if tool not in all_tools:
                    all_tools.append(tool)

            tool_sequence_json = json.dumps(all_tools)
            tool_call_count = len(all_tools)

            # Detect retry patterns from tool observations
            retry_count = detect_retry_patterns(tool_observations)

            # Infer loop count from observation structure
            # Count distinct "generations" or reasoning steps as loop iterations
            loop_count = max(
                1,
                len(
                    [
                        obs
                        for obs in observations
                        if obs.get("type") in ["generation", "span"]
                    ]
                ),
            )

            # Compute time to first tool from observations
            time_to_first_tool_ms = 0
            if tool_observations and start_dt:
                first_tool_time = None
                for obs in tool_observations:
                    obs_start = obs.get("startTime") or obs.get("start_time")
                    if obs_start:
                        if isinstance(obs_start, str):
                            obs_start_dt = datetime.fromisoformat(
                                obs_start.replace("Z", "+00:00")
                            )
                        else:
                            obs_start_dt = obs_start
                        if not first_tool_time or obs_start_dt < first_tool_time:
                            first_tool_time = obs_start_dt

                if first_tool_time:
                    time_to_first_tool_ms = int(
                        (first_tool_time - start_dt).total_seconds() * 1000
                    )

            # Token counts from observations
            prompt_tokens = 0
            completion_tokens = 0
            for obs in observations:
                usage = obs.get("usage", {})
                if usage:
                    prompt_tokens += usage.get("input", 0) or 0
                    completion_tokens += usage.get("output", 0) or 0

            # Extract input and output for hashing and raw storage
            input_data = trace.get("input")
            output_data = trace.get("output")

            # Serialize to JSON strings
            raw_prompt = json.dumps(input_data) if input_data else ""
            output_str = json.dumps(output_data) if output_data else ""

            # Store full versions for blob storage (Phase 4)
            raw_prompt_full = raw_prompt
            raw_output_full = output_str

            # Compute hashes for fingerprinting
            task_input_hash = compute_hash(raw_prompt)
            output_structure_hash = compute_hash(output_str)

            # Error detection - check multiple sources like Cloud does
            error = False
            error_message = None

            # Check metadata.error first
            metadata_error = metadata.get("error")
            if metadata_error is True:
                error = True
            elif metadata_error is False:
                error = False
            else:
                # Check trace-level status and level
                status = trace.get("status", "success") or "success"
                level = trace.get("level", "") or ""

                if (
                    status in ("error", "ERROR")
                    or level in ("ERROR", "error")
                    or output_str
                    and "Error:" in output_str
                ):
                    error = True
                # Check observations for ERROR level
                else:
                    for obs in observations:
                        if obs.get("level") == "ERROR":
                            error = True
                            error_message = obs.get("statusMessage") or obs.get(
                                "output"
                            )
                            break

            # Semantic cluster
            semantic_cluster = infer_semantic_cluster(output_str, error)

            # Session ID
            session_id = trace.get("sessionId") or config.project_name
            if config.agent_id:
                session_id = config.agent_id

            # Use start time if available, otherwise current time
            if not start_dt:
                start_dt = datetime.now(tz=timezone.utc)
            if not end_dt:
                end_dt = datetime.now(tz=timezone.utc)

            # Serialize observation tree (already built above for tool extraction)
            observation_tree_json = (
                json.dumps(observation_tree) if observation_tree else None
            )

            return {
                "id": str(uuid4()),  # Generate new UUID for Driftbase
                "external_id": str(trace.get("id", str(uuid4()))),
                "source": "langfuse",
                "ingestion_source": "connector",  # Track ingestion method
                "session_id": session_id,
                "deployment_version": version,
                "version_source": version_source,  # Track version resolution source
                "environment": environment,  # Extracted from metadata
                "model": model,  # Extracted from trace or metadata
                "started_at": start_dt,
                "completed_at": end_dt,
                "latency_ms": latency_ms,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "error_count": 1 if error else 0,
                "tool_sequence": tool_sequence_json,
                "tool_call_sequence": tool_sequence_json,
                "tool_call_count": tool_call_count,
                "loop_count": loop_count,
                "time_to_first_tool_ms": max(
                    0, time_to_first_tool_ms
                ),  # Ensure non-negative
                "output_length": len(output_str),
                "semantic_cluster": semantic_cluster,
                "verbosity_ratio": compute_verbosity_ratio(
                    prompt_tokens, completion_tokens
                ),
                "task_input_hash": task_input_hash,  # SHA256 hash of input
                "output_structure_hash": output_structure_hash,  # SHA256 hash of output
                "raw_output": output_str[:5000],  # Truncate to 5000 chars
                "raw_prompt": raw_prompt[:5000],  # Truncate to 5000 chars
                "raw_prompt_full": raw_prompt_full,  # Phase 4: full text for blob storage
                "raw_output_full": raw_output_full,  # Phase 4: full text for blob storage
                "retry_count": retry_count,
                "sensitivity": None,
                "observation_tree_json": observation_tree_json,  # Phase 4: full tree
            }
        except Exception as e:
            logger.error(f"Failed to map LangFuse trace {trace.get('id')}: {e}")
            return None
