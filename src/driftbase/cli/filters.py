"""
Shared filter utilities for CLI commands.
"""

from __future__ import annotations

from datetime import datetime, timedelta


def parse_smart_time_filter(filter_value: str) -> int | None:
    """
    Parse smart time filters into hours.

    Args:
        filter_value: One of 'today', 'yesterday', 'this-week', 'last-week'

    Returns:
        Number of hours to look back, or None if invalid
    """
    if filter_value == "today":
        return 24
    elif filter_value == "yesterday":
        # Yesterday means: 24-48 hours ago (would need date range, return 48 for now)
        return 48
    elif filter_value == "this-week":
        # Current week (7 days)
        return 24 * 7
    elif filter_value == "last-week":
        # Previous week (14 days total to cover last week)
        return 24 * 14
    elif filter_value == "this-month":
        return 24 * 30
    else:
        return None


def parse_quality_filter(
    filter_value: str,
) -> dict[str, int | list[str] | None]:
    """
    Parse quality filters into query parameters.

    Args:
        filter_value: One of 'errors-only', 'slow', 'fast', 'high-cost'

    Returns:
        Dict with filter parameters (outcomes, min_latency, max_latency, etc.)
    """
    filters = {}

    if filter_value == "errors-only":
        filters["outcomes"] = ["error"]
        filters["min_error_count"] = 1
    elif filter_value == "slow":
        # Slow = latency > 1 second
        filters["min_latency_ms"] = 1000
    elif filter_value == "fast":
        # Fast = latency < 100ms
        filters["max_latency_ms"] = 100
    elif filter_value == "high-cost":
        # High cost = runs with many tokens (rough heuristic: > 10k tokens)
        filters["min_prompt_tokens"] = 10000
    elif filter_value == "production":
        filters["environment"] = "production"
    elif filter_value == "staging":
        filters["environment"] = "staging"

    return filters


def smart_filter_to_hours(smart_filter: str | None) -> int | None:
    """Convert smart filter to hours for backend queries."""
    if not smart_filter:
        return None
    return parse_smart_time_filter(smart_filter)


def apply_quality_filter_to_runs(runs: list[dict], quality_filter: str) -> list[dict]:
    """
    Apply quality filter to a list of runs (for backends that don't support filtering).

    Args:
        runs: List of run dicts
        quality_filter: Quality filter name

    Returns:
        Filtered list of runs
    """
    filters = parse_quality_filter(quality_filter)

    filtered = runs

    # Filter by outcomes
    if "outcomes" in filters:
        filtered = [
            r for r in filtered if r.get("semantic_cluster") in filters["outcomes"]
        ]

    # Filter by error count
    if "min_error_count" in filters:
        filtered = [
            r
            for r in filtered
            if r.get("error_count", 0) >= filters["min_error_count"]
        ]

    # Filter by latency
    if "min_latency_ms" in filters:
        filtered = [
            r
            for r in filtered
            if r.get("latency_ms", 0) >= filters["min_latency_ms"]
        ]

    if "max_latency_ms" in filters:
        filtered = [
            r
            for r in filtered
            if r.get("latency_ms", 0) <= filters["max_latency_ms"]
        ]

    # Filter by environment
    if "environment" in filters:
        filtered = [
            r for r in filtered if r.get("environment") == filters["environment"]
        ]

    return filtered
