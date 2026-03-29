"""
Behavioral budgets: user-defined acceptable ranges per dimension.

Budgets are hard limits on absolute dimension values within a single version.
Separate from drift scoring (which compares two versions statistically).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

# Mapping from budget keys to dimension names
BUDGET_KEY_TO_DIMENSION = {
    "max_p95_latency": "latency_p95",
    "max_p50_latency": "latency_p50",
    "max_error_rate": "error_rate",
    "max_escalation_rate": "decision_drift",  # escalation outcome proportion
    "min_resolution_rate": "decision_drift",  # resolution outcome proportion
    "max_retry_rate": "retry_rate",
    "max_loop_depth": "loop_depth",
    "max_verbosity_ratio": "verbosity_ratio",
    "max_output_length": "output_length",
    "max_time_to_first_tool": "time_to_first_tool",
}


@dataclass
class BudgetConfig:
    """Parsed and validated budget definition."""

    limits: dict[str, float]  # budget_key -> limit value


@dataclass
class BudgetBreach:
    """A recorded breach event."""

    agent_id: str
    version: str
    dimension: str
    budget_key: str
    limit: float
    actual: float  # rolling average value that triggered breach
    direction: str  # "above" | "below"
    run_count: int  # size of rolling window used
    breached_at: datetime


def parse_budget(raw: dict[str, Any]) -> BudgetConfig:
    """
    Parse and validate budget definition at decoration time.

    Raises ValueError on unknown keys (fail fast at setup, not runtime).

    Args:
        raw: Raw budget dict from @track(budget={...})

    Returns:
        Validated BudgetConfig

    Raises:
        ValueError: If any key is unknown
    """
    if not raw:
        return BudgetConfig(limits={})

    limits = {}
    for key, value in raw.items():
        if key not in BUDGET_KEY_TO_DIMENSION:
            raise ValueError(
                f"Unknown budget key: '{key}'. "
                f"Supported keys: {', '.join(sorted(BUDGET_KEY_TO_DIMENSION.keys()))}"
            )
        try:
            limits[key] = float(value)
        except (ValueError, TypeError) as e:
            raise ValueError(
                f"Budget key '{key}' must be numeric, got {value!r}"
            ) from e

    return BudgetConfig(limits=limits)


def check_budget(
    budget: BudgetConfig, runs: list[dict[str, Any]], window: int
) -> list[BudgetBreach]:
    """
    Check if rolling averages breach budget limits. Pure function, no SQLite access.

    Minimum runs before breach detection: 5. Below 5 runs, returns empty list.

    Args:
        budget: Validated budget config
        runs: List of run dicts (most recent first)
        window: Rolling window size (e.g., 10)

    Returns:
        List of BudgetBreach objects (empty if no breaches)
    """
    if len(runs) < 5:
        return []

    if not budget.limits:
        return []

    # Use only the last N runs for rolling window
    window_runs = runs[:window]
    n = len(window_runs)

    breaches = []

    for budget_key, limit in budget.limits.items():
        dimension = BUDGET_KEY_TO_DIMENSION[budget_key]

        # Compute rolling average for this dimension
        avg = _compute_rolling_average(window_runs, dimension, budget_key)

        if avg is None:
            continue

        # Check if limit is breached
        direction = None
        if budget_key.startswith("max_") and avg > limit:
            direction = "above"
        elif budget_key.startswith("min_") and avg < limit:
            direction = "below"

        if direction:
            # Extract agent_id and version from first run
            agent_id = window_runs[0].get("session_id", "unknown")
            version = window_runs[0].get("deployment_version", "unknown")

            breaches.append(
                BudgetBreach(
                    agent_id=agent_id,
                    version=version,
                    dimension=dimension,
                    budget_key=budget_key,
                    limit=limit,
                    actual=avg,
                    direction=direction,
                    run_count=n,
                    breached_at=datetime.utcnow(),
                )
            )

    return breaches


def _compute_rolling_average(
    runs: list[dict[str, Any]], dimension: str, budget_key: str
) -> float | None:
    """Compute rolling average for a dimension from runs."""
    values = []

    for run in runs:
        if dimension == "latency_p95" or dimension == "latency_p50":
            val = run.get("latency_ms", 0)
            values.append(val)
        elif dimension == "error_rate":
            error_count = run.get("error_count", 0)
            values.append(1.0 if error_count > 0 else 0.0)
        elif dimension == "retry_rate":
            retry_count = run.get("retry_count", 0)
            values.append(float(retry_count))
        elif dimension == "loop_depth":
            loop_count = run.get("loop_count", 0)
            values.append(float(loop_count))
        elif dimension == "verbosity_ratio":
            verbosity_ratio = run.get("verbosity_ratio", 0.0)
            values.append(verbosity_ratio)
        elif dimension == "output_length":
            output_length = run.get("output_length", 0)
            values.append(float(output_length))
        elif dimension == "time_to_first_tool":
            time_to_first = run.get("time_to_first_tool_ms", 0)
            values.append(float(time_to_first))
        elif dimension == "decision_drift":
            # For escalation/resolution rate, check semantic_cluster
            semantic_cluster = run.get("semantic_cluster", "")
            if "escalation" in budget_key.lower():
                values.append(1.0 if semantic_cluster == "escalated" else 0.0)
            elif "resolution" in budget_key.lower():
                values.append(1.0 if semantic_cluster == "resolved" else 0.0)

    if not values:
        return None

    return sum(values) / len(values)


def format_breach_warning(breach: BudgetBreach) -> str:
    """Format a single plain-English warning line for console output."""
    direction_text = "exceeded" if breach.direction == "above" else "fell below"
    delta_pct = (
        ((breach.actual - breach.limit) / breach.limit * 100) if breach.limit > 0 else 0
    )
    delta_sign = "+" if delta_pct > 0 else ""

    # Format the dimension-specific unit
    if "latency" in breach.budget_key:
        limit_str = f"{breach.limit:.1f}s"
        actual_str = f"{breach.actual / 1000:.1f}s"  # Convert ms to s
    elif "rate" in breach.budget_key or "ratio" in breach.budget_key:
        limit_str = f"{breach.limit * 100:.1f}%"
        actual_str = f"{breach.actual * 100:.1f}%"
    else:
        limit_str = f"{breach.limit:.1f}"
        actual_str = f"{breach.actual:.1f}"

    return (
        f"Budget breach: {breach.budget_key} {direction_text} for {breach.version}\n"
        f"            Limit: {limit_str} | Actual (rolling n={breach.run_count}): {actual_str} | {delta_sign}{abs(delta_pct):.0f}% over limit"
    )
