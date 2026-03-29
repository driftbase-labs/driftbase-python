"""
Compare command: Batch comparisons and tournament mode for multiple versions.
"""

from __future__ import annotations

import click

from driftbase.backends.factory import get_backend


def _safe_import_rich():
    try:
        from rich.console import Console
        from rich.table import Table

        return Console, Table
    except ImportError:
        return None, None


def _fingerprint_from_runs(run_dicts: list, label: str) -> object | None:
    """Create fingerprint from run dicts."""
    try:
        from datetime import datetime

        from driftbase.local.fingerprinter import build_fingerprint_from_runs
        from driftbase.local.local_store import run_dict_to_agent_run

        if not run_dicts:
            return None

        runs = [run_dict_to_agent_run(r) for r in run_dicts]
        timestamps = [r.started_at for r in runs if r.started_at]
        window_start = min(timestamps) if timestamps else datetime.utcnow()
        window_end = max(timestamps) if timestamps else datetime.utcnow()

        return build_fingerprint_from_runs(
            runs, window_start, window_end, label, "production"
        )
    except Exception:
        return None


def _compute_drift_and_metrics(baseline_runs: list, current_runs: list) -> dict | None:
    """Compute drift score and all dimension metrics between two run sets."""
    try:
        from driftbase.local.diff import compute_drift

        if len(baseline_runs) < 2 or len(current_runs) < 2:
            return None

        baseline_fp = _fingerprint_from_runs(baseline_runs, "baseline")
        current_fp = _fingerprint_from_runs(current_runs, "current")

        if not baseline_fp or not current_fp:
            return None

        drift_report = compute_drift(
            baseline_fp, current_fp, baseline_runs, current_runs
        )

        # Calculate key metrics
        baseline_latency = baseline_fp.p95_latency_ms
        current_latency = current_fp.p95_latency_ms
        latency_change_pct = (
            (current_latency - baseline_latency) / max(baseline_latency, 1)
        ) * 100

        baseline_errors = baseline_fp.error_rate
        current_errors = current_fp.error_rate
        error_change = current_errors - baseline_errors

        # Return ALL dimensions from drift report
        return {
            "drift_score": drift_report.drift_score,
            "decision_drift": drift_report.decision_drift,
            "latency_drift": drift_report.latency_drift,
            "error_drift": drift_report.error_drift,
            "semantic_drift": drift_report.semantic_drift,
            "verbosity_drift": drift_report.verbosity_drift,
            "loop_depth_drift": drift_report.loop_depth_drift,
            "output_drift": drift_report.output_drift,
            "output_length_drift": drift_report.output_length_drift,
            "tool_sequence_drift": drift_report.tool_sequence_drift,
            "retry_drift": drift_report.retry_drift,
            "latency_ms": current_latency,
            "latency_change_pct": latency_change_pct,
            "error_rate": current_errors,
            "error_change": error_change,
            "escalation_rate": getattr(drift_report, "current_escalation_rate", 0.0),
            "sample_count": len(current_runs),
            "report": drift_report,  # Keep full report for detailed analysis
        }
    except Exception as e:
        return None


@click.command(name="compare")
@click.argument("versions", nargs=-1, required=True)
@click.option(
    "--matrix",
    is_flag=True,
    help="Show comparison matrix (tournament mode).",
)
@click.option(
    "--limit",
    "-n",
    type=int,
    default=1000,
    help="Max runs per version (default 1000).",
)
@click.pass_context
def cmd_compare(
    ctx: click.Context,
    versions: tuple[str, ...],
    matrix: bool,
    limit: int,
) -> None:
    """
    Compare multiple versions at once (batch comparison).

    \b
    Examples:
      driftbase compare v1.0 v1.5 v2.0           # Compare 3 versions
      driftbase compare v1.0 v1.5 v2.0 --matrix  # Show drift matrix
      driftbase compare $(driftbase versions --names)  # Compare all versions
    """
    Console, Table = _safe_import_rich()
    console = ctx.obj.get("console") if Console else None

    if not console:
        console = type("PlainConsole", (), {"print": lambda self, x: print(x)})()

    if len(versions) < 2:
        console.print("#FF6B6B]Error:[/] Need at least 2 versions to compare")
        ctx.exit(1)

    try:
        backend = get_backend()
    except Exception as e:
        console.print(f"#FF6B6B]Error:[/] {e}")
        ctx.exit(1)

    # Load runs for all versions
    console.print(f"\n[dim]Loading runs for {len(versions)} versions...[/]\n")
    version_runs = {}

    for ver in versions:
        runs = backend.get_runs(deployment_version=ver, limit=limit)
        version_runs[ver] = runs
        if not runs:
            console.print(f"[#FFA94D]⚠[/] No runs found for {ver}")
        else:
            console.print(f"  ✓ {ver}: {len(runs)} runs")

    # Filter to versions with data
    version_runs = {v: r for v, r in version_runs.items() if r}

    if len(version_runs) < 2:
        console.print("\n#FF6B6B]Error:[/] Not enough versions with data")
        ctx.exit(1)

    if matrix:
        console.print("\n[bold #8B5CF6]Version Comparison Matrix[/]\n")

        versions_list = list(version_runs.keys())

        # Compute all pairwise comparisons and fingerprints
        comparisons = {}
        fingerprints = {}

        for ver in versions_list:
            fingerprints[ver] = _fingerprint_from_runs(version_runs[ver], ver)

        for baseline_ver in versions_list:
            for current_ver in versions_list:
                if baseline_ver != current_ver:
                    metrics = _compute_drift_and_metrics(
                        version_runs[baseline_ver],
                        version_runs[current_ver],
                    )
                    comparisons[(baseline_ver, current_ver)] = metrics

        if Table:
            # === COMPACT VERSION SUMMARY ===
            console.print("[bold]Version Summary[/]\n")

            summary_table = Table(
                show_header=True, header_style="bold #8B5CF6", border_style="dim"
            )
            summary_table.add_column("Version", width=10)
            summary_table.add_column("Runs", justify="right", width=6)
            summary_table.add_column("P95 Latency", justify="right", width=12)
            summary_table.add_column("Error Rate", justify="right", width=11)
            summary_table.add_column("Rank", justify="center", width=6)

            # Score versions (lower is better)
            scores = {}
            for ver in versions_list:
                fp = fingerprints[ver]
                if fp:
                    latency_score = fp.p95_latency_ms
                    error_score = fp.error_rate * 10000
                    cost_score = fp.avg_output_length
                    scores[ver] = latency_score + error_score + cost_score

            sorted_versions = (
                sorted(scores.keys(), key=lambda v: scores[v])
                if scores
                else versions_list
            )

            for rank, ver in enumerate(sorted_versions, 1):
                fp = fingerprints.get(ver)
                if not fp:
                    continue

                latency_color = (
                    "#4ADE80"
                    if fp.p95_latency_ms < 1000
                    else "#FFA94D"
                    if fp.p95_latency_ms < 2000
                    else "#FF6B6B"
                )
                error_color = (
                    "#4ADE80"
                    if fp.error_rate < 0.05
                    else "#FFA94D"
                    if fp.error_rate < 0.10
                    else "#FF6B6B"
                )

                rank_display = (
                    f"[#4ADE80]{rank}[/]"
                    if rank == 1
                    else f"[#FF6B6B]{rank}[/]"
                    if rank == len(sorted_versions)
                    else f"[dim]{rank}[/]"
                )

                summary_table.add_row(
                    ver,
                    str(len(version_runs[ver])),
                    f"[{latency_color}]{fp.p95_latency_ms:.0f}ms[/]",
                    f"[{error_color}]{fp.error_rate:.1%}[/]",
                    rank_display,
                )

            console.print(summary_table)
            console.print()

            # === DIMENSION BREAKDOWN (show top comparison only) ===
            if len(versions_list) == 2:
                # For 2 versions, show full dimension breakdown
                v1, v2 = versions_list
                metrics = comparisons.get((v1, v2))

                if metrics:
                    console.print(f"[bold]Dimension Breakdown: {v1} → {v2}[/]\n")

                    dim_table = Table(
                        show_header=True,
                        header_style="bold #8B5CF6",
                        border_style="dim",
                    )
                    dim_table.add_column("Dimension", width=20)
                    dim_table.add_column("Score", justify="center", width=10)
                    dim_table.add_column("Weight", justify="center", width=8)
                    dim_table.add_column("Impact", justify="right", width=12)

                    # All 11 dimensions with their weights from diff.py
                    dimensions = [
                        ("Decision Logic", "decision_drift", 0.40),
                        ("Latency Profile", "latency_drift", 0.12),
                        ("Error Rates", "error_drift", 0.12),
                        ("Semantic Outcomes", "semantic_drift", 0.08),
                        ("Verbosity", "verbosity_drift", 0.06),
                        ("Loop Depth", "loop_depth_drift", 0.06),
                        ("Output Structure", "output_drift", 0.04),
                        ("Output Length", "output_length_drift", 0.04),
                        ("Tool Sequencing", "tool_sequence_drift", 0.04),
                        ("Retry Behavior", "retry_drift", 0.04),
                    ]

                    # Sort by weighted impact
                    dim_scores = []
                    for name, key, weight in dimensions:
                        score = metrics.get(key, 0.0)
                        impact = score * weight
                        dim_scores.append((name, score, weight, impact))

                    dim_scores.sort(key=lambda x: x[3], reverse=True)

                    for name, score, weight, impact in dim_scores:
                        if score < 0.10:
                            score_color = "#4ADE80"
                        elif score < 0.25:
                            score_color = "#FFA94D"
                        else:
                            score_color = "#FF6B6B"

                        dim_table.add_row(
                            name,
                            f"[{score_color}]{score:.3f}[/]",
                            f"[dim]{weight:.2f}[/]",
                            f"{impact:.3f}",
                        )

                    console.print(dim_table)
                    console.print()
                    console.print(
                        f"[bold]Overall Drift:[/] [{score_color}]{metrics['drift_score']:.3f}[/] (weighted sum)\n"
                    )

            elif len(versions_list) > 2:
                # For 3+ versions, show compact pairwise drift matrix
                console.print(
                    "[bold]Pairwise Drift Matrix[/] [dim](row = baseline, col = current)[/]\n"
                )

                drift_table = Table(
                    show_header=True, header_style="bold #8B5CF6", border_style="dim"
                )
                drift_table.add_column("Baseline ↓", width=10)

                for ver in versions_list:
                    drift_table.add_column(ver, justify="center", width=10)

                for baseline_ver in versions_list:
                    row = [baseline_ver]
                    for current_ver in versions_list:
                        if baseline_ver == current_ver:
                            row.append("[dim]—[/]")
                        else:
                            metrics = comparisons.get((baseline_ver, current_ver))
                            if metrics:
                                drift = metrics["drift_score"]
                                if drift < 0.10:
                                    row.append(f"[#4ADE80]{drift:.2f}[/]")
                                elif drift < 0.20:
                                    row.append(f"[#FFA94D]{drift:.2f}[/]")
                                else:
                                    row.append(f"[#FF6B6B]{drift:.2f}[/]")
                            else:
                                row.append("[dim]N/A[/]")

                    drift_table.add_row(*row)

                console.print(drift_table)
                console.print()
                console.print(
                    "[dim]Note: Drift is directional - measures how current differs from baseline patterns[/]\n"
                )

            # === RECOMMENDATION ===
            if scores:
                best_ver = sorted_versions[0]
                worst_ver = sorted_versions[-1]

                console.print(
                    f"[bold]Recommendation:[/] Deploy [#4ADE80]{best_ver}[/]\n"
                )

                if len(sorted_versions) > 1:
                    best_fp = fingerprints[best_ver]
                    worst_fp = fingerprints[worst_ver]

                    metrics = comparisons.get((best_ver, worst_ver))
                    if metrics and worst_ver != best_ver:
                        latency_diff = (
                            (worst_fp.p95_latency_ms - best_fp.p95_latency_ms)
                            / best_fp.p95_latency_ms
                        ) * 100
                        error_diff = (
                            (worst_fp.error_rate - best_fp.error_rate)
                            / max(best_fp.error_rate, 0.001)
                        ) * 100

                        issues = []
                        if latency_diff > 50:
                            issues.append(f"{latency_diff:.0f}% slower")
                        if error_diff > 100:
                            issues.append(f"{error_diff:.0f}% more errors")

                        if issues:
                            console.print(f"  Avoid {worst_ver}: {', '.join(issues)}")
                            console.print()

            console.print(
                "[dim]Run 'driftbase diff <v1> <v2>' for detailed dimension analysis[/]\n"
            )
    else:
        # Sequential comparison (v1→v2, v2→v3, etc.) with rich metrics
        console.print("\n[bold #8B5CF6]Sequential Version Comparison[/]\n")

        versions_list = list(version_runs.keys())

        if Table:
            table = Table(
                show_header=True, header_style="bold #8B5CF6", border_style="dim"
            )
            table.add_column("From", style="", width=10)
            table.add_column("→", style="dim", width=3)
            table.add_column("To", style="", width=10)
            table.add_column("Drift", justify="center", width=10)
            table.add_column("Latency Δ", justify="right", width=12)
            table.add_column("Error Δ", justify="right", width=10)
            table.add_column("Verdict", justify="center", width=12)
            table.add_column("Key Change", style="dim", width=30)

            for i in range(len(versions_list) - 1):
                baseline_ver = versions_list[i]
                current_ver = versions_list[i + 1]

                metrics = _compute_drift_and_metrics(
                    version_runs[baseline_ver],
                    version_runs[current_ver],
                )

                if metrics:
                    drift = metrics["drift_score"]
                    latency_change = metrics["latency_change_pct"]
                    error_change = metrics["error_change"]

                    # Determine verdict
                    if drift < 0.10:
                        verdict = "[#4ADE80]✓ Stable[/]"
                        drift_display = f"[#4ADE80]{drift:.2f}[/]"
                    elif drift < 0.20:
                        verdict = "[#FFA94D]△ Moderate[/]"
                        drift_display = f"[#FFA94D]{drift:.2f}[/]"
                    else:
                        verdict = "[#FF6B6B]⚠ High[/]"
                        drift_display = f"[#FF6B6B]{drift:.2f}[/]"

                    # Latency change
                    if abs(latency_change) < 10:
                        latency_display = f"[dim]{latency_change:+.0f}%[/]"
                    elif latency_change > 0:
                        latency_display = f"[#FF8787]{latency_change:+.0f}%[/]"
                    else:
                        latency_display = f"[#4ADE80]{latency_change:+.0f}%[/]"

                    # Error change
                    if abs(error_change) < 0.01:
                        error_display = f"[dim]{error_change:+.1%}[/]"
                    elif error_change > 0:
                        error_display = f"[#FF8787]{error_change:+.1%}[/]"
                    else:
                        error_display = f"[#4ADE80]{error_change:+.1%}[/]"

                    # Key change summary
                    key_changes = []
                    if abs(latency_change) > 20:
                        key_changes.append(
                            "Latency" if latency_change > 0 else "Performance"
                        )
                    if abs(error_change) > 0.05:
                        key_changes.append(
                            "Reliability" if error_change > 0 else "Stability"
                        )
                    if drift >= 0.50:
                        key_changes.append("Major behavior shift")

                    key_change_text = (
                        ", ".join(key_changes) if key_changes else "Minimal changes"
                    )

                    table.add_row(
                        baseline_ver,
                        "→",
                        current_ver,
                        drift_display,
                        latency_display,
                        error_display,
                        verdict,
                        key_change_text,
                    )
                else:
                    table.add_row(
                        baseline_ver,
                        "→",
                        current_ver,
                        "[dim]N/A[/]",
                        "[dim]—[/]",
                        "[dim]—[/]",
                        "[dim]—[/]",
                        "[dim]Insufficient data[/]",
                    )

            console.print(table)
        else:
            # Plain text fallback
            for i in range(len(versions_list) - 1):
                baseline_ver = versions_list[i]
                current_ver = versions_list[i + 1]

                metrics = _compute_drift_and_metrics(
                    version_runs[baseline_ver],
                    version_runs[current_ver],
                )

                if metrics:
                    drift = metrics["drift_score"]
                    if drift < 0.10:
                        verdict = "✓ Stable"
                    elif drift < 0.20:
                        verdict = "△ Moderate"
                    else:
                        verdict = "⚠ High"
                    print(f"{baseline_ver} → {current_ver}: {drift:.2f} ({verdict})")
                else:
                    print(f"{baseline_ver} → {current_ver}: N/A")

        console.print()
        console.print(
            "[dim]Tip: Use --matrix flag to see all pairwise comparisons[/]\n"
        )

    ctx.exit(0)
