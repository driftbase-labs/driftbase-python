"""
Local CLI diff and watch: compute drift from local backend (SQLite/Postgres) runs.
All computation runs locally unless --remote is specified. Output via rich Console/Table/Panel.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from collections import Counter
from datetime import datetime
from typing import Any

import click

logger = logging.getLogger(__name__)

from driftbase.backends.base import StorageBackend
from driftbase.cli._deps import safe_import_rich
from driftbase.local.diff import compute_drift
from driftbase.local.fingerprinter import build_fingerprint_from_runs
from driftbase.local.local_store import (
    BehavioralFingerprint,
    DriftReport,
    run_dict_to_agent_run,
)
from driftbase.local.rootcause import (
    build_explanation,
    tool_frequency_diff,
    top_sequence_shifts,
)
from driftbase.pricing import calculate_cost_per_10k, get_rates_for_display

# Lazy import of heavy [analyze] dependencies
Console, Panel, Table = safe_import_rich()

MIN_SAMPLES_WARNING = 50
DEFAULT_THRESHOLD = 0.20


def _parse_duration_to_hours(duration_str: str) -> int | None:
    """Parse duration string like '24h', '7d', '2w' into hours."""
    import re

    match = re.match(r"^(\d+)([hdw])$", duration_str.lower())
    if not match:
        return None

    value, unit = match.groups()
    value = int(value)

    if unit == "h":
        return value
    elif unit == "d":
        return value * 24
    elif unit == "w":
        return value * 24 * 7

    return None


def _parse_date_range(between_str: str) -> tuple[datetime, datetime] | None:
    """Parse date range like '2026-03-01..2026-03-15' into (start, end) datetimes."""
    parts = between_str.split("..")
    if len(parts) != 2:
        return None

    try:
        start_date = datetime.fromisoformat(parts[0].strip())
        end_date = datetime.fromisoformat(parts[1].strip())
        return (start_date, end_date)
    except ValueError:
        return None


def _parse_outcomes(outcomes_str: str) -> list[str]:
    """Parse comma-separated outcomes like 'resolved,escalated' into list."""
    return [o.strip() for o in outcomes_str.split(",") if o.strip()]


def _apply_filters_to_runs(
    backend: StorageBackend,
    deployment_version: str | None,
    environment: str | None,
    since: str | None,
    between: str | None,
    outcomes: str | None,
    max_samples: int | None,
    limit: int = 10000,
) -> list[dict[str, Any]]:
    """
    Fetch runs with enhanced filtering.

    Returns list of run dicts.
    """
    # Parse filters
    since_hours = None
    if since:
        since_hours = _parse_duration_to_hours(since)

    between_range = None
    if between:
        between_range = _parse_date_range(between)

    outcomes_list = None
    if outcomes:
        outcomes_list = _parse_outcomes(outcomes)

    # Use enhanced query if backend supports it
    if hasattr(backend, "get_runs_filtered"):
        runs = backend.get_runs_filtered(
            deployment_version=deployment_version,
            environment=environment,
            since_hours=since_hours,
            between=between_range,
            outcomes=outcomes_list,
            limit=max_samples or limit,
        )
    else:
        # Fallback to basic get_runs
        runs = backend.get_runs(
            deployment_version=deployment_version,
            environment=environment,
            limit=max_samples or limit,
        )

    return runs


@click.command(name="diff")
@click.argument("baseline", required=False)
@click.argument("current", required=False)
@click.option(
    "--last",
    "-n",
    type=int,
    metavar="N",
    help="Use last N runs as current (use with --against).",
)
@click.option("--against", metavar="VERSION", help="Baseline version (with --last).")
@click.option("--environment", "-e", default=None, help="Filter by environment.")
@click.option(
    "--threshold",
    "-t",
    type=float,
    default=0.20,
    help="Drift threshold (default 0.20).",
)
@click.option(
    "--json", "json_output", is_flag=True, help="Machine-readable output for CI."
)
@click.option(
    "--remote", is_flag=True, help="Compute diff using the Driftbase Pro cloud engine."
)
@click.option(
    "--since",
    metavar="DURATION",
    help="Compare runs since duration (e.g., 24h, 7d, 2w).",
)
@click.option(
    "--between",
    metavar="START..END",
    help="Compare runs between dates (e.g., 2026-03-01..2026-03-15).",
)
@click.option(
    "--outcomes",
    metavar="LIST",
    help="Filter by outcomes (comma-separated, e.g., resolved,escalated).",
)
@click.option(
    "--max-samples",
    type=int,
    metavar="N",
    help="Limit samples per version (trades precision for speed).",
)
@click.option(
    "--fail-on-drift",
    is_flag=True,
    help="Exit with code 1 if any drift detected (CI mode).",
)
@click.option(
    "--exit-nonzero-above",
    type=float,
    metavar="THRESHOLD",
    help="Exit code 1 if drift > threshold (e.g., 0.15).",
)
@click.option(
    "--significance-level",
    type=float,
    metavar="ALPHA",
    default=0.05,
    help="Statistical significance level for hypothesis tests (default 0.05).",
)
@click.option(
    "--show-stats",
    is_flag=True,
    help="Show statistical significance tests (chi-squared, t-test, etc.).",
)
@click.pass_context
def cmd_diff(
    ctx: click.Context,
    baseline: str | None,
    current: str | None,
    last: int | None,
    against: str | None,
    environment: str | None,
    threshold: float,
    json_output: bool,
    remote: bool,
    since: str | None,
    between: str | None,
    outcomes: str | None,
    max_samples: int | None,
    fail_on_drift: bool,
    exit_nonzero_above: float | None,
    significance_level: float,
    show_stats: bool,
) -> None:
    """
    Compare two versions or last N runs vs baseline.

    \b
    Examples:
      # Compare two versions
      driftbase diff v1.0 v2.0

      # Compare last 50 runs against baseline
      driftbase diff --last 50 --against v2.0

      # CI mode: fail if drift detected
      driftbase diff v1.0 v2.0 --json --fail-on-drift

      # Filter by time and outcome
      driftbase diff v1.0 v2.0 --since 24h --outcomes resolved,escalated

      # Use cloud comparison engine
      driftbase diff v1.0 v2.0 --remote
    """
    console: Console = ctx.obj["console"]
    use_color = not console.no_color

    # Handle Cloud Diff
    if remote:
        if not baseline or not current:
            console.print(
                "[bold red]Error:[/] --remote requires explicit baseline and current versions (e.g. driftbase diff v1.0 v2.0 --remote)"
            )
            ctx.exit(1)

        import httpx

        api_key = os.getenv("DRIFTBASE_API_KEY")
        if not api_key:
            console.print("[bold red]Error:[/] DRIFTBASE_API_KEY missing.")
            ctx.exit(1)

        api_url = os.getenv("DRIFTBASE_API_URL", "http://localhost:8000")

        payload = {
            "baseline_version": baseline,
            "current_version": current,
            "environment": environment or "production",
        }

        try:
            response = httpx.post(
                f"{api_url}/diff",
                json=payload,
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=10.0,
            )
            response.raise_for_status()
            data = response.json()
        except Exception as e:
            console.print(f"[bold red]API Error:[/] {str(e)}")
            ctx.exit(1)

        score = data.get("drift_score", 0.0)
        severity = data.get("severity", "unknown")

        # Financial calculation
        rate_p = float(os.getenv("DRIFTBASE_RATE_PROMPT_1M", "2.50"))
        rate_c = float(os.getenv("DRIFTBASE_RATE_COMPLETION_1M", "10.00"))

        b_p_tok = data.get("baseline_prompt_tokens", 0)
        b_c_tok = data.get("baseline_completion_tokens", 0)
        c_p_tok = data.get("current_prompt_tokens", 0)
        c_c_tok = data.get("current_completion_tokens", 0)

        b_cost_10k = ((b_p_tok * rate_p) + (b_c_tok * rate_c)) * 10000 / 1000000
        c_cost_10k = ((c_p_tok * rate_p) + (c_c_tok * rate_c)) * 10000 / 1000000
        delta_cost = c_cost_10k - b_cost_10k

        console.print(f"\n[bold]Drift Analysis (Cloud):[/] {baseline} ➔ {current}")
        console.print(
            f"Sample size: {data.get('baseline_sample_count', 0)} vs {data.get('current_sample_count', 0)}"
        )
        console.print(f"Jensen-Shannon Divergence: [bold]{score}[/]")

        cost_color = "red" if delta_cost > 0 else "green"
        cost_sign = "+" if delta_cost > 0 else ""
        console.print(
            f"Cost Impact (per 10k runs): [{cost_color}]{cost_sign}€{delta_cost:.2f}[/]"
        )

        if severity == "high":
            console.print(
                "\n[bold red]✖ High behavioral drift detected. Deployment blocked.[/]"
            )
            ctx.exit(1)
        elif severity == "medium":
            console.print(
                "\n[bold yellow]! Medium behavioral drift detected. Proceed with caution.[/]"
            )
            ctx.exit(0)
        else:
            console.print(
                "\n[bold green]✓ Agent behavior is stable. Deployment approved.[/]"
            )
            ctx.exit(0)

    # Handle Local Diff
    from driftbase.backends.factory import get_backend

    if last is not None and against is not None:
        code = run_diff(
            against,
            "local",
            last_n=last,
            against_version=against,
            environment=environment,
            threshold=threshold,
            json_output=json_output,
            use_color=use_color,
            backend=None,
            console=console,
            fail_on_drift=fail_on_drift,
            exit_nonzero_above=exit_nonzero_above,
        )
        ctx.exit(code)

    if (baseline == "local" or current == "local") and (
        baseline is None or current is None
    ):
        backend = get_backend()
        versions = backend.get_versions()
        if not versions:
            console.print(
                Panel(
                    "No versions in DB; cannot diff 'local' without a baseline. Use: driftbase diff VERSION local",
                    title="Error",
                    border_style="#FF6B6B",
                ),
            )
            ctx.exit(1)
        base_version = (max(versions, key=lambda x: x[1])[0]) or "unknown"
        code = run_diff(
            base_version,
            "local",
            environment=environment,
            threshold=threshold,
            json_output=json_output,
            use_color=use_color,
            backend=backend,
            console=console,
            fail_on_drift=fail_on_drift,
            exit_nonzero_above=exit_nonzero_above,
        )
        ctx.exit(code)

    if baseline is None or current is None:
        console.print(
            Panel(
                "Either provide two versions (e.g. driftbase diff v1.0 v2.0) or use --last N --against VERSION",
                title="Error",
                border_style="#FF6B6B",
            ),
        )
        ctx.exit(1)

    code = run_diff(
        baseline,
        current,
        environment=environment,
        threshold=threshold,
        json_output=json_output,
        use_color=use_color,
        backend=None,
        console=console,
        fail_on_drift=fail_on_drift,
        exit_nonzero_above=exit_nonzero_above,
    )
    ctx.exit(code)


def get_runs_for_version(
    backend: StorageBackend,
    version: str,
    limit: int = 5000,
    environment: str | None = None,
) -> list[dict[str, Any]]:
    """Get runs for a version. Use version='local' for last N runs (no version filter)."""
    if version == "local":
        return backend.get_runs(
            deployment_version=None, environment=environment, limit=limit
        )
    return backend.get_runs(
        deployment_version=version, environment=environment, limit=limit
    )


def fingerprint_from_runs(
    run_dicts: list[dict[str, Any]],
    label: str,
    environment: str = "production",
) -> BehavioralFingerprint | None:
    """Build a behavioral fingerprint from run dicts (no DB persist)."""
    if not run_dicts:
        return None
    runs = [run_dict_to_agent_run(d) for d in run_dicts]
    started = [r.started_at for r in runs]
    window_start = min(started)
    window_end = max(started)
    return build_fingerprint_from_runs(
        runs, window_start, window_end, label, environment
    )


def tool_usage_distribution(run_dicts: list[dict[str, Any]]) -> dict[str, float]:
    """Per-tool usage frequency (fraction of all tool calls)."""
    counter: Counter[str] = Counter()
    for d in run_dicts:
        seq = d.get("tool_sequence", "[]")
        try:
            tools = json.loads(seq) if isinstance(seq, str) else seq
        except Exception:
            tools = []
        for t in tools:
            counter[str(t)] += 1
    total = sum(counter.values())
    if total == 0:
        return {}
    return {k: v / total for k, v in counter.most_common()}


def _dimension_style(score: float, threshold: float) -> str:
    if score >= 0.5:
        return "red"
    if score >= 0.2:
        return "yellow3"
    if score >= 0.1:
        return "dim"
    return "green"


def _dimension_status(score: float) -> str:
    if score >= 0.5:
        return "HIGH"
    if score >= 0.2:
        return "MODERATE"
    if score >= 0.1:
        return "LOW"
    return "STABLE"


def render_diff_report(
    console: Console,
    report: DriftReport,
    baseline_label: str,
    current_label: str,
    baseline_n: int,
    current_n: int,
    baseline_tools: dict[str, float],
    current_tools: dict[str, float],
    tool_frequency_diffs: list[dict[str, Any]],
    top_sequence_shifts_list: list[dict[str, Any]],
    explanation: str,
    threshold: float = DEFAULT_THRESHOLD,
    compute_time_ms: float | None = None,
    baseline_cost_per_10k: float | None = None,
    current_cost_per_10k: float | None = None,
) -> int:
    """Render drift report using rich Table and Panel (no raw ANSI)."""
    from driftbase.verdict import compute_verdict

    verdict_result = compute_verdict(
        report,
        baseline_tools=baseline_tools,
        current_tools=current_tools,
        baseline_n=baseline_n,
        current_n=current_n,
        baseline_label=baseline_label,
        current_label=current_label,
    )

    console.print("─" * 76)
    console.print(
        f"  [bold]DRIFTBASE[/]  [default]{baseline_label}[/] → [default]{current_label}[/]  ·  [default]{baseline_n} vs {current_n} runs[/]"
    )
    console.print("─" * 76)
    console.print()

    # Calibration transparency (always shown)
    use_case = getattr(report, "inferred_use_case", "GENERAL")
    use_case_confidence = getattr(report, "use_case_confidence", 0.0)
    calibration_method = getattr(report, "calibration_method", "default")
    calibrated_weights = getattr(report, "calibrated_weights", None)
    composite_thresholds = getattr(report, "composite_thresholds", None)
    baseline_n_calibration = getattr(report, "baseline_n", baseline_n)

    # Format use case for display (lowercase with underscores to title case)
    use_case_display = use_case.lower().replace("_", " ")

    # One-line calibration summary (always visible)
    calibration_line = f"Calibration   {use_case_display} · {calibration_method} · baseline n={baseline_n_calibration}"
    if use_case_confidence > 0:
        calibration_line += f" ({use_case_confidence:.0%} confidence)"
    console.print(f"[dim]{calibration_line}[/]")

    # Show top weighted dimensions and thresholds if calibrated
    if calibrated_weights and composite_thresholds:
        # Get top 3 weighted dimensions
        sorted_dims = sorted(
            calibrated_weights.items(), key=lambda x: x[1], reverse=True
        )[:3]
        dim_names_map = {
            "decision_drift": "decision patterns",
            "latency_drift": "latency",
            "error_drift": "error rate",
            "semantic_drift": "outcome patterns",
            "verbosity_drift": "verbosity",
            "loop_depth_drift": "reasoning depth",
            "output_drift": "output structure",
            "output_length_drift": "output length",
            "tool_sequence_drift": "tool sequencing",
            "retry_drift": "retry rate",
            "planning_latency_drift": "planning latency",
        }
        top_dims_str = ", ".join(
            [
                f"{dim_names_map.get(dim, dim)} ({weight:.2f})"
                for dim, weight in sorted_dims
            ]
        )
        console.print(f"[dim]  Top dimensions: {top_dims_str}[/]")

        # Show adjusted thresholds
        monitor_t = composite_thresholds.get("MONITOR", 0.15)
        review_t = composite_thresholds.get("REVIEW", 0.28)
        block_t = composite_thresholds.get("BLOCK", 0.42)
        console.print(
            f"[dim]  Thresholds: MONITOR {monitor_t:.2f} · REVIEW {review_t:.2f} · BLOCK {block_t:.2f}[/]"
        )

    console.print()

    # Create summary table
    summary_table = Table(
        show_header=False,
        box=None,
        padding=(0, 2, 0, 0),
        collapse_padding=True,
    )
    summary_table.add_column("Metric", style="dim", width=22)
    summary_table.add_column("Value", style="", no_wrap=False)

    # Overall drift with CI
    ci_display = ""
    if (
        hasattr(report, "drift_score_upper")
        and hasattr(report, "drift_score_lower")
        and report.drift_score_upper is not None
        and report.drift_score_lower is not None
    ):
        lower, upper = report.drift_score_lower, report.drift_score_upper
        if upper - lower > 0.01:
            ci_display = f"  [dim]95% CI: [{lower:.2f}–{upper:.2f}][/]"

    drift_color = (
        "#FF6B6B"
        if report.drift_score >= 0.50
        else "#FFA94D"
        if report.drift_score >= 0.20
        else "#4ADE80"
    )
    summary_table.add_row(
        "Overall Drift Score:",
        f"[{drift_color} bold]{report.drift_score:.2f}[/]{ci_display}",
    )

    # Cost impact (per 10k runs) when token data is available
    if baseline_cost_per_10k is not None and current_cost_per_10k is not None:
        delta_cost = current_cost_per_10k - baseline_cost_per_10k
        cost_pct_change = (
            (delta_cost / baseline_cost_per_10k * 100)
            if baseline_cost_per_10k > 0
            else 0
        )
        cost_color = (
            "#FF8787"
            if delta_cost > 0
            else "#4ADE80"
            if delta_cost < 0
            else "bright_black"
        )
        cost_sign = "+" if delta_cost > 0 else ""

        cost_display = (
            f"[bold]{baseline_cost_per_10k:.2f}[/] → [bold]{current_cost_per_10k:.2f}[/] €  "
            f"([{cost_color}]{cost_sign}{delta_cost:.2f} €, {cost_sign}{cost_pct_change:.0f}%[/])"
        )
        summary_table.add_row("Cost per 10k runs:", cost_display)

        from driftbase.pricing import get_rates_for_display

        rate_p, rate_c = get_rates_for_display()
        summary_table.add_row(
            "Pricing:", f"[dim]€{rate_p:.2f}/1M prompt · €{rate_c:.2f}/1M completion[/]"
        )

    console.print(summary_table)
    console.print()
    console.print(
        "[dim]  Tip: Set DRIFTBASE_RATE_* env vars to override default pricing[/]"
    )
    console.print()

    # Build dimension data with context
    dims_data = []
    dims = [
        ("decision_drift", "Decision patterns", report.decision_drift),
        ("latency_drift", "Latency", report.latency_drift),
        (
            "planning_latency_drift",
            "Planning latency",
            getattr(report, "planning_latency_drift", 0.0),
        ),
        ("error_drift", "Error rate", report.error_drift),
        ("semantic_drift", "Outcome patterns", getattr(report, "semantic_drift", 0.0)),
        ("verbosity_drift", "Verbosity", getattr(report, "verbosity_drift", 0.0)),
        (
            "loop_depth_drift",
            "Reasoning depth",
            getattr(report, "loop_depth_drift", 0.0),
        ),
        (
            "tool_sequence_drift",
            "Tool sequencing",
            getattr(report, "tool_sequence_drift", 0.0),
        ),
        ("retry_drift", "Retry rate", getattr(report, "retry_drift", 0.0)),
        ("output_drift", "Output structure", getattr(report, "output_drift", 0.0)),
        (
            "output_length_drift",
            "Output length",
            getattr(report, "output_length_drift", 0.0),
        ),
    ]

    for dim_key, dim_name, score in dims:
        status = _dimension_status(score)

        # Build context string
        context = ""
        if dim_key == "decision_drift" and score > 0.2:
            baseline_esc = getattr(report, "baseline_escalation_rate", 0.0) * 100
            current_esc = getattr(report, "current_escalation_rate", 0.0) * 100
            if baseline_esc > 0 or current_esc > 0:
                context = f"escalation {baseline_esc:.0f}% → {current_esc:.0f}%"
                if current_esc > baseline_esc * 1.5:
                    multiplier = current_esc / max(baseline_esc, 1)
                    context += f" ({multiplier:.1f}× to humans)"
            else:
                context = "outcome distribution changed"
        elif dim_key == "latency_drift" and score > 0.15:
            baseline_p95 = getattr(report, "baseline_p95_latency_ms", 0.0)
            current_p95 = getattr(report, "current_p95_latency_ms", 0.0)
            if baseline_p95 > 0:
                context = f"p95: {baseline_p95:.0f}ms → {current_p95:.0f}ms"
            else:
                pct_change = score * 100
                context = f"p95 +{pct_change:.0f}%"
        elif dim_key == "error_drift":
            baseline_err = getattr(report, "baseline_error_rate", 0.0) * 100
            current_err = getattr(report, "current_error_rate", 0.0) * 100
            if score >= 0.05:
                if baseline_err > 0 or current_err > 0:
                    context = f"{baseline_err:.1f}% → {current_err:.1f}%"
                else:
                    err_pct = score * 50
                    context = f"+{err_pct:.1f}%"
        elif dim_key == "verbosity_drift" and score > 0.15:
            baseline_v = getattr(report, "baseline_avg_verbosity_ratio", 0.0)
            current_v = getattr(report, "current_avg_verbosity_ratio", 0.0)
            if baseline_v > 0 or current_v > 0:
                pct_change = (
                    ((current_v - baseline_v) / baseline_v * 100)
                    if baseline_v > 0
                    else 0
                )
                if pct_change > 0:
                    context = f"+{pct_change:.0f}% wordier"
                else:
                    context = f"{pct_change:.0f}% more concise"
            else:
                context = "output style changed"
        elif dim_key == "loop_depth_drift" and score > 0.15:
            baseline_loop = getattr(report, "baseline_avg_loop_count", 0.0)
            current_loop = getattr(report, "current_avg_loop_count", 0.0)
            if baseline_loop > 0 or current_loop > 0:
                context = f"{baseline_loop:.1f} → {current_loop:.1f} steps"
            else:
                context = "iteration pattern changed"
        elif dim_key == "tool_sequence_drift" and score > 0.15:
            context = "different ordering"
        elif dim_key == "retry_drift" and score > 0.15:
            baseline_retry = getattr(report, "baseline_avg_retry_count", 0.0)
            current_retry = getattr(report, "current_avg_retry_count", 0.0)
            if baseline_retry > 0 or current_retry > 0:
                context = f"{baseline_retry:.2f} → {current_retry:.2f}"
            else:
                context = "reliability changed"
        elif dim_key == "planning_latency_drift" and score > 0.15:
            baseline_plan = getattr(report, "baseline_avg_time_to_first_tool_ms", 0.0)
            current_plan = getattr(report, "current_avg_time_to_first_tool_ms", 0.0)
            if baseline_plan > 0 or current_plan > 0:
                context = f"{baseline_plan:.0f}ms → {current_plan:.0f}ms thinking time"
            else:
                context = "planning behavior changed"
        elif dim_key == "semantic_drift" and score > 0.15:
            baseline_esc = getattr(report, "baseline_escalation_rate", 0.0) * 100
            current_esc = getattr(report, "current_escalation_rate", 0.0) * 100
            if baseline_esc > 0 or current_esc > 0:
                context = f"escalated: {baseline_esc:.0f}% → {current_esc:.0f}%"
            else:
                context = "outcome distribution changed"
        elif dim_key == "output_drift" and score > 0.15:
            baseline_out = getattr(report, "baseline_avg_output_length", 0.0)
            current_out = getattr(report, "current_avg_output_length", 0.0)
            if baseline_out > 0 or current_out > 0:
                pct_change = (
                    ((current_out - baseline_out) / baseline_out * 100)
                    if baseline_out > 0
                    else 0
                )
                context = f"structure {pct_change:+.0f}%"
            else:
                context = "format changed"
        elif dim_key == "output_length_drift" and score > 0.15:
            baseline_len = getattr(report, "baseline_avg_output_length", 0.0)
            current_len = getattr(report, "current_avg_output_length", 0.0)
            if baseline_len > 0 or current_len > 0:
                context = f"{baseline_len:.0f} → {current_len:.0f} chars"
            else:
                context = "detail level changed"

        dims_data.append((dim_name, score, status, context))

    # Sort by score (highest first) so critical issues appear at top
    dims_data.sort(key=lambda x: x[1], reverse=True)

    # Create dimensions table
    dim_table = Table(
        show_header=True,
        header_style="bold #8B5CF6",  # Purple-blue header
        border_style="dim",
        box=None,
        pad_edge=False,
        collapse_padding=False,
        show_edge=False,
    )
    dim_table.add_column("Dimension", style="", width=20)
    dim_table.add_column("Score", justify="center", width=8)
    dim_table.add_column("Status", justify="center", width=12)
    dim_table.add_column("Details", style="dim", width=40)

    for dim_name, score, status, context in dims_data:
        # Color and symbol based on score - modern palette
        if score >= 0.5:
            score_style = "#FF6B6B bold"  # Coral red for critical
            symbol = "⚠"
        elif score >= 0.2:
            score_style = "#FFA94D"  # Orange for moderate
            symbol = "△"
        elif score >= 0.1:
            score_style = "bright_black"  # Gray for low
            symbol = "○"
        else:
            score_style = "#4ADE80"  # Green for stable
            symbol = "✓"

        # Status styling - consistent colors
        if status == "HIGH":
            status_display = f"[#FF6B6B]{symbol} {status}[/]"
        elif status == "MODERATE":
            status_display = f"[#FFA94D]{symbol} {status}[/]"
        elif status == "LOW":
            status_display = f"[bright_black]{symbol} {status}[/]"
        else:
            status_display = f"[#4ADE80]{symbol} {status}[/]"

        dim_table.add_row(
            dim_name,
            f"[{score_style}]{score:.2f}[/]",
            status_display,
            context if context else "—",
        )

    console.print(dim_table)
    console.print()
    console.print("─" * 60)

    from driftbase.local.hypothesis_engine import generate_hypotheses

    hypotheses = generate_hypotheses(
        report, baseline_tools, current_tools, baseline_n, current_n
    )

    verdict_symbol = verdict_result.symbol
    verdict_title = f"{verdict_symbol}  {verdict_result.title}"

    verdict_content = verdict_result.explanation

    # Include all hypotheses in the verdict box (not just top one)
    if hypotheses:
        verdict_content += "\n\n[bold]Root cause analysis:[/]"
        for i, h in enumerate(hypotheses):
            verdict_content += f"\n  → {h['observation']}"
            verdict_content += f"\n    [dim]{h['likely_cause']}[/]"
            verdict_content += f"\n    [dim]Action: {h['recommended_action']}[/]"
            # Add spacing between hypotheses if there are multiple
            if i < len(hypotheses) - 1:
                verdict_content += "\n"

    verdict_content += "\n\n[bold]Next steps:[/]\n" + "\n".join(
        f"  □ {step}" for step in verdict_result.next_steps
    )

    console.print(
        Panel(
            verdict_content,
            title=f"[bold {verdict_result.style}]VERDICT  {verdict_title}[/]",
            border_style=verdict_result.style,
            width=100,
        )
    )
    console.print()

    # Budget section (if budgets exist for the current version)
    try:
        from driftbase.backends.factory import get_backend

        backend = get_backend()
        # Try to get budget breaches for the current version
        breaches = backend.get_budget_breaches(version=current_label)
        budget_config_row = backend.get_budget_config(
            agent_id="", version=current_label
        )

        # Show budget section if config exists or breaches exist
        if budget_config_row or breaches:
            budget_table = Table(
                title=f"Budget ({current_label})",
                show_header=True,
                header_style="bold #8B5CF6",
                border_style="dim",
                width=100,
            )
            budget_table.add_column("Dimension", style="", width=25)
            budget_table.add_column("Limit", justify="right", width=15)
            budget_table.add_column("Actual", justify="right", width=15)
            budget_table.add_column("Status", justify="center", width=20)
            budget_table.add_column("Window", justify="center", width=15)

            # Get budget config
            budget_limits = {}
            if budget_config_row:
                budget_limits = budget_config_row.get("config", {})

            # Create a map of breaches by budget_key
            breaches_map = {b["budget_key"]: b for b in breaches}

            # Display all budget keys from config
            for budget_key, limit_value in budget_limits.items():
                breach = breaches_map.get(budget_key)

                if breach:
                    # Breached
                    actual_value = breach["actual"]
                    run_count = breach["run_count"]

                    # Format values based on dimension
                    if "latency" in budget_key:
                        limit_str = f"{limit_value:.1f}s"
                        actual_str = f"{actual_value / 1000:.1f}s"
                    elif "rate" in budget_key or "ratio" in budget_key:
                        limit_str = f"{limit_value * 100:.1f}%"
                        actual_str = f"{actual_value * 100:.1f}%"
                    else:
                        limit_str = f"{limit_value:.1f}"
                        actual_str = f"{actual_value:.1f}"

                    status = "[#FF6B6B bold]BREACHED[/]"
                    window_str = f"n={run_count}"
                else:
                    # No breach - would need to compute current value
                    # For now, just show as "ok" without actual value
                    if "latency" in budget_key:
                        limit_str = f"{limit_value:.1f}s"
                    elif "rate" in budget_key or "ratio" in budget_key:
                        limit_str = f"{limit_value * 100:.1f}%"
                    else:
                        limit_str = f"{limit_value:.1f}"

                    actual_str = "—"
                    status = "[#4ADE80]ok[/]"
                    window_str = "—"

                budget_table.add_row(
                    budget_key.replace("_", " "),
                    limit_str,
                    actual_str,
                    status,
                    window_str,
                )

            console.print(budget_table)
            console.print()
    except Exception as e:
        logger.debug(f"Failed to display budget section: {e}")

    # Root Cause section
    try:
        root_cause = getattr(report, "root_cause", None)
        if root_cause and root_cause.has_changes:
            # Only show if winner has HIGH or MEDIUM confidence
            if root_cause.winner_confidence in ("HIGH", "MEDIUM"):
                from rich.text import Text

                root_table = Table(
                    title="Root Cause",
                    show_header=False,
                    border_style="dim",
                    width=100,
                    box=None,
                )
                root_table.add_column("Label", style="dim", width=20)
                root_table.add_column("Value", width=75)

                # Most likely cause
                change_display = root_cause.winner.replace("_", " ")
                if root_cause.winner_previous and root_cause.winner_current:
                    change_detail = (
                        f"{root_cause.winner_previous} → {root_cause.winner_current}"
                    )
                else:
                    change_detail = root_cause.winner_current or "changed"

                confidence_color = (
                    "#4ADE80" if root_cause.winner_confidence == "HIGH" else "#FFA94D"
                )
                root_table.add_row(
                    "Most likely cause",
                    f"[bold]{change_display}[/]  (confidence: [{confidence_color}]{root_cause.winner_confidence}[/])\n"
                    f"[dim]{change_detail}[/]",
                )

                # Affected dimensions
                if root_cause.affected_dimensions:
                    affected_str = "  ".join(
                        [f"{d} ✓" for d in root_cause.affected_dimensions]
                    )
                    root_table.add_row("Affected dims", affected_str)

                # Ruled out
                if root_cause.ruled_out:
                    ruled_out_str = "  ".join(
                        [f"{r} (unchanged)" for r in root_cause.ruled_out]
                    )
                    root_table.add_row("Ruled out", f"[dim]{ruled_out_str}[/]")

                # Suggested action
                if root_cause.suggested_action:
                    root_table.add_row("Suggested action", root_cause.suggested_action)

                console.print(root_table)
                console.print()
            elif root_cause.winner_confidence in ("LOW", "UNLIKELY"):
                # Low confidence - show brief message
                console.print(
                    "[dim]Root cause inconclusive — multiple changes recorded but weak correlation with drifted dimensions.[/]"
                )
                if root_cause.all_scores:
                    recorded_changes = ", ".join(root_cause.all_scores.keys())
                    console.print(f"[dim]Recorded changes: {recorded_changes}[/]")
                console.print()
    except Exception as e:
        logger.debug(f"Failed to display root cause section: {e}")

    # Rollback section
    try:
        rollback = getattr(report, "rollback_suggestion", None)
        if rollback:
            rollback_table = Table(
                title="Rollback",
                show_header=False,
                border_style="dim",
                width=100,
                box=None,
            )
            rollback_table.add_column("Label", style="dim", width=20)
            rollback_table.add_column("Value", width=75)

            # Rollback target
            rollback_table.add_row(
                "Suggested version", f"[bold]{rollback.suggested_version}[/]"
            )

            # Reason
            rollback_table.add_row("Reason", rollback.reason)

            # Command
            rollback_table.add_row(
                "Command",
                f"[dim]driftbase rollback <agent_id> {rollback.suggested_version}[/]",
            )

            console.print(rollback_table)
            console.print(
                "[dim]Note: Driftbase does not execute rollbacks. This is the version to target in your deploy pipeline.[/]"
            )
            console.print()
    except Exception as e:
        logger.debug(f"Failed to display rollback section: {e}")

    if getattr(report, "sample_size_warning", False):
        console.print(
            Panel(
                "Low sample count — confidence interval may be wide. Run more iterations for a tighter estimate.",
                title="[bold yellow]⚠  Sample Size Warning[/]",
                border_style="#FFA94D",
                width=100,
            )
        )
        console.print()

    tools_table = Table(
        title="Tool call frequency diff",
        show_header=True,
        header_style="bold #8B5CF6",  # Purple-blue header
        border_style="dim",
    )
    tools_table.add_column("Tool", style="")
    tools_table.add_column("Baseline count", justify="right")
    tools_table.add_column("Current count", justify="right")
    tools_table.add_column("Baseline %", justify="right")
    tools_table.add_column("Current %", justify="right")
    tools_table.add_column("Δ %", justify="right")

    for row in tool_frequency_diffs[:20]:
        delta_pct = row["delta_pct"]
        # Modern color palette - only color the delta percentage
        abs_delta = abs(delta_pct)
        if abs_delta > 100:
            delta_style = "#FF6B6B bold"  # Coral red for extreme changes
        elif abs_delta > 50:
            delta_style = "#FF8787"  # Light red for high changes
        elif abs_delta > 20:
            delta_style = "#FFA94D"  # Orange for moderate changes
        else:
            delta_style = "bright_black"  # Gray for small changes

        tools_table.add_row(
            row["tool"],  # Tool name stays default color
            str(row["baseline_count"]),
            str(row["current_count"]),
            f"{row['baseline_pct']:.0f}%",
            f"{row['current_pct']:.0f}%",
            f"[{delta_style}]{delta_pct:+.0f}%[/]",
        )

    console.print(tools_table)

    if top_sequence_shifts_list:
        seq_table = Table(
            title="Tool Sequence Changes (Markov transitions showing workflow pattern shifts)",
            show_header=True,
            header_style="bold #8B5CF6",  # Purple-blue header
            border_style="dim",
        )
        seq_table.add_column("Transition", style="", width=50)
        seq_table.add_column("Baseline", justify="right", width=10)
        seq_table.add_column("Current", justify="right", width=10)
        seq_table.add_column("Change", justify="right", width=12)
        seq_table.add_column("Impact", justify="left", width=15)

        for row in top_sequence_shifts_list:
            dp = row["delta_pct"]
            baseline_pct = row["baseline_pct"]
            current_pct = row["current_pct"]

            # Modern color palette - transition name stays default, only color Change and Impact
            if baseline_pct == 0 and current_pct > 0:
                # NEW pattern
                change_style = "#FF6B6B bold"
                impact = "[#FF6B6B]NEW pattern[/]"
                arrow = "→"
            elif current_pct == 0 and baseline_pct > 0:
                # REMOVED pattern
                change_style = "#FF6B6B bold"
                impact = "[#FF6B6B]REMOVED[/]"
                arrow = "×"
            elif abs(dp) > 5:
                # Major change (either direction) is high-impact
                change_style = "#FF8787"
                impact = "[#FF8787]Major shift[/]"
                arrow = "↑↑" if dp > 0 else "↓↓"
            elif abs(dp) > 2:
                # Moderate change
                change_style = "#FFA94D"
                impact = "[#FFA94D]Moderate shift[/]"
                arrow = "↑" if dp > 0 else "↓"
            else:
                change_style = "bright_black"
                impact = "[bright_black]Stable[/]"
                arrow = "→"

            seq_table.add_row(
                row["transition"],  # Transition name stays default color
                f"{baseline_pct:.1f}%",
                f"{current_pct:.1f}%",
                f"[{change_style}]{arrow} {dp:+.1f}%[/]",
                impact,
            )
        console.print(seq_table)
        console.print()

    console.print("─" * 60)
    footer_parts = []
    if getattr(report, "bootstrap_iterations", 0) > 0:
        footer_parts.append("95% CI via bootstrap")
    if compute_time_ms is not None:
        footer_parts.append(f"Computed in {compute_time_ms:.0f}ms")
    footer_parts.append("No data left your machine")
    footer = "  " + " · ".join(footer_parts)
    console.print(f"[dim]{footer}[/]")

    return verdict_result.exit_code


def diff_local(
    backend: StorageBackend,
    baseline_version: str,
    current_version: str,
    *,
    last_n: int | None = None,
    against_version: str | None = None,
    environment: str | None = None,
    threshold: float = DEFAULT_THRESHOLD,
    min_samples_warning: int = MIN_SAMPLES_WARNING,
) -> tuple[
    DriftReport | None,
    BehavioralFingerprint | None,
    BehavioralFingerprint | None,
    str | None,
]:
    """
    Compute drift between two run sets from the local backend.
    """
    if last_n is not None and against_version is not None:
        baseline_run_dicts = get_runs_for_version(
            backend, against_version, limit=5000, environment=environment
        )
        current_run_dicts = get_runs_for_version(
            backend, "local", limit=last_n, environment=environment
        )
        baseline_label = against_version
        current_label = f"last_{last_n}_runs"
    elif current_version == "local":
        baseline_run_dicts = get_runs_for_version(
            backend, baseline_version, limit=5000, environment=environment
        )
        current_run_dicts = get_runs_for_version(
            backend, "local", limit=500, environment=environment
        )
        baseline_label = baseline_version
        current_label = "local"
    else:
        baseline_run_dicts = get_runs_for_version(
            backend, baseline_version, limit=5000, environment=environment
        )
        current_run_dicts = get_runs_for_version(
            backend, current_version, limit=5000, environment=environment
        )
        baseline_label = baseline_version
        current_label = current_version

    min_runs_needed = 2
    if len(baseline_run_dicts) < min_runs_needed:
        return (
            None,
            None,
            None,
            f"\nNot enough runs to diff.\n"
            f"{baseline_label}: {len(baseline_run_dicts)} runs (need {min_runs_needed})\n"
            f"{current_label}: {len(current_run_dicts)} runs\n\n"
            f"Run your agent more, then try again.",
        )
    if len(current_run_dicts) < min_runs_needed:
        return (
            None,
            None,
            None,
            f"\nNot enough runs to diff.\n"
            f"{baseline_label}: {len(baseline_run_dicts)} runs\n"
            f"{current_label}: {len(current_run_dicts)} runs (need {min_runs_needed})\n\n"
            f"Run your agent more, then try again.",
        )

    baseline_fp = fingerprint_from_runs(
        baseline_run_dicts, baseline_label, environment or "production"
    )
    current_fp = fingerprint_from_runs(
        current_run_dicts, current_label, environment or "production"
    )
    if baseline_fp is None or current_fp is None:
        return None, None, None, "Failed to build fingerprints"

    report = compute_drift(
        baseline_fp, current_fp, baseline_run_dicts, current_run_dicts
    )

    # Root cause correlation
    try:
        from driftbase.local.rootcause import correlate_drift_with_changes

        # Extract agent_id from runs (use first run's session_id, or empty string)
        agent_id = ""
        if baseline_run_dicts:
            agent_id = baseline_run_dicts[0].get("session_id", "")
        elif current_run_dicts:
            agent_id = current_run_dicts[0].get("session_id", "")

        # Get change events for both versions
        change_events = backend.get_change_events_for_versions(
            agent_id, baseline_label, current_label
        )

        # Identify drifted dimensions (above MONITOR threshold = 0.15)
        drifted_dimensions = []
        threshold = 0.15
        if report.decision_drift > threshold:
            drifted_dimensions.append("decision_drift")
        if report.latency_drift > threshold:
            drifted_dimensions.append("latency_drift")
        if report.error_drift > threshold:
            drifted_dimensions.append("error_drift")
        if report.semantic_drift > threshold:
            drifted_dimensions.append("semantic_drift")
        if report.verbosity_drift > threshold:
            drifted_dimensions.append("verbosity_drift")
        if report.output_length_drift > threshold:
            drifted_dimensions.append("output_length_drift")
        if report.tool_sequence_drift > threshold:
            drifted_dimensions.append("tool_sequence_drift")
        if report.retry_drift > threshold:
            drifted_dimensions.append("retry_drift")
        if getattr(report, "error_rate", 0.0) > threshold:
            drifted_dimensions.append("error_rate")

        # Correlate drift with changes
        if change_events.get("v1") or change_events.get("v2"):
            root_cause = correlate_drift_with_changes(
                report, change_events, drifted_dimensions
            )
            report.root_cause = root_cause
    except Exception:
        # Never crash on root cause failure
        pass

    # Rollback suggestion
    try:
        from driftbase.local.rootcause import get_rollback_suggestion
        from driftbase.verdict import compute_verdict

        # Need to compute verdict to know if it's BLOCK/REVIEW
        verdict_result = compute_verdict(
            report,
            baseline_tools=baseline_fp.tool_call_distribution if baseline_fp else {},
            current_tools=current_fp.tool_call_distribution if current_fp else {},
            baseline_n=len(baseline_run_dicts),
            current_n=len(current_run_dicts),
            baseline_label=baseline_label,
            current_label=current_label,
        )

        rollback = get_rollback_suggestion(
            agent_id=agent_id,
            eval_version=current_label,
            current_verdict=verdict_result.verdict.value.upper(),
            baseline_version=baseline_label,
            baseline_run_count=len(baseline_run_dicts),
        )
        report.rollback_suggestion = rollback
    except Exception:
        # Never crash on rollback suggestion failure
        pass

    return report, baseline_fp, current_fp, None


def run_diff(
    baseline_version: str,
    current_version: str,
    *,
    last_n: int | None = None,
    against_version: str | None = None,
    environment: str | None = None,
    threshold: float = DEFAULT_THRESHOLD,
    json_output: bool = False,
    use_color: bool = True,
    backend: StorageBackend | None = None,
    console: Console | None = None,
    fail_on_drift: bool = False,
    exit_nonzero_above: float | None = None,
) -> int:
    """Run diff and print via rich. Returns 0 on success, 1 on error or above threshold (for CI)."""
    if backend is None:
        from driftbase.backends.factory import get_backend

        backend = get_backend()

    if console is None:
        console = Console(no_color=not use_color)

    t0 = time.perf_counter()
    report, baseline_fp, current_fp, err = diff_local(
        backend,
        baseline_version,
        current_version,
        last_n=last_n,
        against_version=against_version,
        environment=environment,
        threshold=threshold,
    )
    elapsed_ms = (time.perf_counter() - t0) * 1000

    if err:
        console.print(
            Panel(err, title="[bold red]Error[/]", border_style="#FF6B6B"),
        )
        return 1
    if report is None or baseline_fp is None or current_fp is None:
        console.print(
            Panel(
                "Failed to compute diff.",
                title="[bold red]Error[/]",
                border_style="#FF6B6B",
            ),
        )
        return 1

    baseline_n = baseline_fp.sample_count
    current_n = current_fp.sample_count

    if baseline_n < MIN_SAMPLES_WARNING or current_n < MIN_SAMPLES_WARNING:
        console.print(
            Panel(
                f"Minimum recommended sample size is [bold]{MIN_SAMPLES_WARNING}[/]. "
                f"Baseline n={baseline_n}, current n={current_n}. Results may be noisy.",
                title="[bold yellow]⚠ Low sample size[/]",
                border_style="#FFA94D",
            ),
        )

    baseline_label = baseline_fp.deployment_version
    current_label = current_fp.deployment_version
    if last_n and against_version:
        current_label = f"last_{last_n}_runs"
    elif current_version == "local":
        current_label = "local"

    if last_n and against_version:
        current_run_dicts = get_runs_for_version(
            backend, "local", limit=last_n, environment=environment
        )
        baseline_run_dicts = get_runs_for_version(
            backend, against_version, limit=5000, environment=environment
        )
    elif current_version == "local":
        baseline_run_dicts = get_runs_for_version(
            backend, baseline_version, limit=5000, environment=environment
        )
        current_run_dicts = get_runs_for_version(
            backend, "local", limit=500, environment=environment
        )
    else:
        baseline_run_dicts = get_runs_for_version(
            backend, baseline_version, limit=5000, environment=environment
        )
        current_run_dicts = get_runs_for_version(
            backend, current_version, limit=5000, environment=environment
        )

    baseline_tools = tool_usage_distribution(baseline_run_dicts)
    current_tools = tool_usage_distribution(current_run_dicts)

    tool_frequency_diffs = tool_frequency_diff(baseline_run_dicts, current_run_dicts)
    top_sequence_shifts_list = top_sequence_shifts(
        baseline_run_dicts, current_run_dicts, top_n=10
    )
    explanation = build_explanation(
        report, baseline_fp, current_fp, tool_frequency_diffs, threshold
    )

    if json_output:
        from driftbase.verdict import compute_verdict

        verdict_result = compute_verdict(
            report,
            baseline_tools=baseline_tools,
            current_tools=current_tools,
            baseline_n=baseline_n,
            current_n=current_n,
            baseline_label=baseline_label,
            current_label=current_label,
        )
        out = {
            "schema_version": "1.0",
            "baseline_version": baseline_label,
            "current_version": current_label,
            "baseline_n": baseline_n,
            "current_n": current_n,
            "drift_score": report.drift_score,
            "severity": report.severity,
            "verdict": verdict_result.verdict.value,
            "verdict_title": verdict_result.title,
            "verdict_explanation": verdict_result.explanation,
            "next_steps": verdict_result.next_steps,
            "above_threshold": report.drift_score >= threshold,
            "threshold": threshold,
            "decision_drift": report.decision_drift,
            "latency_drift": report.latency_drift,
            "error_drift": report.error_drift,
            "verbosity_drift": getattr(report, "verbosity_drift", 0.0),
            "loop_depth_drift": getattr(report, "loop_depth_drift", 0.0),
            "tool_sequence_drift": getattr(report, "tool_sequence_drift", 0.0),
            "retry_drift": getattr(report, "retry_drift", 0.0),
            "planning_latency_drift": getattr(report, "planning_latency_drift", 0.0),
            "output_length_drift": getattr(report, "output_length_drift", 0.0),
            "tool_frequency_diffs": tool_frequency_diffs,
            "top_sequence_shifts": top_sequence_shifts_list,
            "tool_changes": {
                t: {
                    "baseline_pct": baseline_tools.get(t, 0) * 100,
                    "current_pct": current_tools.get(t, 0) * 100,
                }
                for t in sorted(set(baseline_tools.keys()) | set(current_tools.keys()))
            },
            "computed_ms": round(elapsed_ms, 1),
        }
        # Add cost per 10k when token data is available
        baseline_cost_10k = calculate_cost_per_10k(baseline_run_dicts)
        current_cost_10k = calculate_cost_per_10k(current_run_dicts)
        out["cost_per_10k_baseline_eur"] = round(baseline_cost_10k, 2)
        out["cost_per_10k_current_eur"] = round(current_cost_10k, 2)
        out["cost_per_10k_delta_eur"] = round(current_cost_10k - baseline_cost_10k, 2)
        rate_p, rate_c = get_rates_for_display()
        out["rate_prompt_eur_per_1m"] = rate_p
        out["rate_completion_eur_per_1m"] = rate_c
        if report.drift_score >= threshold and explanation:
            out["explanation"] = explanation
        console.print(json.dumps(out, indent=2))

        # CI exit code logic
        if (fail_on_drift and report.drift_score > 0) or (
            exit_nonzero_above is not None and report.drift_score > exit_nonzero_above
        ):
            return 1
        else:
            return verdict_result.exit_code

    baseline_cost_10k = calculate_cost_per_10k(baseline_run_dicts)
    current_cost_10k = calculate_cost_per_10k(current_run_dicts)
    exit_code = render_diff_report(
        console,
        report,
        baseline_label,
        current_label,
        baseline_n,
        current_n,
        baseline_tools,
        current_tools,
        tool_frequency_diffs,
        top_sequence_shifts_list,
        explanation,
        threshold=threshold,
        compute_time_ms=elapsed_ms,
        baseline_cost_per_10k=baseline_cost_10k,
        current_cost_per_10k=current_cost_10k,
    )

    # Non-JSON CI exit code logic
    if (fail_on_drift and report.drift_score > 0) or (
        exit_nonzero_above is not None and report.drift_score > exit_nonzero_above
    ):
        return 1

    return exit_code


def run_watch(
    against_version: str,
    *,
    interval_seconds: float = 5.0,
    min_runs: int = 10,
    last_n: int = 20,
    environment: str | None = None,
    threshold: float = DEFAULT_THRESHOLD,
    use_color: bool = True,
    backend: StorageBackend | None = None,
    console: Console | None = None,
    max_iterations: int | None = None,
    notify: bool = False,
) -> None:
    """Poll backend and print live diff via rich; exit on Ctrl+C."""
    if backend is None:
        from driftbase.backends.factory import get_backend

        backend = get_backend()

    if console is None:
        console = Console(no_color=not use_color)

    # Check notification support if enabled
    if notify:
        from driftbase.utils.notify import is_notification_supported

        if not is_notification_supported():
            console.print(
                "#FFA94D]⚠[/] Desktop notifications not supported on this platform"
            )
            console.print(
                "[dim]Continuing without notifications. Install required packages:[/]"
            )
            console.print("  macOS:   No additional packages needed")
            console.print("  Linux:   Install notify-send (libnotify-bin package)")
            console.print("  Windows: pip install win10toast")
            notify = False

    iteration = 0
    last_drift_alert = None  # Track last alert to avoid spam

    try:
        while True:
            if max_iterations is not None and iteration >= max_iterations:
                break
            iteration += 1

            baseline_run_dicts = get_runs_for_version(
                backend, against_version, limit=5000, environment=environment
            )
            current_run_dicts = get_runs_for_version(
                backend, "local", limit=last_n, environment=environment
            )
            n_current = len(current_run_dicts)
            if n_current < min_runs:
                console.clear()
                console.print(
                    f"[bold]DRIFTBASE WATCH[/] — live · polling every {interval_seconds}s · against [#8B5CF6]{against_version}[/]"
                )
                console.print(
                    f"[dim]Waiting for at least {min_runs} runs (have {n_current}). Ctrl+C to exit.[/]"
                )
                time.sleep(interval_seconds)
                continue

            report, baseline_fp, current_fp, err = diff_local(
                backend,
                against_version,
                "local",
                last_n=last_n,
                against_version=against_version,
                environment=environment,
                threshold=threshold,
            )
            console.clear()
            now = datetime.utcnow().strftime("%H:%M:%S")
            console.print(
                f"[bold]DRIFTBASE WATCH[/] — live · every {interval_seconds}s · against [#8B5CF6]{against_version}[/]"
            )
            console.print(
                f"[dim]Last updated: {now} · {n_current} runs in current window[/]"
            )
            console.rule(style="dim")

            if err:
                console.print(
                    Panel(err, title="[bold red]Error[/]", border_style="#FF6B6B"),
                )
            elif report and baseline_fp and current_fp:
                baseline_tools = tool_usage_distribution(baseline_run_dicts)
                current_tools = tool_usage_distribution(current_run_dicts)
                tool_frequency_diffs = tool_frequency_diff(
                    baseline_run_dicts, current_run_dicts
                )
                top_sequence_shifts_list = top_sequence_shifts(
                    baseline_run_dicts, current_run_dicts, top_n=10
                )
                explanation = build_explanation(
                    report,
                    baseline_fp,
                    current_fp,
                    tool_frequency_diffs,
                    threshold,
                )
                baseline_cost_10k = calculate_cost_per_10k(baseline_run_dicts)
                current_cost_10k = calculate_cost_per_10k(current_run_dicts)
                render_diff_report(
                    console,
                    report,
                    against_version,
                    "current",
                    baseline_fp.sample_count,
                    current_fp.sample_count,
                    baseline_tools,
                    current_tools,
                    tool_frequency_diffs,
                    top_sequence_shifts_list,
                    explanation,
                    threshold=threshold,
                    baseline_cost_per_10k=baseline_cost_10k,
                    current_cost_per_10k=current_cost_10k,
                )

                # Send notification if drift detected and notifications enabled
                if notify and report.drift_score >= threshold:
                    # Only send notification if different from last alert (avoid spam)
                    current_alert_key = f"{report.drift_score:.3f}"
                    if current_alert_key != last_drift_alert:
                        from driftbase.utils.notify import send_drift_alert

                        success = send_drift_alert(
                            baseline_version=against_version,
                            current_version="current",
                            drift_score=report.drift_score,
                            threshold=threshold,
                        )
                        if success:
                            last_drift_alert = current_alert_key

            console.print("[dim]Ctrl+C to exit.[/]")
            if max_iterations is not None and iteration >= max_iterations:
                break
            time.sleep(interval_seconds)
    except KeyboardInterrupt:
        console.print("\n[dim]Exiting watch.[/]")
        sys.exit(0)
