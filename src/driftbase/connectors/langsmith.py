"""LangSmith trace connector."""

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
    import httpx

    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False


def _build_observation_tree(run: dict, child_runs: list[dict]) -> dict | None:
    """
    Build hierarchical observation tree from LangSmith run and child runs.

    Args:
        run: Root run dict from LangSmith
        child_runs: List of child run dicts

    Returns:
        Tree structure with each node containing:
        - id, type, name, inputs, outputs, metadata
        - children: list of child nodes

    Note:
        Returns None if tree build fails.
        Preserves ALL run types (llm, chain, tool, etc).
    """
    try:
        # Index child runs by ID for fast lookup
        runs_by_id = {child.get("id"): child for child in child_runs if child.get("id")}

        # Build parent->children mapping
        children_map: dict[str | None, list[dict]] = {}
        for child in child_runs:
            parent_id = child.get("parent_run_id")
            if parent_id not in children_map:
                children_map[parent_id] = []
            children_map[parent_id].append(child)

        def build_node(run_obj: dict) -> dict:
            """Recursively build tree node with children."""
            node = {
                "id": run_obj.get("id"),
                "type": run_obj.get("run_type"),
                "name": run_obj.get("name"),
                "inputs": run_obj.get("inputs"),
                "outputs": run_obj.get("outputs"),
                "metadata": run_obj.get("extra", {}).get("metadata", {}),
                "start_time": run_obj.get("start_time"),
                "end_time": run_obj.get("end_time"),
                "error": run_obj.get("error"),
            }

            # Add children recursively
            run_id = run_obj.get("id")
            if run_id and run_id in children_map:
                node["children"] = [build_node(child) for child in children_map[run_id]]
            else:
                node["children"] = []

            return node

        # Build tree from root run
        root_node = build_node(run)

        # Add children to root
        root_id = run.get("id")
        if root_id and root_id in children_map:
            root_node["children"] = [
                build_node(child) for child in children_map[root_id]
            ]

        return root_node

    except Exception as e:
        logger.warning(f"Failed to build observation tree: {e}")
        return None


class LangSmithConnector(TraceConnector):
    """Connector for importing traces from LangSmith."""

    def __init__(self):
        if not HTTPX_AVAILABLE:
            raise ImportError("httpx package not installed. Run: pip install httpx")

        api_key = os.getenv("LANGSMITH_API_KEY") or os.getenv("LANGCHAIN_API_KEY")
        if not api_key:
            raise ValueError(
                "LANGSMITH_API_KEY or LANGCHAIN_API_KEY environment variable must be set"
            )

        self.api_key = api_key
        self.base_url = os.getenv(
            "LANGSMITH_ENDPOINT", "https://api.smith.langchain.com"
        )
        self.headers = {"x-api-key": api_key}

    def validate_credentials(self) -> bool:
        """Check if API key is valid."""
        try:
            # Try to list projects (minimal API call)
            with httpx.Client(timeout=10.0) as client:
                response = client.get(
                    f"{self.base_url}/sessions",
                    headers=self.headers,
                    params={"limit": 1},
                )
                return response.status_code == 200
        except Exception as e:
            logger.debug(f"LangSmith credential validation failed: {e}")
            return False

    def list_projects(self) -> list[dict[str, Any]]:
        """
        List available projects (LangSmith calls them "sessions").
        Returns [{"name": str, "run_count": int}] sorted by run_count desc.
        Returns [] on any error. Never raises.
        """
        try:
            with httpx.Client(timeout=10.0) as client:
                response = client.get(
                    f"{self.base_url}/sessions",
                    headers=self.headers,
                    params={"limit": 100},
                )
                response.raise_for_status()
                sessions = response.json()

                projects = []
                for session in sessions:
                    projects.append(
                        {
                            "name": session.get("name", "unknown"),
                            "run_count": session.get("run_count", 0),
                        }
                    )

                # Sort by run_count descending
                projects.sort(key=lambda x: x["run_count"], reverse=True)
                return projects
        except Exception as e:
            logger.debug(f"Failed to list LangSmith projects: {e}")
            return []

    def fetch_traces(self, config: ConnectorConfig) -> list[dict]:
        """Fetch runs from LangSmith."""
        try:
            # Build fetch parameters
            params: dict[str, Any] = {
                "limit": min(config.limit, 100),  # LangSmith max is 100
            }

            # Add project filter (LangSmith uses "session")
            if config.project_name:
                params["session"] = config.project_name

            # Add time filter if specified
            if config.since:
                params["start_time"] = config.since.isoformat()

            # Fetch runs
            with httpx.Client(timeout=30.0) as client:
                response = client.get(
                    f"{self.base_url}/runs",
                    headers=self.headers,
                    params=params,
                )
                response.raise_for_status()
                runs = response.json()

                # Filter to root runs only (parent_run_id is None)
                if isinstance(runs, list):
                    root_runs = [r for r in runs if r.get("parent_run_id") is None]

                    # Fetch child runs for each root run (for tool sequence)
                    for run in root_runs:
                        run_id = run.get("id")
                        if run_id:
                            try:
                                child_response = client.get(
                                    f"{self.base_url}/runs",
                                    headers=self.headers,
                                    params={"parent_run_id": run_id, "limit": 100},
                                )
                                if child_response.status_code == 200:
                                    run["child_runs"] = child_response.json()
                            except Exception as e:
                                logger.warning(
                                    f"Failed to fetch child runs for {run_id}: {e}"
                                )
                                run["child_runs"] = []

                    return root_runs

                return []
        except Exception as e:
            logger.error(f"Failed to fetch LangSmith runs: {e}")
            return []

    def map_trace(self, run: dict, config: ConnectorConfig) -> dict | None:
        """Map LangSmith run to Driftbase schema."""
        try:
            # Extract metadata from extra field
            extra = run.get("extra", {})
            metadata = extra.get("metadata", {})

            # Extract version
            # Track version source for transparency
            version_source = "none"
            version = None

            if metadata.get("version"):
                version = metadata.get("version")
                version_source = "tag"
            elif metadata.get("deployment_version"):
                version = metadata.get("deployment_version")
                version_source = "tag"
            elif os.getenv("DRIFTBASE_VERSION"):
                version = os.getenv("DRIFTBASE_VERSION")
                version_source = "env"
            elif run.get("name"):
                version = run.get("name")
                version_source = "tag"  # LangSmith uses run name as version
            else:
                version = "unknown"
                version_source = "none"

            # Extract environment
            environment = metadata.get("environment", "production")

            # Extract model name from multiple possible locations
            invocation_params = extra.get("invocation_params", {})
            model = (
                invocation_params.get("model_name")
                or metadata.get("ls_model_name")
                or metadata.get("model")
                or "unknown"
            )

            # Parse timestamps
            start_time_str = run.get("start_time")
            end_time_str = run.get("end_time")

            if start_time_str:
                if isinstance(start_time_str, str):
                    started_at = datetime.fromisoformat(
                        start_time_str.replace("Z", "+00:00")
                    )
                else:
                    started_at = start_time_str
            else:
                started_at = datetime.now(tz=timezone.utc)

            if end_time_str:
                if isinstance(end_time_str, str):
                    completed_at = datetime.fromisoformat(
                        end_time_str.replace("Z", "+00:00")
                    )
                else:
                    completed_at = end_time_str
            else:
                completed_at = started_at

            # Latency conversion: LangSmith returns in seconds, convert to ms
            latency_seconds = run.get("latency", 0) or 0
            latency_ms = int(float(latency_seconds) * 1000)

            # Token counts
            prompt_tokens = run.get("prompt_tokens", 0) or 0
            completion_tokens = run.get("completion_tokens", 0) or 0

            # Extract input and output
            inputs = run.get("inputs")
            outputs = run.get("outputs")

            raw_prompt = json.dumps(inputs) if inputs else ""
            output_str = json.dumps(outputs) if outputs else ""

            # Store full versions for blob storage (Phase 4)
            raw_prompt_full = raw_prompt
            raw_output_full = output_str

            # Compute hashes
            task_input_hash = compute_hash(raw_prompt)
            output_structure_hash = compute_hash(output_str)

            # Error detection
            error = bool(run.get("error"))

            # Extract tool calls from child_runs
            child_runs = run.get("child_runs", [])

            # Build observation tree first (Phase 4 - needed for enhanced tool extraction)
            observation_tree = _build_observation_tree(run, child_runs)

            tool_observations = [
                child for child in child_runs if child.get("run_type") == "tool"
            ]

            # Legacy extraction (baseline)
            legacy_tool_names = []
            for child in tool_observations:
                tool_name = child.get("name", "unknown_tool")
                legacy_tool_names.append(tool_name)

            # Tree-based extraction (Phase 4 additive enhancement)
            tree_tools = extract_tools_from_tree(observation_tree)

            # Merge: start with legacy, then add any new tools from tree
            all_tools = legacy_tool_names.copy()

            # Add tree tools that aren't already in legacy (preserves order)
            for tool in tree_tools:
                if tool not in all_tools:
                    all_tools.append(tool)

            tool_sequence_json = json.dumps(all_tools)
            tool_call_count = len(all_tools)

            # Detect retry patterns
            retry_count = detect_retry_patterns(tool_observations)

            # Infer loop count from child run structure
            loop_count = max(
                1, len([c for c in child_runs if c.get("run_type") in ["chain", "llm"]])
            )

            # Compute time to first tool
            time_to_first_tool_ms = 0
            if tool_observations and started_at:
                first_tool = min(
                    tool_observations,
                    key=lambda t: t.get("start_time", "9999-12-31"),
                )
                first_tool_start = first_tool.get("start_time")
                if first_tool_start:
                    if isinstance(first_tool_start, str):
                        first_tool_dt = datetime.fromisoformat(
                            first_tool_start.replace("Z", "+00:00")
                        )
                    else:
                        first_tool_dt = first_tool_start
                    time_to_first_tool_ms = int(
                        (first_tool_dt - started_at).total_seconds() * 1000
                    )

            # Semantic cluster
            semantic_cluster = infer_semantic_cluster(output_str, error)

            # Session ID
            session_id = run.get("session_id", run.get("id", "unknown"))[:16]
            if config.agent_id:
                session_id = config.agent_id

            # Serialize observation tree (already built above for tool extraction)
            observation_tree_json = (
                json.dumps(observation_tree) if observation_tree else None
            )

            return {
                "id": str(uuid4()),  # Generate new UUID for Driftbase
                "external_id": str(run.get("id", str(uuid4()))),
                "source": "langsmith",
                "ingestion_source": "connector",  # Track ingestion method
                "session_id": session_id,
                "deployment_version": version,
                "version_source": version_source,  # Track version resolution source
                "environment": environment,
                "model": model,
                "started_at": started_at,
                "completed_at": completed_at,
                "latency_ms": latency_ms,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "error_count": 1 if error else 0,
                "tool_sequence": tool_sequence_json,
                "tool_call_sequence": tool_sequence_json,
                "tool_call_count": tool_call_count,
                "loop_count": loop_count,
                "time_to_first_tool_ms": max(0, time_to_first_tool_ms),
                "output_length": len(output_str),
                "semantic_cluster": semantic_cluster,
                "verbosity_ratio": compute_verbosity_ratio(
                    prompt_tokens, completion_tokens
                ),
                "task_input_hash": task_input_hash,
                "output_structure_hash": output_structure_hash,
                "raw_output": output_str[:5000],  # Truncate to 5000 chars
                "raw_prompt": raw_prompt[:5000],  # Truncate to 5000 chars
                "raw_prompt_full": raw_prompt_full,  # Phase 4: full text for blob storage
                "raw_output_full": raw_output_full,  # Phase 4: full text for blob storage
                "retry_count": retry_count,
                "sensitivity": None,
                "observation_tree_json": observation_tree_json,  # Phase 4: full tree
            }
        except Exception as e:
            logger.error(f"Failed to map LangSmith run {run.get('id')}: {e}")
            return None
