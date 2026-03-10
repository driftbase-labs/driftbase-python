"""
Local CLI diff and watch: compute drift from local backend (SQLite/Postgres) runs.
All computation runs locally; no cloud connection. Output via rich Console/Table/Panel.
"""

from __future__ import annotations

import json
import sys
import time
from collections import Counter
from datetime import datetime
from typing import Any, Optional

import click
from driftbase.backends.base import StorageBackend
from driftbase.local.diff import compute_drift
from driftbase.local.fingerprinter import build_fingerprint_from_runs
from driftbase.local.rootcause import (
    build_explanation,
    top_sequence_shifts,
    tool_frequency_diff,
)
from driftbase.local.local_store import AgentRun, BehavioralFingerprint, DriftReport, run_dict_to_agent_run
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

MIN_SAMPLES_WARNING = 50
DEFAULT_THRESHOLD = 0.20


@click.command(name="diff")
@click.argument("baseline", required=False)
@click.argument("current", required=False)
@click.option("--last", "-n", type=int, metavar="N", help="Use last N runs as current (use with --against).")
@click.option("--against", metavar="VERSION", help="Baseline version (with --last).")
@click.option("--environment", "-e", default=None, help="Filter by environment.")
@click.option("--threshold", "-t", type=float, default=0.20, help="Drift threshold (default 0.20).")
@click.option("--json", "json_output", is_flag=True, help="Machine-readable output for CI.")
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
) -> None:
    """Compare two versions or last N runs vs baseline (local SQLite)."""
    from driftbase.backends.factory import get_backend

    console: Console = ctx.obj["console"]
    use_color = not console.no_color

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
        )
        ctx.exit(code)

    if (baseline == "local" or current == "local") and (baseline is None or current is None):
        backend = get_backend()
        versions = backend.get_versions()
        if not versions:
            console.print(
                Panel(
                    "No versions in DB; cannot diff 'local' without a baseline. Use: driftbase diff VERSION local",
                    title="Error",
                    border_style="red",
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
        )
        ctx.exit(code)

    if baseline is None or current is None:
        console.print(
            Panel(
                "Either provide two versions (e.g. driftbase diff v1.0 v2.0) or use --last N --against VERSION",
                title="Error",
                border_style="red",
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
    )
    ctx.exit(code)


def get_runs_for_version(
    backend: StorageBackend,
    version: str,
    limit: int = 5000,
    environment: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Get runs for a version. Use version='local' for last N runs (no version filter)."""
    if version == "local":
        return backend.get_runs(deployment_version=None, environment=environment, limit=limit)
    return backend.get_runs(
        deployment_version=version, environment=environment, limit=limit
    )


def fingerprint_from_runs(
    run_dicts: list[dict[str, Any]],
    label: str,
    environment: str = "production",
) -> Optional[BehavioralFingerprint]:
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
    compute_time_ms: Optional[float] = None,
) -> int:
    """Render drift report using rich Table and Panel (no raw ANSI).

    Returns:
        Exit code (0 for SHIP/MONITOR, 1 for REVIEW/BLOCK)
    """
    from driftbase.verdict import compute_verdict

    # Compute verdict
    verdict_result = compute_verdict(
        report,
        baseline_tools=baseline_tools,
        current_tools=current_tools,
        baseline_n=baseline_n,
        current_n=current_n,
    )

    # Header
    console.print("─" * 60)
    console.print(
        f"  [bold]DRIFTBASE[/]  {baseline_label} → {current_label}  ·  {baseline_n} vs {current_n} runs"
    )
    console.print("─" * 60)
    console.print()

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
            ci_display = f"  [{lower:.2f}–{upper:.2f}, 95% CI]"
    console.print(f"  Overall drift      [bold]{report.drift_score:.2f}[/]{ci_display}")
    console.print()

    # Dimension breakdown with status indicators
    dims = [
        ("decision_drift", "Decisions", report.decision_drift),
        ("latency_drift", "Latency", report.latency_drift),
        ("error_drift", "Errors", report.error_drift),
    ]

    for dim_key, dim_name, score in dims:
        status = _dimension_status(score)
        style = _dimension_style(score, threshold)

        # Status symbol
        if score >= 0.5:
            symbol = "⚠"
        elif score >= 0.2:
            symbol = "·"
        elif score >= 0.1:
            symbol = "·"
        else:
            symbol = "✓"

        # Context line with before→after values
        context = ""
        if dim_key == "decision_drift" and score > 0.2:
            # Show escalation rate: before → after
            baseline_esc = getattr(report, "baseline_escalation_rate", 0.0) * 100
            current_esc = getattr(report, "current_escalation_rate", 0.0) * 100
            if baseline_esc > 0 or current_esc > 0:
                context = f"\n    └─ escalation rate jumped from {baseline_esc:.0f}% → {current_esc:.0f}%"
                if current_esc > baseline_esc * 1.5:
                    multiplier = current_esc / max(baseline_esc, 1)
                    context += f"\n    └─ agent is routing {multiplier:.1f}× more to humans"
            else:
                context = "\n    └─ outcome distribution changed"
        elif dim_key == "latency_drift" and score > 0.15:
            # Show p95 latency: before → after
            baseline_p95 = getattr(report, "baseline_p95_latency_ms", 0.0)
            current_p95 = getattr(report, "current_p95_latency_ms", 0.0)
            if baseline_p95 > 0:
                context = f"\n    └─ p95 increased {baseline_p95:.0f}ms → {current_p95:.0f}ms"
            else:
                pct_change = score * 100
                context = f"\n    └─ p95 +{pct_change:.0f}%"
        elif dim_key == "error_drift":
            baseline_err = getattr(report, "baseline_error_rate", 0.0) * 100
            current_err = getattr(report, "current_error_rate", 0.0) * 100
            if score < 0.05:
                context = "\n    └─ stable"
            elif baseline_err > 0 or current_err > 0:
                context = f"\n    └─ error rate {baseline_err:.1f}% → {current_err:.1f}%"
            else:
                err_pct = score * 50
                context = f"\n    └─ error rate +{err_pct:.1f}%"

        console.print(
            f"  {dim_name:<18} [{style}]{score:.2f}  {symbol} {status}[/]{context}"
        )

    console.print()
    console.print("─" * 60)

    # Generate hypotheses to include top one in verdict panel
    from driftbase.local.hypothesis_engine import generate_hypotheses

    hypotheses = generate_hypotheses(
        report, baseline_tools, current_tools, baseline_n, current_n
    )

    # Verdict panel with integrated top hypothesis
    verdict_symbol = verdict_result.symbol
    verdict_title = f"{verdict_symbol}  {verdict_result.title}"

    # Build verdict panel content
    verdict_content = verdict_result.explanation

    # Add the top hypothesis if available (most critical insight)
    if hypotheses:
        top_hypothesis = hypotheses[0]
        verdict_content += f"\n\n[bold]Most likely cause:[/]\n  → {top_hypothesis['observation']}\n  [dim]{top_hypothesis['likely_cause']}[/]"

    # Add next steps
    verdict_content += f"\n\n[bold]Next steps:[/]\n" + "\n".join(
        f"  □ {step}" for step in verdict_result.next_steps
    )

    console.print(
        Panel(
            verdict_content,
            title=f"[bold {verdict_result.style}]VERDICT  {verdict_title}[/]",
            border_style=verdict_result.style,
        )
    )
    console.print()

    # Sample size warning (if applicable)
    if getattr(report, "sample_size_warning", False):
        console.print(
            Panel(
                "Low sample count — confidence interval may be wide. Run more iterations for a tighter estimate.",
                title="[bold yellow]⚠  Sample Size Warning[/]",
                border_style="yellow",
            )
        )
        console.print()

    # Tool call frequency diff table (absolute + percentage change per tool)
    tools_table = Table(
        title="Tool call frequency diff",
        show_header=True,
        header_style="bold",
        border_style="dim",
    )
    tools_table.add_column("Tool", style="cyan")
    tools_table.add_column("Baseline count", justify="right")
    tools_table.add_column("Current count", justify="right")
    tools_table.add_column("Baseline %", justify="right")
    tools_table.add_column("Current %", justify="right")
    tools_table.add_column("Δ %", justify="right")

    for row in tool_frequency_diffs[:20]:
        delta_pct = row["delta_pct"]
        delta_style = "red" if delta_pct > 10 else "green" if delta_pct < -10 else "dim"
        tools_table.add_row(
            row["tool"],
            str(row["baseline_count"]),
            str(row["current_count"]),
            f"{row['baseline_pct']:.0f}%",
            f"{row['current_pct']:.0f}%",
            f"[{delta_style}]{delta_pct:+.0f}%[/]",
        )

    console.print(tools_table)

    # Top sequence shifts (Markov transitions that changed most)
    if top_sequence_shifts_list:
        seq_table = Table(
            title="Top 3 sequence shifts (Markov transitions)",
            show_header=True,
            header_style="bold",
            border_style="dim",
        )
        seq_table.add_column("Transition", style="cyan")
        seq_table.add_column("Baseline %", justify="right")
        seq_table.add_column("Current %", justify="right")
        seq_table.add_column("Δ %", justify="right")
        for row in top_sequence_shifts_list:
            dp = row["delta_pct"]
            style = "red" if dp > 5 else "green" if dp < -5 else "dim"
            seq_table.add_row(
                row["transition"],
                f"{row['baseline_pct']:.1f}%",
                f"{row['current_pct']:.1f}%",
                f"[{style}]{dp:+.1f}%[/]",
            )
        console.print(seq_table)

    # Additional hypotheses (technical details) - show remaining ones if there are multiple
    if len(hypotheses) > 1:
        from driftbase.local.hypothesis_engine import format_hypotheses

        # Format all hypotheses except the first (which is in verdict)
        remaining_hypotheses = hypotheses[1:]
        hypothesis_text = format_hypotheses(remaining_hypotheses)
        console.print(
            Panel(
                hypothesis_text,
                title="[dim]Additional Analysis (hypothesis engine)[/]",
                border_style="dim",
            )
        )
        console.print()

    # Footer
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
    last_n: Optional[int] = None,
    against_version: Optional[str] = None,
    environment: Optional[str] = None,
    threshold: float = DEFAULT_THRESHOLD,
    min_samples_warning: int = MIN_SAMPLES_WARNING,
) -> tuple[Optional[DriftReport], Optional[BehavioralFingerprint], Optional[BehavioralFingerprint], Optional[str]]:
    """
    Compute drift between two run sets from the local backend.
    Returns (report, baseline_fp, current_fp, error_message).
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

    if len(baseline_run_dicts) < 2:
        return None, None, None, f"Insufficient baseline runs for '{baseline_label}' (got {len(baseline_run_dicts)})"
    if len(current_run_dicts) < 2:
        return None, None, None, f"Insufficient current runs for '{current_label}' (got {len(current_run_dicts)})"

    baseline_fp = fingerprint_from_runs(
        baseline_run_dicts, baseline_label, environment or "production"
    )
    current_fp = fingerprint_from_runs(
        current_run_dicts, current_label, environment or "production"
    )
    if baseline_fp is None or current_fp is None:
        return None, None, None, "Failed to build fingerprints"

    report = compute_drift(baseline_fp, current_fp, baseline_run_dicts, current_run_dicts)
    return report, baseline_fp, current_fp, None


def run_diff(
    baseline_version: str,
    current_version: str,
    *,
    last_n: Optional[int] = None,
    against_version: Optional[str] = None,
    environment: Optional[str] = None,
    threshold: float = DEFAULT_THRESHOLD,
    json_output: bool = False,
    use_color: bool = True,
    backend: Optional[StorageBackend] = None,
    console: Optional[Console] = None,
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
            Panel(err, title="[bold red]Error[/]", border_style="red"),
        )
        return 1
    if report is None or baseline_fp is None or current_fp is None:
        console.print(
            Panel(
                "Failed to compute diff.",
                title="[bold red]Error[/]",
                border_style="red",
            ),
        )
        return 1

    baseline_n = baseline_fp.sample_count
    current_n = current_fp.sample_count

    # Minimum sample size warning (yellow panel)
    if baseline_n < MIN_SAMPLES_WARNING or current_n < MIN_SAMPLES_WARNING:
        console.print(
            Panel(
                f"Minimum recommended sample size is [bold]{MIN_SAMPLES_WARNING}[/]. "
                f"Baseline n={baseline_n}, current n={current_n}. Results may be noisy.",
                title="[bold yellow]⚠ Low sample size[/]",
                border_style="yellow",
            ),
        )

    baseline_label = baseline_fp.deployment_version
    current_label = current_fp.deployment_version
    if last_n and against_version:
        current_label = f"last_{last_n}_runs"
    elif current_version == "local":
        current_label = "local"

    if last_n and against_version:
        current_run_dicts = get_runs_for_version(backend, "local", limit=last_n, environment=environment)
        baseline_run_dicts = get_runs_for_version(backend, against_version, limit=5000, environment=environment)
    elif current_version == "local":
        baseline_run_dicts = get_runs_for_version(backend, baseline_version, limit=5000, environment=environment)
        current_run_dicts = get_runs_for_version(backend, "local", limit=500, environment=environment)
    else:
        baseline_run_dicts = get_runs_for_version(backend, baseline_version, limit=5000, environment=environment)
        current_run_dicts = get_runs_for_version(backend, current_version, limit=5000, environment=environment)
    baseline_tools = tool_usage_distribution(baseline_run_dicts)
    current_tools = tool_usage_distribution(current_run_dicts)

    tool_frequency_diffs = tool_frequency_diff(baseline_run_dicts, current_run_dicts)
    top_sequence_shifts_list = top_sequence_shifts(
        baseline_run_dicts, current_run_dicts, top_n=3
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
        )
        out = {
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
            "tool_frequency_diffs": tool_frequency_diffs,
            "top_sequence_shifts": top_sequence_shifts_list,
            "tool_changes": {
                t: {"baseline_pct": baseline_tools.get(t, 0) * 100, "current_pct": current_tools.get(t, 0) * 100}
                for t in sorted(set(baseline_tools.keys()) | set(current_tools.keys()))
            },
            "computed_ms": round(elapsed_ms, 1),
        }
        if report.drift_score >= threshold and explanation:
            out["explanation"] = explanation
        console.print(json.dumps(out, indent=2))
        return verdict_result.exit_code

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
    )
    return exit_code


def run_watch(
    against_version: str,
    *,
    interval_seconds: float = 5.0,
    min_runs: int = 10,
    last_n: int = 20,
    environment: Optional[str] = None,
    threshold: float = DEFAULT_THRESHOLD,
    use_color: bool = True,
    backend: Optional[StorageBackend] = None,
    console: Optional[Console] = None,
    max_iterations: Optional[int] = None,
) -> None:
    """Poll backend and print live diff via rich; exit on Ctrl+C.
    If max_iterations is set (e.g. 1 for tests), stop after that many poll cycles."""
    if backend is None:
        from driftbase.backends.factory import get_backend
        backend = get_backend()

    if console is None:
        console = Console(no_color=not use_color)

    iteration = 0
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
                    f"[bold]DRIFTBASE WATCH[/] — live · polling every {interval_seconds}s · against [cyan]{against_version}[/]"
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
                f"[bold]DRIFTBASE WATCH[/] — live · every {interval_seconds}s · against [cyan]{against_version}[/]"
            )
            console.print(f"[dim]Last updated: {now} · {n_current} runs in current window[/]")
            console.rule(style="dim")

            if err:
                console.print(
                    Panel(err, title="[bold red]Error[/]", border_style="red"),
                )
            elif report and baseline_fp and current_fp:
                baseline_tools = tool_usage_distribution(baseline_run_dicts)
                current_tools = tool_usage_distribution(current_run_dicts)
                tool_frequency_diffs = tool_frequency_diff(
                    baseline_run_dicts, current_run_dicts
                )
                top_sequence_shifts_list = top_sequence_shifts(
                    baseline_run_dicts, current_run_dicts, top_n=3
                )
                explanation = build_explanation(
                    report, baseline_fp, current_fp,
                    tool_frequency_diffs, threshold,
                )
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
                )

            console.print("[dim]Ctrl+C to exit.[/]")
            if max_iterations is not None and iteration >= max_iterations:
                break
            time.sleep(interval_seconds)
    except KeyboardInterrupt:
        console.print("\n[dim]Exiting watch.[/]")
        sys.exit(0)
