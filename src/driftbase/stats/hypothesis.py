"""
Hypothesis testing and statistical significance for drift detection.

Provides statistical tests to determine if observed drift is statistically significant.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class StatisticalTest:
    """Results of a statistical significance test."""

    test_name: str
    """Name of the test (e.g., 'chi_squared', 't_test')."""

    p_value: float
    """P-value from the test."""

    statistic: float
    """Test statistic value."""

    significant: bool
    """Whether result is statistically significant at given alpha."""

    alpha: float
    """Significance level used (e.g., 0.05)."""

    degrees_of_freedom: int | None = None
    """Degrees of freedom for the test."""

    effect_size: float | None = None
    """Effect size measure (Cohen's d, Cramér's V, etc.)."""

    interpretation: str = ""
    """Human-readable interpretation of results."""


def chi_squared_test(
    baseline_counts: dict[str, int],
    current_counts: dict[str, int],
    alpha: float = 0.05,
) -> StatisticalTest:
    """
    Perform chi-squared test for independence on outcome distributions.

    Tests whether the distribution of outcomes differs significantly
    between baseline and current versions.

    Args:
        baseline_counts: Outcome counts for baseline (e.g., {"resolved": 80, "escalated": 20})
        current_counts: Outcome counts for current version
        alpha: Significance level (default 0.05)

    Returns:
        StatisticalTest with chi-squared results
    """
    # Get all unique outcomes
    all_outcomes = set(baseline_counts.keys()) | set(current_counts.keys())

    # Build contingency table
    baseline_totals = sum(baseline_counts.values())
    current_totals = sum(current_counts.values())

    if baseline_totals == 0 or current_totals == 0:
        return StatisticalTest(
            test_name="chi_squared",
            p_value=1.0,
            statistic=0.0,
            significant=False,
            alpha=alpha,
            degrees_of_freedom=0,
            interpretation="Insufficient data for test",
        )

    # Calculate chi-squared statistic
    chi_squared = 0.0
    for outcome in all_outcomes:
        baseline_obs = baseline_counts.get(outcome, 0)
        current_obs = current_counts.get(outcome, 0)

        # Expected counts assuming same distribution
        total_outcome = baseline_obs + current_obs
        baseline_exp = total_outcome * baseline_totals / (baseline_totals + current_totals)
        current_exp = total_outcome * current_totals / (baseline_totals + current_totals)

        # Add to chi-squared statistic (avoid division by zero)
        if baseline_exp > 0:
            chi_squared += (baseline_obs - baseline_exp) ** 2 / baseline_exp
        if current_exp > 0:
            chi_squared += (current_obs - current_exp) ** 2 / current_exp

    # Degrees of freedom
    df = len(all_outcomes) - 1

    # Calculate p-value using chi-squared distribution approximation
    # For simplicity, using a rough approximation
    # In production, you'd use scipy.stats.chi2.sf(chi_squared, df)
    p_value = _chi_squared_p_value_approx(chi_squared, df)

    # Calculate Cramér's V (effect size)
    n = baseline_totals + current_totals
    cramers_v = math.sqrt(chi_squared / n) if n > 0 else 0.0

    # Interpretation
    if p_value < alpha:
        interpretation = f"Outcome distributions differ significantly (p={p_value:.4f} < {alpha})"
    else:
        interpretation = f"No significant difference in outcome distributions (p={p_value:.4f} >= {alpha})"

    return StatisticalTest(
        test_name="chi_squared",
        p_value=p_value,
        statistic=chi_squared,
        significant=p_value < alpha,
        alpha=alpha,
        degrees_of_freedom=df,
        effect_size=cramers_v,
        interpretation=interpretation,
    )


def t_test(
    baseline_values: list[float],
    current_values: list[float],
    alpha: float = 0.05,
) -> StatisticalTest:
    """
    Perform independent samples t-test (Welch's t-test).

    Tests whether the means of two samples differ significantly.
    Commonly used for latency comparisons.

    Args:
        baseline_values: Values from baseline version (e.g., latencies)
        current_values: Values from current version
        alpha: Significance level (default 0.05)

    Returns:
        StatisticalTest with t-test results
    """
    n1 = len(baseline_values)
    n2 = len(current_values)

    if n1 < 2 or n2 < 2:
        return StatisticalTest(
            test_name="t_test",
            p_value=1.0,
            statistic=0.0,
            significant=False,
            alpha=alpha,
            interpretation="Insufficient data for test (need at least 2 samples per group)",
        )

    # Calculate means
    mean1 = sum(baseline_values) / n1
    mean2 = sum(current_values) / n2

    # Calculate variances
    var1 = sum((x - mean1) ** 2 for x in baseline_values) / (n1 - 1)
    var2 = sum((x - mean2) ** 2 for x in current_values) / (n2 - 1)

    # Welch's t-statistic
    if var1 / n1 + var2 / n2 == 0:
        t_stat = 0.0
    else:
        t_stat = (mean1 - mean2) / math.sqrt(var1 / n1 + var2 / n2)

    # Welch-Satterthwaite degrees of freedom
    if var1 > 0 and var2 > 0:
        df = (var1 / n1 + var2 / n2) ** 2 / (
            (var1 / n1) ** 2 / (n1 - 1) + (var2 / n2) ** 2 / (n2 - 1)
        )
    else:
        df = n1 + n2 - 2

    # Calculate p-value (two-tailed)
    p_value = _t_test_p_value_approx(abs(t_stat), df)

    # Calculate Cohen's d (effect size)
    if var1 > 0 or var2 > 0:
        pooled_std = math.sqrt(((n1 - 1) * var1 + (n2 - 1) * var2) / (n1 + n2 - 2))
        cohens_d = abs(mean1 - mean2) / pooled_std if pooled_std > 0 else 0.0
    else:
        cohens_d = 0.0

    # Interpretation
    if p_value < alpha:
        direction = "higher" if mean2 > mean1 else "lower"
        interpretation = (
            f"Means differ significantly (p={p_value:.4f} < {alpha}). "
            f"Current is {direction} than baseline."
        )
    else:
        interpretation = f"No significant difference in means (p={p_value:.4f} >= {alpha})"

    return StatisticalTest(
        test_name="t_test",
        p_value=p_value,
        statistic=t_stat,
        significant=p_value < alpha,
        alpha=alpha,
        degrees_of_freedom=int(df),
        effect_size=cohens_d,
        interpretation=interpretation,
    )


def bootstrap_confidence_interval(
    baseline_values: list[float],
    current_values: list[float],
    confidence_level: float = 0.95,
    n_bootstrap: int = 1000,
) -> tuple[float, float, float]:
    """
    Calculate bootstrap confidence interval for difference in means.

    Args:
        baseline_values: Baseline sample
        current_values: Current sample
        confidence_level: Confidence level (default 0.95 for 95% CI)
        n_bootstrap: Number of bootstrap samples (default 1000)

    Returns:
        Tuple of (mean_difference, lower_bound, upper_bound)
    """
    import random

    if not baseline_values or not current_values:
        return 0.0, 0.0, 0.0

    # Observed difference
    mean_baseline = sum(baseline_values) / len(baseline_values)
    mean_current = sum(current_values) / len(current_values)
    observed_diff = mean_current - mean_baseline

    # Bootstrap resampling
    bootstrap_diffs = []
    for _ in range(n_bootstrap):
        # Resample with replacement
        baseline_sample = [random.choice(baseline_values) for _ in range(len(baseline_values))]
        current_sample = [random.choice(current_values) for _ in range(len(current_values))]

        # Calculate difference in means
        bs_mean_baseline = sum(baseline_sample) / len(baseline_sample)
        bs_mean_current = sum(current_sample) / len(current_sample)
        bootstrap_diffs.append(bs_mean_current - bs_mean_baseline)

    # Sort and find percentiles
    bootstrap_diffs.sort()
    alpha = 1 - confidence_level
    lower_idx = int(alpha / 2 * n_bootstrap)
    upper_idx = int((1 - alpha / 2) * n_bootstrap)

    lower_bound = bootstrap_diffs[lower_idx] if lower_idx < len(bootstrap_diffs) else bootstrap_diffs[0]
    upper_bound = bootstrap_diffs[upper_idx] if upper_idx < len(bootstrap_diffs) else bootstrap_diffs[-1]

    return observed_diff, lower_bound, upper_bound


def _chi_squared_p_value_approx(chi_squared: float, df: int) -> float:
    """
    Approximate p-value for chi-squared test.

    This is a rough approximation. For production use, prefer scipy.stats.chi2.sf().
    """
    if df <= 0:
        return 1.0

    # Very rough approximation using normal approximation
    # chi^2 ~ N(df, 2*df) for large df
    if df > 30:
        z = (chi_squared - df) / math.sqrt(2 * df)
        return _normal_sf_approx(z)

    # For small df, use lookup table approximation
    # Critical values for df=1..10 at p=0.05
    critical_values = {
        1: 3.84,
        2: 5.99,
        3: 7.81,
        4: 9.49,
        5: 11.07,
        6: 12.59,
        7: 14.07,
        8: 15.51,
        9: 16.92,
        10: 18.31,
    }

    critical = critical_values.get(df, 3.84)
    if chi_squared > critical:
        return 0.01  # Rough estimate: p < 0.05
    else:
        return 0.10  # Rough estimate: p > 0.05


def _t_test_p_value_approx(t_stat: float, df: float) -> float:
    """
    Approximate two-tailed p-value for t-test.

    This is a rough approximation. For production use, prefer scipy.stats.t.sf().
    """
    if df <= 0:
        return 1.0

    # For large df, t-distribution approaches normal
    if df > 30:
        return 2 * _normal_sf_approx(t_stat)

    # Rough approximation for small df
    # Critical value for two-tailed test at p=0.05 is approximately 2.0-2.1
    if t_stat > 2.5:
        return 0.01
    elif t_stat > 2.0:
        return 0.05
    elif t_stat > 1.5:
        return 0.10
    else:
        return 0.20


def _normal_sf_approx(z: float) -> float:
    """
    Approximate survival function (1 - CDF) for standard normal.

    This is a rough approximation. For production use, prefer scipy.stats.norm.sf().
    """
    # Use error function approximation
    # P(Z > z) ≈ 0.5 * erfc(z / sqrt(2))

    # Simple bounds-based approximation
    if z > 3:
        return 0.001
    elif z > 2.5:
        return 0.01
    elif z > 2.0:
        return 0.025
    elif z > 1.96:
        return 0.05
    elif z > 1.0:
        return 0.16
    else:
        return 0.50


def analyze_significance(
    baseline_runs: list[dict[str, Any]],
    current_runs: list[dict[str, Any]],
    alpha: float = 0.05,
) -> dict[str, StatisticalTest]:
    """
    Perform comprehensive statistical significance analysis on drift.

    Args:
        baseline_runs: Runs from baseline version
        current_runs: Runs from current version
        alpha: Significance level (default 0.05)

    Returns:
        Dictionary of test results:
            {
                "outcome_distribution": StatisticalTest,  # Chi-squared
                "latency": StatisticalTest,  # t-test
                "error_rate": StatisticalTest,  # Proportion test
            }
    """
    results = {}

    # 1. Test outcome distribution (chi-squared)
    from collections import Counter

    baseline_outcomes = Counter(r.get("semantic_cluster", "unknown") for r in baseline_runs)
    current_outcomes = Counter(r.get("semantic_cluster", "unknown") for r in current_runs)

    results["outcome_distribution"] = chi_squared_test(
        dict(baseline_outcomes), dict(current_outcomes), alpha
    )

    # 2. Test latency (t-test)
    baseline_latencies = [
        float(r.get("latency_ms", 0))
        for r in baseline_runs
        if r.get("latency_ms") and float(r.get("latency_ms", 0)) > 0
    ]
    current_latencies = [
        float(r.get("latency_ms", 0))
        for r in current_runs
        if r.get("latency_ms") and float(r.get("latency_ms", 0)) > 0
    ]

    if baseline_latencies and current_latencies:
        results["latency"] = t_test(baseline_latencies, current_latencies, alpha)

    # 3. Test error rate (proportion test approximated by chi-squared)
    baseline_errors = sum(1 for r in baseline_runs if r.get("error_count", 0) > 0)
    baseline_success = len(baseline_runs) - baseline_errors

    current_errors = sum(1 for r in current_runs if r.get("error_count", 0) > 0)
    current_success = len(current_runs) - current_errors

    results["error_rate"] = chi_squared_test(
        {"error": baseline_errors, "success": baseline_success},
        {"error": current_errors, "success": current_success},
        alpha,
    )

    return results
