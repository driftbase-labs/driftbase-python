"""
Tail command: Stream recent runs with minimal output.
"""

from __future__ import annotations

import time
from datetime import datetime

import click

from driftbase.backends.factory import get_backend


def _safe_import_rich():
    try:
        from rich.console import Console
        from rich.table import Table

        return Console, Table
    except ImportError:
        return None, None


def _format_outcome(outcome: str) -> tuple[str, str]:
    """Return (symbol, style) for outcome."""
    outcome_map = {
        "resolved": ("✓", "green"),
        "escalated": ("⚠", "yellow"),
        "fallback": ("→", "blue"),
        "error": ("✗", "red"),
    }
    return outcome_map.get(outcome, ("·", "dim"))


def _format_latency(latency_ms: int) -> str:
    """Format latency in human-readable form."""
    if latency_ms < 1000:
        return f"{latency_ms}ms"
    else:
        return f"{latency_ms / 1000:.1f}s"


@click.command(name="tail")
@click.option(
    "--lines",
    "-n",
    type=int,
    default=20,
    help="Number of runs to show (default 20).",
)
@click.option(
    "--follow", "-f", is_flag=True, help="Follow mode: continuously show new runs."
)
@click.option("--version", "-v", help="Filter by deployment version.")
@click.option("--environment", "-e", help="Filter by environment.")
@click.option(
    "--interval",
    "-i",
    type=int,
    default=2,
    help="Poll interval in seconds for follow mode (default 2).",
)
@click.pass_context
def cmd_tail(
    ctx: click.Context,
    lines: int,
    follow: bool,
    version: str | None,
    environment: str | None,
    interval: int,
):
    """
    Stream the last N runs with minimal output.

    Examples:
        driftbase tail -n 50          # Show last 50 runs
        driftbase tail -f              # Follow new runs (like tail -f)
        driftbase tail -f -v v2.0      # Follow only v2.0 runs
    """
    Console, Table = _safe_import_rich()
    console = ctx.obj.get("console") if Console else None

    backend = get_backend()

    if not follow:
        # One-shot mode: show last N runs
        try:
            runs = backend.get_runs(
                deployment_version=version, environment=environment, limit=lines
            )
        except Exception as e:
            if console:
                console.print(f"[red]Error:[/] {e}")
            else:
                print(f"Error: {e}")
            ctx.exit(1)

        if not runs:
            if console:
                console.print("[yellow]No runs found[/]")
            else:
                print("No runs found")
            ctx.exit(0)

        # Display in compact format
        if Table:
            table = Table(show_header=True, header_style="bold")
            table.add_column("TIME", style="dim")
            table.add_column("VER", style="cyan")
            table.add_column("OUTCOME")
            table.add_column("LAT", justify="right")

            for run in reversed(runs):  # Oldest first for readability
                started = run.get("started_at")
                if hasattr(started, "strftime"):
                    time_str = started.strftime("%H:%M:%S")
                else:
                    time_str = str(started)[:8] if started else "—"

                ver = run.get("deployment_version", "unknown")[:8]
                outcome = run.get("semantic_cluster", "unknown")
                latency = run.get("latency_ms", 0)

                symbol, style = _format_outcome(outcome)
                outcome_display = f"[{style}]{symbol} {outcome}[/]"
                latency_display = _format_latency(latency)

                table.add_row(time_str, ver, outcome_display, latency_display)

            console.print(table)
        else:
            # Plain text fallback
            print(f"{'TIME':<10} {'VER':<10} {'OUTCOME':<15} {'LAT':>10}")
            print("-" * 45)
            for run in reversed(runs):
                started = run.get("started_at")
                if hasattr(started, "strftime"):
                    time_str = started.strftime("%H:%M:%S")
                else:
                    time_str = str(started)[:8] if started else "—"

                ver = run.get("deployment_version", "unknown")[:8]
                outcome = run.get("semantic_cluster", "unknown")
                latency = run.get("latency_ms", 0)

                symbol, _ = _format_outcome(outcome)
                latency_display = _format_latency(latency)

                print(
                    f"{time_str:<10} {ver:<10} {symbol} {outcome:<13} {latency_display:>10}"
                )

    else:
        # Follow mode: continuously poll for new runs
        if console:
            console.print(
                f"[dim]Following new runs (poll interval: {interval}s, Ctrl+C to stop)...[/]\n"
            )
        else:
            print(
                f"Following new runs (poll interval: {interval}s, Ctrl+C to stop)...\n"
            )

        last_seen_id = None

        try:
            while True:
                # Get recent runs
                runs = backend.get_runs(
                    deployment_version=version, environment=environment, limit=100
                )

                # Find new runs (runs we haven't seen yet)
                new_runs = []
                for run in reversed(runs):  # Process oldest first
                    run_id = run.get("id")
                    if last_seen_id is None:
                        # First iteration - show all recent runs
                        new_runs.append(run)
                    elif run_id == last_seen_id:
                        # Found the last seen run - stop here
                        break
                    else:
                        new_runs.append(run)

                # Update last_seen_id to the most recent run
                if runs:
                    last_seen_id = runs[0].get("id")

                # Display new runs
                for run in new_runs:
                    started = run.get("started_at")
                    if hasattr(started, "strftime"):
                        time_str = started.strftime("%H:%M:%S")
                    else:
                        time_str = str(started)[:8] if started else "—"

                    ver = run.get("deployment_version", "unknown")[:8]
                    outcome = run.get("semantic_cluster", "unknown")
                    latency = run.get("latency_ms", 0)
                    latency_display = _format_latency(latency)

                    symbol, style = _format_outcome(outcome)

                    if console:
                        console.print(
                            f"[dim]{time_str}[/] [cyan]{ver}[/] [{style}]{symbol} {outcome}[/] {latency_display}"
                        )
                    else:
                        print(f"{time_str} {ver} {symbol} {outcome} {latency_display}")

                # Wait before next poll
                time.sleep(interval)

        except KeyboardInterrupt:
            if console:
                console.print("\n[dim]Stopped following[/]")
            else:
                print("\nStopped following")
            ctx.exit(0)
