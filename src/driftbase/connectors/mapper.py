"""Schema mapping utilities for external traces."""

from __future__ import annotations

import json
from typing import Any

# Keywords that indicate escalation in agent output
ESCALATION_KEYWORDS = [
    "escalat",
    "transfer",
    "human agent",
    "supervisor",
    "unable to",
    "cannot help",
    "out of scope",
    "specialist",
    "need help",
    "can't handle",
]


def infer_semantic_cluster(output: str | None, error: bool) -> str:
    """
    Infer semantic cluster from output content.

    This is a heuristic approximation based on keyword matching.
    The developer can override by using @track() with explicit outcome labeling.

    Args:
        output: Agent output text
        error: Whether an error occurred

    Returns:
        Semantic cluster: "error", "escalated", "resolved", or "unknown"
    """
    if error:
        return "error"

    if not output:
        return "unknown"

    output_lower = output.lower()
    if any(kw in output_lower for kw in ESCALATION_KEYWORDS):
        return "escalated"

    return "resolved"


def compute_verbosity_ratio(prompt_tokens: int, completion_tokens: int) -> float:
    """
    Compute verbosity ratio from token counts.

    Args:
        prompt_tokens: Number of prompt tokens
        completion_tokens: Number of completion tokens

    Returns:
        Verbosity ratio (completion_tokens / prompt_tokens)
    """
    if prompt_tokens > 0:
        return completion_tokens / prompt_tokens
    return 0.0


def extract_tool_sequence(tool_observations: list[dict[str, Any]]) -> tuple[str, int]:
    """
    Extract tool sequence and count from tool observations.

    Args:
        tool_observations: List of tool observation dicts

    Returns:
        Tuple of (tool_sequence_json, tool_call_count)
        tool_sequence_json is a JSON array of tool names like ["tool_a", "tool_b"]
    """
    tool_names = []
    for obs in tool_observations:
        name = (
            obs.get("name")
            or obs.get("tool_name")
            or obs.get("function", {}).get("name")
        )
        if name:
            tool_names.append(str(name))

    return json.dumps(tool_names), len(tool_names)


def detect_retry_patterns(tool_observations: list[dict[str, Any]]) -> int:
    """
    Detect retry patterns in tool observations.

    Counts consecutive tool calls with the same tool name as potential retries.

    Args:
        tool_observations: List of tool observation dicts

    Returns:
        Number of detected retry iterations
    """
    if len(tool_observations) < 2:
        return 0

    retries = 0
    prev_tool = None

    for obs in tool_observations:
        tool_name = obs.get("name") or obs.get("tool_name")
        if tool_name and tool_name == prev_tool:
            retries += 1
        prev_tool = tool_name

    return retries
