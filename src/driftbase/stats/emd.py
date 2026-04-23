"""Earth Mover's Distance (Wasserstein) for latency distribution comparison."""

from __future__ import annotations

import logging
from typing import Any

from scipy.stats import wasserstein_distance

logger = logging.getLogger(__name__)


def compute_latency_emd(
    baseline: list[dict[str, Any]], current: list[dict[str, Any]]
) -> float:
    """
    Compute raw Earth Mover's Distance between latency distributions.

    Args:
        baseline: Baseline run dicts (must have 'latency_ms' field)
        current: Current run dicts (must have 'latency_ms' field)

    Returns:
        Raw EMD in milliseconds (unnormalized distance between distributions)
        Returns 0.0 if either distribution is empty
    """
    if not baseline or not current:
        return 0.0

    baseline_latencies = [
        run.get("latency_ms", 0) for run in baseline if "latency_ms" in run
    ]
    current_latencies = [
        run.get("latency_ms", 0) for run in current if "latency_ms" in run
    ]

    if not baseline_latencies or not current_latencies:
        return 0.0

    emd = wasserstein_distance(baseline_latencies, current_latencies)
    return float(emd)


def compute_latency_emd_signal(
    baseline: list[dict[str, Any]], current: list[dict[str, Any]]
) -> float:
    """
    Compute normalized EMD signal for drift scoring.

    Args:
        baseline: Baseline run dicts (must have 'latency_ms' field)
        current: Current run dicts (must have 'latency_ms' field)

    Returns:
        Normalized signal in [0, 1] where:
        - 0.0 = identical distributions
        - 1.0 = completely different distributions
        Uses sigmoid normalization: 1 / (1 + exp(-k * (emd - c)))

    Note:
        Normalization calibrated for typical latency distributions (100-5000ms range).
        EMD of 500ms → ~0.37 signal, 1000ms → ~0.73 signal, 2000ms → ~0.95 signal.
    """
    emd = compute_latency_emd(baseline, current)

    if emd == 0.0:
        return 0.0

    # Sigmoid normalization: steeper response for mid-range EMD
    # k=0.002, c=500 calibrates for typical latency shifts
    k = 0.002
    c = 500.0
    signal = 1.0 / (1.0 + pow(2.718281828, -k * (emd - c)))

    return min(1.0, max(0.0, signal))
