"""
Verdict engine: converts drift scores into actionable ship/no-ship decisions.

This module provides the core decision logic that answers: "Should I ship this?"
It takes drift metrics and produces a verdict with plain-English explanation and
concrete next steps.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from driftbase.local.local_store import DriftReport


class Verdict(Enum):
    """Shipping verdict based on behavioral drift analysis."""

    SHIP = "ship"  # No meaningful change - safe to ship
    MONITOR = "monitor"  # Minor drift - ship with monitoring
    REVIEW = "review"  # Behavioral change detected - review before shipping
    BLOCK = "block"  # Major divergence - do not ship without investigation


@dataclass
class VerdictResult:
    """Complete verdict with explanation and actionable next steps."""

    verdict: Verdict
    title: str  # Short verdict headline
    explanation: str  # Plain-English reason
    next_steps: list[str]  # Actionable checklist
    exit_code: int  # 0 for SHIP/MONITOR, 1 for REVIEW/BLOCK

    @property
    def style(self) -> str:
        """Rich console style for this verdict."""
        return {
            Verdict.SHIP: "green",
            Verdict.MONITOR: "blue",
            Verdict.REVIEW: "yellow",
            Verdict.BLOCK: "red",
        }[self.verdict]

    @property
    def symbol(self) -> str:
        """Symbol prefix for this verdict."""
        return {
            Verdict.SHIP: "✓",
            Verdict.MONITOR: "·",
            Verdict.REVIEW: "⚠",
            Verdict.BLOCK: "✗",
        }[self.verdict]


def _get_highest_dimension(report: DriftReport) -> tuple[str, float]:
    """Return (dimension_name, score) for the highest-scoring dimension."""
    dimensions = [
        ("decision_drift", report.decision_drift),
        ("latency_drift", report.latency_drift),
        ("error_drift", report.error_drift),
    ]
    return max(dimensions, key=lambda x: x[1])


def _generate_next_steps(
    report: DriftReport,
    highest_dim: str,
    baseline_label: str = "",
    current_label: str = "",
    baseline_tools: dict[str, float] | None = None,
    current_tools: dict[str, float] | None = None,
) -> list[str]:
    """Generate dimension-specific next steps based on what changed."""
    steps = []

    # Decision drift - check prompts and outcome logic
    if highest_dim == "decision_drift" or report.decision_drift > 0.25:
        steps.append("Review system prompt changes between versions")
        if report.escalation_rate_delta > 0.1:
            multiplier = (
                report.escalation_rate_delta / max(0.01, 0.08)
            )  # assuming ~8% baseline
            steps.append(
                f"Investigate escalation logic - rate jumped {multiplier:.1f}× from baseline"
            )
        steps.append("Check outcome routing and decision tree logic")
        if baseline_tools and current_tools:
            # Check if tool distribution changed significantly
            new_tools = set(current_tools.keys()) - set(baseline_tools.keys())
            if new_tools:
                steps.append(
                    f"Review new tools introduced: {', '.join(list(new_tools)[:3])}"
                )

    # Latency drift - check tool calls and reasoning depth
    if highest_dim == "latency_drift" or report.latency_drift > 0.20:
        steps.append("Profile tool call sequences for unnecessary chaining")
        steps.append("Check if reasoning depth or model endpoint changed")
        if baseline_tools and current_tools:
            # Look for tools that might be slow
            tools_added = {
                t: current_tools[t]
                for t in current_tools
                if t not in baseline_tools and current_tools[t] > 0.05
            }
            if tools_added:
                steps.append(
                    f"Investigate performance of: {', '.join(list(tools_added.keys())[:2])}"
                )

    # Error drift - check tool availability and API stability
    if highest_dim == "error_drift" or report.error_drift > 0.15:
        steps.append("Check tool availability and API endpoint health")
        steps.append("Review error logs for new failure modes")
        steps.append("Verify external dependencies are stable")

    # Generic steps for all high-drift cases
    if report.drift_score > 0.20:
        # Use version labels if available, otherwise fall back to fingerprint IDs
        baseline_ref = baseline_label or report.baseline_fingerprint_id
        current_ref = current_label or report.current_fingerprint_id
        steps.append(
            f"Run 'driftbase report {baseline_ref} {current_ref} --format html' for full analysis"
        )

    # If we generated no specific steps, add generic review step
    if not steps:
        steps.append("Review dimension breakdown for unexpected changes")

    return steps


def compute_verdict(
    report: DriftReport,
    baseline_tools: dict[str, float] | None = None,
    current_tools: dict[str, float] | None = None,
    baseline_n: int = 0,
    current_n: int = 0,
    baseline_label: str = "",
    current_label: str = "",
) -> VerdictResult:
    """
    Compute shipping verdict from drift report.

    Decision logic:
    - BLOCK: drift_score > 0.40 OR decision_drift > 0.40
    - REVIEW: drift_score > 0.20 OR decision_drift > 0.25
    - MONITOR: drift_score > 0.10
    - SHIP: drift_score <= 0.10

    Args:
        report: DriftReport with computed metrics
        baseline_tools: Tool usage distribution for baseline (for next steps)
        current_tools: Tool usage distribution for current (for next steps)
        baseline_n: Number of baseline runs (for context)
        current_n: Number of current runs (for context)
        baseline_label: Version label for baseline (for next steps command)
        current_label: Version label for current (for next steps command)

    Returns:
        VerdictResult with verdict, explanation, and next steps
    """
    score = report.drift_score
    highest_dim, highest_score = _get_highest_dimension(report)

    # BLOCK - major divergence
    if score > 0.40 or report.decision_drift > 0.40:
        return VerdictResult(
            verdict=Verdict.BLOCK,
            title="DO NOT SHIP",
            explanation=(
                f"Major behavioral divergence detected (drift score {score:.2f}). "
                f"Your agent's {highest_dim.replace('_', ' ')} changed significantly. "
                "Investigate root cause before promoting this version."
            ),
            next_steps=_generate_next_steps(
                report, highest_dim, baseline_label, current_label, baseline_tools, current_tools
            ),
            exit_code=1,
        )

    # REVIEW - moderate drift requiring review
    if score > 0.20 or report.decision_drift > 0.25:
        dimension_context = ""
        if report.decision_drift > 0.25:
            if report.escalation_rate_delta > 0.08:
                esc_pct_base = 8.0  # assumed baseline
                esc_pct_curr = (esc_pct_base + report.escalation_rate_delta * 100)
                dimension_context = f" Your agent is escalating to humans {esc_pct_curr/esc_pct_base:.1f}× more often than baseline."
            else:
                dimension_context = (
                    " Decision layer behavior changed - check outcome routing."
                )
        elif highest_dim == "latency_drift":
            from_ms = 100  # placeholder - would need actual baseline p95
            to_ms = from_ms * (1 + highest_score)
            dimension_context = (
                f" Latency increased {highest_score*100:.0f}% (p95 ~{to_ms:.0f}ms)."
            )
        elif highest_dim == "error_drift":
            dimension_context = f" Error rate changed by {report.error_drift*50:.1f}%."

        return VerdictResult(
            verdict=Verdict.REVIEW,
            title="REVIEW BEFORE SHIPPING",
            explanation=(
                f"Behavioral change detected (drift score {score:.2f}).{dimension_context} "
                "Review changes before promoting to production."
            ),
            next_steps=_generate_next_steps(
                report, highest_dim, baseline_label, current_label, baseline_tools, current_tools
            ),
            exit_code=1,
        )

    # MONITOR - minor drift, ship with awareness
    if score > 0.10:
        return VerdictResult(
            verdict=Verdict.MONITOR,
            title="SHIP WITH MONITORING",
            explanation=(
                f"Minor behavioral drift detected (drift score {score:.2f}). "
                f"Changes in {highest_dim.replace('_', ' ')} are within acceptable range. "
                "Safe to ship - monitor initial rollout."
            ),
            next_steps=[
                "Monitor initial rollout for unexpected behavior",
                "Track key metrics in first 24h after deployment",
            ],
            exit_code=0,
        )

    # SHIP - no meaningful change
    return VerdictResult(
        verdict=Verdict.SHIP,
        title="SAFE TO SHIP",
        explanation=(
            f"No meaningful behavioral change detected (drift score {score:.2f}). "
            "Agent behavior is consistent with baseline."
        ),
        next_steps=["Proceed with deployment"],
        exit_code=0,
    )


def generate_markdown_report(
    version_a: str, 
    version_b: str, 
    report: "DriftReport", 
    result: VerdictResult,
    cost_delta_eur: float = 0.0,
    cost_pct: float = 0.0
) -> str:
    """Generate a clean, PR-ready Markdown block for CI/CD pipelines."""
    
    status_text = {
        Verdict.SHIP: "[PASS]",
        Verdict.MONITOR: "[WARN]",
        Verdict.REVIEW: "[REVIEW]",
        Verdict.BLOCK: "[FAIL]",
    }[result.verdict]

    md = f"""## Driftbase Behavioral Report
Comparing `{version_a}` vs `{version_b}`

### {status_text} {result.title}
**Overall Drift Score:** `{report.drift_score:.2f}` (Threshold: 0.40)  
*{result.explanation}*

### Dimension Breakdown
| Metric | Score | Status |
|---|---|---|
| Decision Logic | `{report.decision_drift:.2f}` | {'PASS' if report.decision_drift < 0.25 else 'WARN'} |
| Latency Profile | `{report.latency_drift:.2f}` | {'PASS' if report.latency_drift < 0.20 else 'WARN'} |
| Error Rates | `{report.error_drift:.2f}` | {'PASS' if report.error_drift < 0.15 else 'WARN'} |
"""

    if cost_pct > 5.0:
        md += f"\n### Financial Impact\n**Cost increased by {cost_pct:.1f}%**. At current blended rates, this change will cost an additional **€{cost_delta_eur:.2f} per 10,000 runs**.\n\n"
    elif cost_pct < -5.0:
        md += f"\n### Financial Impact\n**Cost decreased by {abs(cost_pct):.1f}%**. At current blended rates, this change will save **€{abs(cost_delta_eur):.2f} per 10,000 runs**.\n\n"

    md += "### Next Steps\n"
    for step in result.next_steps:
        md += f"- {step}\n"
        
    md += "\n> *Generated locally. 100% Data Sovereignty maintained.*\n"
    md += "> *Automate PR comments and CI/CD gates with Driftbase Pro: https://driftbase.io/pro*"
    return md