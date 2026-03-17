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


def _compute_drift_score(baseline_runs: list, current_runs: list) -> float | None:
    """Compute drift score between two run sets."""
    try:
        from driftbase.local.diff import compute_drift
        from driftbase.local.fingerprinter import build_fingerprint_from_runs
        from driftbase.local.local_store import run_dict_to_agent_run

        if len(baseline_runs) < 10 or len(current_runs) < 10:
            return None

        baseline_fp = build_fingerprint_from_runs(
            [run_dict_to_agent_run(r) for r in baseline_runs]
        )
        current_fp = build_fingerprint_from_runs(
            [run_dict_to_agent_run(r) for r in current_runs]
        )

        drift_report = compute_drift(baseline_fp, current_fp)
        return drift_report.drift_score
    except Exception:
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
        console.print("[red]Error:[/] Need at least 2 versions to compare")
        ctx.exit(1)

    try:
        backend = get_backend()
    except Exception as e:
        console.print(f"[red]Error:[/] {e}")
        ctx.exit(1)

    # Load runs for all versions
    console.print(f"\n[dim]Loading runs for {len(versions)} versions...[/]\n")
    version_runs = {}

    for ver in versions:
        runs = backend.get_runs(deployment_version=ver, limit=limit)
        version_runs[ver] = runs
        if not runs:
            console.print(f"[yellow]⚠[/] No runs found for {ver}")
        else:
            console.print(f"  ✓ {ver}: {len(runs)} runs")

    # Filter to versions with data
    version_runs = {v: r for v, r in version_runs.items() if r}

    if len(version_runs) < 2:
        console.print("\n[red]Error:[/] Not enough versions with data")
        ctx.exit(1)

    if matrix:
        # Tournament mode: compute all pairwise comparisons
        console.print("\n[bold cyan]📊 Version Comparison Matrix[/]\n")

        if Table:
            # Create matrix table
            table = Table(show_header=True, header_style="bold")
            table.add_column("", style="cyan")

            versions_list = list(version_runs.keys())
            for ver in versions_list:
                table.add_column(ver, justify="center", style="dim")

            for baseline_ver in versions_list:
                row = [baseline_ver]
                for current_ver in versions_list:
                    if baseline_ver == current_ver:
                        row.append("—")
                    else:
                        drift = _compute_drift_score(
                            version_runs[baseline_ver],
                            version_runs[current_ver],
                        )
                        if drift is not None:
                            # Color code by severity
                            if drift < 0.10:
                                row.append(f"[green]{drift:.3f}[/]")
                            elif drift < 0.20:
                                row.append(f"[yellow]{drift:.3f}[/]")
                            else:
                                row.append(f"[red]{drift:.3f}[/]")
                        else:
                            row.append("[dim]N/A[/]")

                table.add_row(*row)

            console.print(table)
        else:
            # Plain text matrix
            versions_list = list(version_runs.keys())
            print(f"{'':10s} | " + " | ".join(f"{v:8s}" for v in versions_list))
            print("-" * (12 + len(versions_list) * 11))

            for baseline_ver in versions_list:
                row = [f"{baseline_ver:10s}"]
                for current_ver in versions_list:
                    if baseline_ver == current_ver:
                        row.append("   —    ")
                    else:
                        drift = _compute_drift_score(
                            version_runs[baseline_ver],
                            version_runs[current_ver],
                        )
                        if drift is not None:
                            row.append(f" {drift:6.3f} ")
                        else:
                            row.append("  N/A   ")
                print(" | ".join(row))

        console.print("\n[dim]Reading: drift from row version to column version[/]\n")

    else:
        # Sequential comparison (v1→v2, v2→v3, etc.)
        console.print("\n[bold cyan]📊 Sequential Comparison[/]\n")

        if Table:
            table = Table(show_header=True, header_style="bold")
            table.add_column("Baseline", style="cyan")
            table.add_column("→", style="dim")
            table.add_column("Current", style="cyan")
            table.add_column("Drift Score", justify="right")
            table.add_column("Verdict", justify="center")

            versions_list = list(version_runs.keys())
            for i in range(len(versions_list) - 1):
                baseline_ver = versions_list[i]
                current_ver = versions_list[i + 1]

                drift = _compute_drift_score(
                    version_runs[baseline_ver],
                    version_runs[current_ver],
                )

                if drift is not None:
                    # Determine verdict
                    if drift < 0.10:
                        verdict = "[green]✓ Low[/]"
                        drift_display = f"[green]{drift:.3f}[/]"
                    elif drift < 0.20:
                        verdict = "[yellow]⚠ Medium[/]"
                        drift_display = f"[yellow]{drift:.3f}[/]"
                    else:
                        verdict = "[red]✗ High[/]"
                        drift_display = f"[red]{drift:.3f}[/]"

                    table.add_row(
                        baseline_ver, "→", current_ver, drift_display, verdict
                    )
                else:
                    table.add_row(
                        baseline_ver, "→", current_ver, "[dim]N/A[/]", "[dim]—[/]"
                    )

            console.print(table)
        else:
            # Plain text
            versions_list = list(version_runs.keys())
            for i in range(len(versions_list) - 1):
                baseline_ver = versions_list[i]
                current_ver = versions_list[i + 1]

                drift = _compute_drift_score(
                    version_runs[baseline_ver],
                    version_runs[current_ver],
                )

                if drift is not None:
                    if drift < 0.10:
                        verdict = "✓ Low"
                    elif drift < 0.20:
                        verdict = "⚠ Medium"
                    else:
                        verdict = "✗ High"
                    print(f"{baseline_ver} → {current_ver}: {drift:.3f} ({verdict})")
                else:
                    print(f"{baseline_ver} → {current_ver}: N/A")

        console.print()

    ctx.exit(0)
