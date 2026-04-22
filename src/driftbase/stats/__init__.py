"""
Statistical analysis module for Driftbase.
"""

from __future__ import annotations

from driftbase.stats.attribution import (
    compute_dimension_attribution,
    compute_marginal_contribution,
)
from driftbase.stats.dimension_ci import DimensionCI, compute_dimension_cis
from driftbase.stats.hypothesis import (
    StatisticalTest,
    analyze_significance,
    bootstrap_confidence_interval,
    chi_squared_test,
    t_test,
)
from driftbase.stats.mde import compute_mde
from driftbase.stats.power_forecast import forecast_runs_needed

__all__ = [
    "DimensionCI",
    "StatisticalTest",
    "analyze_significance",
    "bootstrap_confidence_interval",
    "chi_squared_test",
    "compute_dimension_attribution",
    "compute_dimension_cis",
    "compute_marginal_contribution",
    "compute_mde",
    "forecast_runs_needed",
    "t_test",
]
