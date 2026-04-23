"""Schema mapping utilities for external traces."""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

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


def compute_hash(text: str | None) -> str:
    """
    Compute SHA256 hash for fingerprinting.

    Args:
        text: Text to hash

    Returns:
        First 16 characters of SHA256 hash (64-bit fingerprint)

    Note:
        The original text (raw_prompt, raw_output) is stored locally in SQLite.
        For OSS users, this is fine — data never leaves their machine.

        ⚠️  PRIVACY WARNING: raw_prompt may contain PII. Never transmit without scrubbing.
        Cloud handles this via the Presidio pipeline in driftbase-cloud.
        Local-only usage is safe, but if building integrations that send data elsewhere,
        you MUST implement PII detection/removal before transmission.
    """
    if not text:
        return hashlib.sha256(b"").hexdigest()[:16]
    return hashlib.sha256(text.encode()).hexdigest()[:16]


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


def extract_tools_from_tree(tree: dict | None) -> list[str]:
    """
    Extract all tool names from observation tree (Phase 4 additive extraction).

    Recursively walks the tree and extracts tool names from ALL node types
    (generation, span, event, etc.), not just generations.

    Args:
        tree: Observation tree dict with structure:
            {"id": str, "type": str, "name": str, "children": [...]}

    Returns:
        List of tool names in execution order

    Note:
        This is ADDITIVE - finds MORE tools than legacy extraction.
        If tree is None or extraction fails, returns empty list (fallback to legacy).
    """
    if not tree:
        return []

    tools = []

    def walk(node: dict) -> None:
        """Recursively walk tree and extract tools."""
        if not isinstance(node, dict):
            return

        # Extract tool name from node
        # Check multiple possible fields for tool identification
        node_type = node.get("type", "")
        node_name = node.get("name", "")

        # Tool indicators:
        # 1. type == "tool" (explicit tool calls)
        # 2. type == "generation" with tool-like name
        # 3. type == "span" with tool-like name (e.g., "search", "write", "bash")
        is_tool = False
        tool_name = None

        if node_type == "tool":
            # Explicit tool
            is_tool = True
            tool_name = node_name
        elif node_type in ("generation", "span") and node_name:
            # Check if name looks like a tool (not "llm", "chain", etc.)
            lower_name = node_name.lower()
            # Common non-tool names to skip
            skip_names = {"llm", "chain", "agent", "root", "trace", "trace_root"}
            if lower_name not in skip_names and not lower_name.startswith("llm"):
                is_tool = True
                tool_name = node_name

        if is_tool and tool_name:
            tools.append(str(tool_name))

        # Recursively process children
        children = node.get("children", [])
        if isinstance(children, list):
            for child in children:
                walk(child)

    try:
        walk(tree)
    except Exception as e:
        logger.debug(f"Failed to extract tools from tree: {e}")
        return []

    return tools


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
