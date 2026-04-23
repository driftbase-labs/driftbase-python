"""N-gram analysis for tool sequences."""

from __future__ import annotations

import json
import logging

import numpy as np
from scipy.spatial.distance import jensenshannon

logger = logging.getLogger(__name__)


def compute_bigrams(tool_sequence: str) -> list[tuple[str, str]]:
    """
    Extract consecutive tool pairs from a tool sequence.

    Args:
        tool_sequence: Serialized JSON list of tool names (e.g., '["search", "read"]')

    Returns:
        List of consecutive pairs: [("search", "read"), ("read", "write")]
        Empty list for single-tool or empty sequences
    """
    if not tool_sequence:
        return []

    try:
        tools = json.loads(tool_sequence)
    except (json.JSONDecodeError, TypeError):
        logger.debug(f"Invalid tool_sequence format: {tool_sequence}")
        return []

    if not isinstance(tools, list) or len(tools) < 2:
        return []

    return [(tools[i], tools[i + 1]) for i in range(len(tools) - 1)]


def compute_bigram_distribution(tool_sequences: list[str]) -> dict[str, float]:
    """
    Compute frequency distribution of bigrams across tool sequences.

    Args:
        tool_sequences: List of serialized tool_sequence strings

    Returns:
        Dict mapping bigram string repr to probability.
        Example: {"('search', 'read')": 0.4, "('read', 'write')": 0.6}
    """
    if not tool_sequences:
        return {}

    bigram_counts: dict[str, int] = {}
    total_bigrams = 0

    for seq in tool_sequences:
        bigrams = compute_bigrams(seq)
        for bigram in bigrams:
            key = str(bigram)
            bigram_counts[key] = bigram_counts.get(key, 0) + 1
            total_bigrams += 1

    if total_bigrams == 0:
        return {}

    return {k: v / total_bigrams for k, v in bigram_counts.items()}


def compute_bigram_jsd(
    baseline_dist: dict[str, float], current_dist: dict[str, float]
) -> float:
    """
    Compute Jensen-Shannon divergence between two bigram distributions.

    Args:
        baseline_dist: Baseline bigram distribution
        current_dist: Current bigram distribution

    Returns:
        JSD in [0, 1] (0 = identical, 1 = completely different)
        Returns 0.0 if either distribution is empty
    """
    if not baseline_dist or not current_dist:
        return 0.0

    # Get union of all bigrams
    all_bigrams = sorted(set(baseline_dist.keys()) | set(current_dist.keys()))

    if not all_bigrams:
        return 0.0

    # Build probability vectors (0 for missing bigrams)
    p = np.array([baseline_dist.get(bg, 0.0) for bg in all_bigrams])
    q = np.array([current_dist.get(bg, 0.0) for bg in all_bigrams])

    # Normalize to ensure they sum to 1 (handle floating point errors)
    p_sum = p.sum()
    q_sum = q.sum()
    if p_sum > 0:
        p = p / p_sum
    if q_sum > 0:
        q = q / q_sum

    # Compute Jensen-Shannon distance (sqrt of divergence)
    # jensenshannon returns distance in [0, 1], not divergence in [0, inf]
    jsd = float(jensenshannon(p, q))

    return jsd
