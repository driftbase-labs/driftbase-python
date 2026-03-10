"""
HTML report generator for drift analysis.
Produces a single self-contained HTML file with inline CSS - emailable and PR-attachable.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from driftbase.local.local_store import DriftReport
    from driftbase.verdict import VerdictResult


# Color system matching CLI
COLORS = {
    "green": "#16a34a",
    "blue": "#2563eb",
    "yellow": "#d97706",  # Maps to verdict.style "yellow" for REVIEW
    "amber": "#d97706",
    "red": "#dc2626",
    "gray": "#6b7280",
    "gray_light": "#f3f4f6",
    "gray_border": "#e5e7eb",
}


def _escape_html(text: str) -> str:
    """Escape HTML special characters."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def _get_severity_color(verdict_style: str) -> str:
    """Map verdict style to color."""
    return COLORS.get(verdict_style, COLORS["gray"])


def _render_dimension_card(
    name: str,
    score: float,
    status: str,
    context_lines: list[str],
    style_color: str,
) -> str:
    """Render a single dimension card."""
    symbol = "⚠" if score >= 0.5 else "·" if score >= 0.1 else "✓"

    context_html = ""
    if context_lines:
        context_html = "<div style='margin-top:8px; font-size:13px; color:#6b7280;'>"
        for line in context_lines:
            context_html += f"<div>{_escape_html(line)}</div>"
        context_html += "</div>"

    return f"""
    <div style="background:white; border:1px solid {COLORS['gray_border']}; border-radius:8px; padding:16px;">
        <div style="font-size:14px; color:{COLORS['gray']}; font-weight:500; margin-bottom:8px;">
            {_escape_html(name)}
        </div>
        <div style="font-size:28px; font-weight:600; color:{style_color}; margin-bottom:4px;">
            {score:.2f}
        </div>
        <div style="font-size:12px; color:{style_color}; font-weight:500; letter-spacing:0.5px;">
            {symbol} {_escape_html(status).upper()}
        </div>
        {context_html}
    </div>
    """


def generate_html_report(
    report: DriftReport,
    verdict_result: VerdictResult,
    baseline_label: str,
    current_label: str,
    baseline_n: int,
    current_n: int,
    hypotheses: list[dict[str, str]],
    tool_frequency_diffs: list[dict[str, Any]] | None = None,
    compute_time_ms: float | None = None,
) -> str:
    """
    Generate a single self-contained HTML report.

    Args:
        report: DriftReport with metrics
        verdict_result: VerdictResult from verdict engine
        baseline_label: Baseline version label
        current_label: Current version label
        baseline_n: Number of baseline runs
        current_n: Number of current runs
        hypotheses: List of hypotheses from hypothesis engine
        tool_frequency_diffs: Optional tool frequency changes
        compute_time_ms: Optional computation time

    Returns:
        Complete HTML document as a string
    """
    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    verdict_color = _get_severity_color(verdict_result.style)

    # Verdict symbol
    verdict_symbol = verdict_result.symbol

    # Build "Most likely cause" section if we have hypotheses
    most_likely_cause_html = ""
    if hypotheses:
        top = hypotheses[0]
        most_likely_cause_html = f"""
        <div style="margin-top:20px; padding:16px; background:{COLORS['gray_light']}; border-radius:6px;">
            <div style="font-weight:600; margin-bottom:8px; color:#111827;">Most likely cause:</div>
            <div style="margin-bottom:6px; color:#111827;">→ {_escape_html(top['observation'])}</div>
            <div style="font-size:14px; color:{COLORS['gray']};">{_escape_html(top['likely_cause'])}</div>
        </div>
        """

    # Build next steps checklist
    next_steps_html = "<div style='margin-top:20px;'><div style='font-weight:600; margin-bottom:8px; color:#111827;'>Next steps:</div>"
    for step in verdict_result.next_steps:
        next_steps_html += f"<div style='margin-bottom:6px; color:#374151;'>□ {_escape_html(step)}</div>"
    next_steps_html += "</div>"

    # Build dimension cards
    def get_dimension_status(score: float) -> str:
        if score >= 0.5:
            return "HIGH"
        elif score >= 0.2:
            return "MODERATE"
        elif score >= 0.1:
            return "LOW"
        else:
            return "STABLE"

    def get_dimension_style(score: float) -> str:
        if score >= 0.5:
            return COLORS["red"]
        elif score >= 0.2:
            return COLORS["amber"]
        elif score >= 0.1:
            return COLORS["gray"]
        else:
            return COLORS["green"]

    # Decision drift context
    decision_context = []
    if report.decision_drift > 0.2:
        baseline_esc = getattr(report, "baseline_escalation_rate", 0.0) * 100
        current_esc = getattr(report, "current_escalation_rate", 0.0) * 100
        if baseline_esc > 0 or current_esc > 0:
            decision_context.append(f"escalation rate: {baseline_esc:.0f}% → {current_esc:.0f}%")
            if current_esc > baseline_esc * 1.5:
                multiplier = current_esc / max(baseline_esc, 1)
                decision_context.append(f"routing {multiplier:.1f}× more to humans")
        else:
            decision_context.append("outcome distribution changed")

    # Latency drift context
    latency_context = []
    if report.latency_drift > 0.15:
        baseline_p95 = getattr(report, "baseline_p95_latency_ms", 0.0)
        current_p95 = getattr(report, "current_p95_latency_ms", 0.0)
        if baseline_p95 > 0:
            latency_context.append(f"p95: {baseline_p95:.0f}ms → {current_p95:.0f}ms")

    # Error drift context
    error_context = []
    baseline_err = getattr(report, "baseline_error_rate", 0.0) * 100
    current_err = getattr(report, "current_error_rate", 0.0) * 100
    if report.error_drift < 0.05:
        error_context.append("stable")
    elif baseline_err > 0 or current_err > 0:
        error_context.append(f"error rate: {baseline_err:.1f}% → {current_err:.1f}%")

    decision_card = _render_dimension_card(
        "Decisions",
        report.decision_drift,
        get_dimension_status(report.decision_drift),
        decision_context,
        get_dimension_style(report.decision_drift),
    )

    latency_card = _render_dimension_card(
        "Latency",
        report.latency_drift,
        get_dimension_status(report.latency_drift),
        latency_context,
        get_dimension_style(report.latency_drift),
    )

    error_card = _render_dimension_card(
        "Errors",
        report.error_drift,
        get_dimension_status(report.error_drift),
        error_context,
        get_dimension_style(report.error_drift),
    )

    # Tool usage card (placeholder - we could add tool_dist here if needed)
    tool_context = []
    if tool_frequency_diffs and len(tool_frequency_diffs) > 0:
        top_change = tool_frequency_diffs[0]
        delta = top_change.get("delta_pct", 0)
        if abs(delta) > 20:
            tool_context.append(f"top change: {top_change['tool'][:20]} ({delta:+.0f}%)")

    # Use semantic_drift as a proxy for tool distribution changes
    tool_score = getattr(report, "semantic_drift", 0.0)
    tool_card = _render_dimension_card(
        "Tool Usage",
        tool_score,
        get_dimension_status(tool_score),
        tool_context,
        get_dimension_style(tool_score),
    )

    # Additional analysis section (only if multiple hypotheses)
    additional_analysis_html = ""
    if len(hypotheses) > 1:
        additional_analysis_html = """
        <div style="margin-top:40px;">
            <h2 style="font-size:18px; font-weight:600; color:#111827; margin-bottom:16px;">Additional Analysis</h2>
            <div style="background:white; border:1px solid #e5e7eb; border-radius:8px; padding:20px;">
        """
        for hyp in hypotheses[1:]:
            additional_analysis_html += f"""
            <div style="margin-bottom:20px;">
                <div style="margin-bottom:6px; color:#111827;">→ {_escape_html(hyp['observation'])}</div>
                <div style="font-size:14px; color:#6b7280; margin-bottom:4px; margin-left:16px;">
                    <strong>Likely cause:</strong> {_escape_html(hyp['likely_cause'])}
                </div>
                <div style="font-size:14px; color:#6b7280; margin-left:16px;">
                    <strong>Recommended action:</strong> {_escape_html(hyp['recommended_action'])}
                </div>
            </div>
            """
        additional_analysis_html += "</div></div>"

    # Tool frequency table (if available)
    tool_table_html = ""
    if tool_frequency_diffs and len(tool_frequency_diffs) > 0:
        tool_table_html = """
        <div style="margin-top:40px;">
            <h2 style="font-size:18px; font-weight:600; color:#111827; margin-bottom:16px;">Tool Call Frequency Changes</h2>
            <div style="overflow-x:auto;">
                <table style="width:100%; border-collapse:collapse; background:white; border:1px solid #e5e7eb; border-radius:8px;">
                    <thead>
                        <tr style="background:#f9fafb; border-bottom:1px solid #e5e7eb;">
                            <th style="padding:12px; text-align:left; font-size:13px; font-weight:600; color:#6b7280;">Tool</th>
                            <th style="padding:12px; text-align:right; font-size:13px; font-weight:600; color:#6b7280;">Baseline</th>
                            <th style="padding:12px; text-align:right; font-size:13px; font-weight:600; color:#6b7280;">Current</th>
                            <th style="padding:12px; text-align:right; font-size:13px; font-weight:600; color:#6b7280;">Change</th>
                        </tr>
                    </thead>
                    <tbody>
        """
        for i, row in enumerate(tool_frequency_diffs[:15]):
            delta = row.get("delta_pct", 0)
            color = COLORS["red"] if delta > 10 else COLORS["green"] if delta < -10 else COLORS["gray"]
            border = "" if i == len(tool_frequency_diffs[:15]) - 1 else "border-bottom:1px solid #f3f4f6;"
            tool_table_html += f"""
                        <tr style="{border}">
                            <td style="padding:12px; font-size:14px; color:#111827;">{_escape_html(row['tool'])}</td>
                            <td style="padding:12px; text-align:right; font-size:14px; color:#6b7280;">{row['baseline_pct']:.0f}%</td>
                            <td style="padding:12px; text-align:right; font-size:14px; color:#6b7280;">{row['current_pct']:.0f}%</td>
                            <td style="padding:12px; text-align:right; font-size:14px; font-weight:600; color:{color};">{delta:+.0f}%</td>
                        </tr>
            """
        tool_table_html += """
                    </tbody>
                </table>
            </div>
        </div>
        """

    # Footer
    footer_parts = []
    if hasattr(report, "bootstrap_iterations") and report.bootstrap_iterations > 0:
        footer_parts.append("95% CI via bootstrap")
    if compute_time_ms:
        footer_parts.append(f"Computed in {compute_time_ms:.0f}ms")
    footer_parts.append("No data left your machine")
    footer = " · ".join(footer_parts)

    # Confidence interval display
    ci_display = ""
    if (
        hasattr(report, "drift_score_upper")
        and hasattr(report, "drift_score_lower")
        and report.drift_score_upper is not None
        and report.drift_score_lower is not None
    ):
        lower, upper = report.drift_score_lower, report.drift_score_upper
        if upper - lower > 0.01:
            ci_display = f" <span style='font-size:16px; color:#6b7280;'>[{lower:.2f}–{upper:.2f}, 95% CI]</span>"

    # Complete HTML document
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Driftbase Report: {_escape_html(baseline_label)} → {_escape_html(current_label)}</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            background: #f9fafb;
            color: #111827;
            padding: 40px 20px;
        }}
        .container {{
            max-width: 1000px;
            margin: 0 auto;
        }}
    </style>
</head>
<body>
    <div class="container">
        <!-- Header -->
        <div style="background:white; border-radius:12px; padding:24px; margin-bottom:24px; border:1px solid {COLORS['gray_border']};">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:16px;">
                <div>
                    <div style="font-size:24px; font-weight:700; color:#111827; margin-bottom:4px;">
                        DRIFTBASE
                    </div>
                    <div style="font-size:16px; color:{COLORS['gray']};">
                        {_escape_html(baseline_label)} → {_escape_html(current_label)} · {baseline_n} vs {current_n} runs
                    </div>
                </div>
                <div style="text-align:right; font-size:13px; color:{COLORS['gray']};">
                    {timestamp}
                </div>
            </div>
            <div style="margin-top:20px; padding-top:20px; border-top:1px solid {COLORS['gray_border']};">
                <div style="font-size:14px; color:{COLORS['gray']}; margin-bottom:4px;">Overall drift</div>
                <div style="font-size:32px; font-weight:700; color:#111827;">
                    {report.drift_score:.2f}{ci_display}
                </div>
            </div>
        </div>

        <!-- Verdict Panel -->
        <div style="background:{verdict_color}; color:white; border-radius:12px; padding:24px; margin-bottom:24px; box-shadow:0 4px 6px -1px rgba(0,0,0,0.1);">
            <div style="font-size:20px; font-weight:700; margin-bottom:16px;">
                {verdict_symbol} {_escape_html(verdict_result.title)}
            </div>
            <div style="font-size:15px; line-height:1.6; margin-bottom:8px;">
                {_escape_html(verdict_result.explanation)}
            </div>
            {most_likely_cause_html}
            {next_steps_html}
        </div>

        <!-- Dimension Grid -->
        <div style="margin-bottom:24px;">
            <h2 style="font-size:18px; font-weight:600; color:#111827; margin-bottom:16px;">What Changed</h2>
            <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(220px, 1fr)); gap:16px;">
                {decision_card}
                {latency_card}
                {tool_card}
                {error_card}
            </div>
        </div>

        {tool_table_html}

        {additional_analysis_html}

        <!-- Footer -->
        <div style="margin-top:40px; padding-top:20px; border-top:1px solid {COLORS['gray_border']}; text-align:center; font-size:13px; color:{COLORS['gray']};">
            {footer}
        </div>

        <div style="margin-top:20px; text-align:center; font-size:12px; color:{COLORS['gray']};">
            Generated by <strong>Driftbase</strong> · Behavioral drift monitoring for AI agents
        </div>
    </div>
</body>
</html>"""

    return html
