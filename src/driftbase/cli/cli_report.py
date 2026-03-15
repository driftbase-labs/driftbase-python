"""
Shareable drift report: markdown, JSON, HTML from local SQLite data.
No cloud; same data as driftbase diff. Footer always includes trust line.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from typing import Any, Optional

import click

from driftbase.backends.base import StorageBackend
from driftbase.cli.cli_diff import (
    diff_local,
    get_runs_for_version,
    tool_usage_distribution,
)
from driftbase.local.hypothesis_engine import format_hypotheses, generate_hypotheses

FOOTER = "No raw content was captured or stored"


def _jsd(p: dict[str, float], q: dict[str, float]) -> float:
    """Jensen-Shannon divergence in [0, 1]."""
    if not p and not q:
        return 0.0
    if not p or not q:
        return 1.0
    keys = set(p) | set(q)
    m = {k: (p.get(k, 0.0) + q.get(k, 0.0)) / 2.0 for k in keys}
    js = 0.0
    for k in keys:
        pi, qi, mi = p.get(k, 0.0), q.get(k, 0.0), m[k]
        if pi > 0 and mi > 0:
            js += pi * math.log(pi / mi)
        if qi > 0 and mi > 0:
            js += qi * math.log(qi / mi)
    return min(1.0, max(0.0, js * 0.5 / math.log(2)))


def _status_label(score: float, threshold: float, is_overall: bool = False) -> str:
    if is_overall:
        if score >= threshold:
            return "⚠️ Above threshold"
        return "🟢 Within threshold"
    if score >= 0.35:
        return "🔴 High"
    if score >= 0.20:
        return "🟡 Moderate"
    if score >= 0.10:
        return "🟢 Low"
    return "🟢 Stable"


def _build_report_data(
    report: Any,
    baseline_fp: Any,
    current_fp: Any,
    baseline_tools: dict[str, float],
    current_tools: dict[str, float],
    baseline_label: str,
    current_label: str,
    threshold: float,
) -> dict[str, Any]:
    """Build a serializable report dict for markdown/json/html."""
    baseline_n = baseline_fp.sample_count
    current_n = current_fp.sample_count
    overall_drift = report.drift_score
    decision_drift = report.decision_drift
    latency_drift = report.latency_drift
    error_drift = report.error_drift
    tool_drift_jsd = _jsd(baseline_tools, current_tools)

    drift_score_lower = getattr(report, "drift_score_lower", overall_drift)
    drift_score_upper = getattr(report, "drift_score_upper", overall_drift)
    confidence_interval_pct = getattr(report, "confidence_interval_pct", 95)
    bootstrap_iterations = getattr(report, "bootstrap_iterations", 0)
    sample_size_warning = getattr(report, "sample_size_warning", False)

    summary_table = [
        {
            "metric": "Overall drift",
            "score": round(overall_drift, 2),
            "status": _status_label(overall_drift, threshold, is_overall=True),
        },
        {
            "metric": "Decision drift",
            "score": round(decision_drift, 2),
            "status": _status_label(decision_drift, threshold),
        },
        {
            "metric": "Latency drift",
            "score": round(latency_drift, 2),
            "status": _status_label(latency_drift, threshold),
        },
        {
            "metric": "Tool drift",
            "score": round(tool_drift_jsd, 2),
            "status": _status_label(tool_drift_jsd, threshold),
        },
        {
            "metric": "Error drift",
            "score": round(error_drift, 2),
            "status": _status_label(error_drift, threshold),
        },
    ]

    # What changed: bullets
    what_changed: list[str] = []
    # Error rate
    b_err = baseline_fp.error_rate
    c_err = current_fp.error_rate
    if b_err != c_err:
        pct = (
            ((c_err - b_err) / b_err * 100)
            if b_err > 0
            else (100.0 if c_err > 0 else 0)
        )
        what_changed.append(
            f"**Error rate** {'increased' if c_err > b_err else 'decreased'} from {b_err:.1%} → {c_err:.1%} ({pct:+.0f}%)"
        )
    # Tool with biggest drop/rise
    all_tools = sorted(set(baseline_tools.keys()) | set(current_tools.keys()))
    for tool in all_tools:
        b = baseline_tools.get(tool, 0.0) * 100
        c = current_tools.get(tool, 0.0) * 100
        if b == 0:
            if c > 0:
                what_changed.append(f"**{tool}** now used ({c:.1f}% of tool calls)")
            continue
        delta_pct = ((c - b) / b) * 100
        if abs(delta_pct) >= 15:
            direction = "more" if delta_pct > 0 else "less"
            what_changed.append(
                f"**{tool}** called {abs(delta_pct):.0f}% {direction} frequently"
            )
    # P95 latency
    b_p95 = baseline_fp.p95_latency_ms
    c_p95 = current_fp.p95_latency_ms
    delta_ms = c_p95 - b_p95
    if abs(delta_ms) >= 10:
        what_changed.append(
            f"**p95 latency** {'increased' if delta_ms > 0 else 'decreased'} by {abs(delta_ms)}ms ({b_p95}ms → {c_p95}ms)"
        )

    hypotheses = generate_hypotheses(
        report, baseline_tools, current_tools, baseline_n, current_n
    )
    root_cause_text = format_hypotheses(hypotheses)
    recommendation = (
        "⚠️ **Do not promote to production** until drift is investigated."
        if overall_drift >= threshold
        else "✅ Drift is within threshold. Proceed with standard review."
    )

    return {
        "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "baseline_version": baseline_label,
        "current_version": current_label,
        "baseline_n": baseline_n,
        "current_n": current_n,
        "threshold": threshold,
        "summary_table": summary_table,
        "drift_score_lower": drift_score_lower,
        "drift_score_upper": drift_score_upper,
        "confidence_interval_pct": confidence_interval_pct,
        "bootstrap_iterations": bootstrap_iterations,
        "sample_size_warning": sample_size_warning,
        "what_changed": what_changed,
        "root_cause_analysis": root_cause_text,
        "recommendation": recommendation,
        "footer": FOOTER,
    }


def format_markdown(data: dict[str, Any]) -> str:
    """Render report as GitHub-PR-friendly markdown."""
    lines = [
        f"## Driftbase Behavioral Report — {data['baseline_version']} → {data['current_version']}",
        "",
        f"Generated: {data['generated_at_utc']} · Runs: {data['baseline_version']} (n={data['baseline_n']}), {data['current_version']} (n={data['current_n']})",
        "",
        "### Summary",
        "| Metric | Score | Status |",
        "|--------|-------|--------|",
    ]
    for row in data["summary_table"]:
        lines.append(f"| {row['metric']} | {row['score']} | {row['status']} |")
    ci_lower = data.get("drift_score_lower")
    ci_upper = data.get("drift_score_upper")
    if (
        ci_lower is not None
        and ci_upper is not None
        and data.get("bootstrap_iterations", 0) > 0
    ):
        lines.append("")
        lines.append(f"95% confidence interval: [{ci_lower:.2f} – {ci_upper:.2f}]")
    lines.extend(["", "### What Changed", ""])
    if data["what_changed"]:
        for bullet in data["what_changed"]:
            lines.append(f"- {bullet}")
    else:
        lines.append("- No major changes detected.")
    lines.extend(
        [
            "",
            "### Root Cause Analysis",
            "",
            data["root_cause_analysis"],
            "",
            "### Recommendation",
            "",
            data["recommendation"],
            "",
        ]
    )
    lines.extend(["---", f"*Generated by Driftbase · {data['footer']}*"])
    return "\n".join(lines)


def format_json(data: dict[str, Any]) -> str:
    """Machine-readable JSON; same content, footer included."""
    return json.dumps(data, indent=2)


def format_html_legacy(data: dict[str, Any]) -> str:
    """Legacy HTML format - kept for compatibility. Use format_html_verdict() for new verdict-based format."""
    rows_html = "".join(
        f"<tr><td>{r['metric']}</td><td>{r['score']}</td><td>{r['status']}</td></tr>"
        for r in data["summary_table"]
    )
    ci_line = ""
    ci_lower = data.get("drift_score_lower")
    ci_upper = data.get("drift_score_upper")
    if (
        ci_lower is not None
        and ci_upper is not None
        and data.get("bootstrap_iterations", 0) > 0
    ):
        ci_line = f'<p class="meta">95% confidence interval: [{ci_lower:.2f} – {ci_upper:.2f}]</p>'
    bullets_html = (
        "".join(f"<li>{b.replace('**', '')}</li>" for b in data["what_changed"])
        if data["what_changed"]
        else "<li>No major changes detected.</li>"
    )
    rc_html = data["root_cause_analysis"].replace("\n", "<br>\n")
    rec = data["recommendation"].replace("**", "")  # drop markdown bold for plain HTML
    rec_html = rec.replace("⚠️", "<strong>⚠️</strong>").replace(
        "✅", "<strong>✅</strong>"
    )
    css = """
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 720px; margin: 24px auto; padding: 0 16px; color: #24292f; }
    h1 { font-size: 1.35rem; margin-bottom: 0.25rem; }
    h2 { font-size: 1.1rem; margin-top: 1.5rem; margin-bottom: 0.5rem; }
    .meta { color: #57606a; font-size: 0.9rem; margin-bottom: 1rem; }
    table { border-collapse: collapse; width: 100%; }
    th, td { border: 1px solid #d0d7de; padding: 8px 12px; text-align: left; }
    th { background: #f6f8fa; font-weight: 600; }
    ul { padding-left: 1.25rem; }
    .recommendation { margin: 1rem 0; padding: 12px; border-radius: 6px; background: #fff8e6; border: 1px solid #f0c674; }
    .footer { margin-top: 2rem; font-size: 0.85rem; color: #57606a; }
    """
    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><title>Driftbase Report — {data["baseline_version"]} → {data["current_version"]}</title><style>{css}</style></head>
<body>
<h1>Driftbase Behavioral Report — {data["baseline_version"]} → {data["current_version"]}</h1>
<p class="meta">Generated: {data["generated_at_utc"]} · Runs: {data["baseline_version"]} (n={data["baseline_n"]}), {data["current_version"]} (n={data["current_n"]})</p>
<h2>Summary</h2>
<table><thead><tr><th>Metric</th><th>Score</th><th>Status</th></tr></thead><tbody>{rows_html}</tbody></table>
{ci_line}
<h2>What Changed</h2><ul>{bullets_html}</ul>
<h2>Root Cause Analysis</h2><p>{rc_html}</p>
<h2>Recommendation</h2><div class="recommendation">{rec_html}</div>
<hr><p class="footer">Generated by Driftbase · {data["footer"]}</p>
</body>
</html>"""


def format_html_verdict(
    report: Any,
    baseline_fp: Any,
    current_fp: Any,
    baseline_tools: dict[str, float],
    current_tools: dict[str, float],
    tool_frequency_diffs: list[dict[str, Any]],
    compute_time_ms: float | None = None,
    template: str = "standard",
    sign: bool = False,
) -> str:
    """Generate modern HTML report using verdict engine and new design."""
    from driftbase.local.hypothesis_engine import generate_hypotheses
    from driftbase.reports.html import generate_eu_ai_act_report, generate_html_report
    from driftbase.verdict import compute_verdict

    baseline_n = baseline_fp.sample_count
    current_n = current_fp.sample_count
    baseline_label = baseline_fp.deployment_version
    current_label = current_fp.deployment_version

    # Generate verdict
    verdict_result = compute_verdict(
        report,
        baseline_tools=baseline_tools,
        current_tools=current_tools,
        baseline_n=baseline_n,
        current_n=current_n,
        baseline_label=baseline_label,
        current_label=current_label,
    )

    # Generate hypotheses
    hypotheses = generate_hypotheses(
        report, baseline_tools, current_tools, baseline_n, current_n
    )

    # Branch on template type
    if template == "eu-ai-act":
        return generate_eu_ai_act_report(
            report=report,
            verdict_result=verdict_result,
            baseline_label=baseline_label,
            current_label=current_label,
            baseline_n=baseline_n,
            current_n=current_n,
            hypotheses=hypotheses,
            tool_frequency_diffs=tool_frequency_diffs,
            compute_time_ms=compute_time_ms,
            include_signature=sign,
        )
    else:
        return generate_html_report(
            report=report,
            verdict_result=verdict_result,
            baseline_label=baseline_label,
            current_label=current_label,
            baseline_n=baseline_n,
            current_n=current_n,
            hypotheses=hypotheses,
            tool_frequency_diffs=tool_frequency_diffs,
            compute_time_ms=compute_time_ms,
        )


def run_report(
    baseline_version: str,
    current_version: str,
    *,
    fmt: str = "markdown",
    output_path: Optional[str] = None,
    threshold: float = 0.20,
    environment: Optional[str] = None,
    backend: Optional[StorageBackend] = None,
    console: Optional[Any] = None,
    template: str = "standard",
    sign: bool = False,
) -> int:
    """Generate shareable report; print to stdout or write to file. Returns 0 on success, 1 on error."""
    import time

    from rich.console import Console as RichConsole
    from rich.panel import Panel

    from driftbase.local.rootcause import tool_frequency_diff

    _console = console if console is not None else RichConsole()

    if backend is None:
        from driftbase.backends.factory import get_backend

        backend = get_backend()

    t0 = time.perf_counter()
    report, baseline_fp, current_fp, err = diff_local(
        backend,
        baseline_version,
        current_version,
        environment=environment,
        threshold=threshold,
    )
    elapsed_ms = (time.perf_counter() - t0) * 1000

    if err:
        _console.print(
            Panel(err, title="[bold red]Error[/]", border_style="red"),
        )
        return 1
    if report is None or baseline_fp is None or current_fp is None:
        _console.print(
            Panel(
                "Failed to compute diff for report.",
                title="[bold red]Error[/]",
                border_style="red",
            ),
        )
        return 1

    baseline_run_dicts = get_runs_for_version(
        backend, baseline_version, limit=5000, environment=environment
    )
    current_run_dicts = get_runs_for_version(
        backend, current_version, limit=5000, environment=environment
    )
    baseline_tools = tool_usage_distribution(baseline_run_dicts)
    current_tools = tool_usage_distribution(current_run_dicts)

    # For HTML format, use new verdict-based generator
    if fmt == "html":
        tool_frequency_diffs = tool_frequency_diff(
            baseline_run_dicts, current_run_dicts
        )
        out = format_html_verdict(
            report,
            baseline_fp,
            current_fp,
            baseline_tools,
            current_tools,
            tool_frequency_diffs,
            compute_time_ms=elapsed_ms,
            template=template,
            sign=sign,
        )

        # Auto-generate filename for EU AI Act reports
        final_output_path = output_path
        if output_path is None and template == "eu-ai-act":
            from datetime import datetime

            timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
            final_output_path = f"drift-report-eu-ai-act-{baseline_version}-{current_version}-{timestamp}.html"

        if final_output_path:
            with open(final_output_path, "w", encoding="utf-8") as f:
                f.write(out)
            _console.print(f"[green]✓[/] HTML report written to {final_output_path}")
            return 0
        _console.print(out)
        return 0

    # For markdown/json, use existing data-based format
    data = _build_report_data(
        report,
        baseline_fp,
        current_fp,
        baseline_tools,
        current_tools,
        baseline_fp.deployment_version,
        current_fp.deployment_version,
        threshold,
    )

    if fmt == "json":
        out = format_json(data)
    else:
        out = format_markdown(data)

    if output_path:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(out)
        return 0
    _console.print(out)
    return 0


@click.command(name="report")
@click.argument("baseline")
@click.argument("current")
@click.option(
    "--format",
    "-f",
    "fmt",
    type=click.Choice(["markdown", "json", "html"]),
    default="markdown",
    help="Output format.",
)
@click.option(
    "--output",
    "-o",
    "output_path",
    metavar="PATH",
    help="Write report to file instead of stdout.",
)
@click.option(
    "--threshold",
    "-t",
    type=float,
    default=0.20,
    help="Drift threshold for recommendation (default 0.20).",
)
@click.option("--environment", "-e", default=None, help="Filter by environment.")
@click.option(
    "--template",
    type=click.Choice(["standard", "eu-ai-act"]),
    default="standard",
    help="Report template (HTML format only).",
)
@click.option(
    "--sign",
    is_flag=True,
    default=False,
    help="Include SHA256 integrity hash (eu-ai-act template only).",
)
@click.pass_context
def cmd_report(
    ctx: click.Context,
    baseline: str,
    current: str,
    fmt: str,
    output_path: str | None,
    threshold: float,
    environment: str | None,
    template: str,
    sign: bool,
) -> None:
    """Generate shareable drift report (markdown, JSON, HTML) from local SQLite data."""
    console = ctx.obj["console"]
    code = run_report(
        baseline,
        current,
        fmt=fmt,
        output_path=output_path,
        threshold=threshold,
        environment=environment,
        console=console,
        template=template,
        sign=sign,
    )
    ctx.exit(code)
