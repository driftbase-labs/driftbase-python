"""
CLI for driftbase: versions, diff, watch, inspect, report.
Uses click for parsing and rich for output.
"""

from __future__ import annotations

import os
import sys

import click
from rich.console import Console
from rich.table import Table

from driftbase.backends.factory import get_backend


def _console_no_color(no_color_flag: bool) -> bool:
    """True if output should be uncolored: --no-color wins, else use DRIFTBASE_OUTPUT_COLOR."""
    if no_color_flag:
        return True
    try:
        from driftbase.config import get_settings
        return not get_settings().DRIFTBASE_OUTPUT_COLOR
    except Exception:
        return False


@click.group()
@click.option("--no-color", is_flag=True, help="Disable colored output (overrides DRIFTBASE_OUTPUT_COLOR).")
@click.pass_context
def cli(ctx: click.Context, no_color: bool) -> None:
    """Behavioral watchdog for AI agents — versions, diff, watch, inspect, report."""
    ctx.ensure_object(dict)
    ctx.obj["console"] = Console(no_color=_console_no_color(no_color))


from driftbase.cli.cli_diff import cmd_diff
from driftbase.cli.cli_inspect import cmd_inspect
from driftbase.cli.cli_report import cmd_report

cli.add_command(cmd_diff)
cli.add_command(cmd_inspect)
cli.add_command(cmd_report)


@cli.command("versions")
@click.pass_context
def cmd_versions(ctx: click.Context) -> None:
    """List deployment versions with run counts from the local backend."""
    console: Console = ctx.obj["console"]
    backend_name = (os.getenv("DRIFTBASE_BACKEND") or "sqlite").strip().lower()
    if backend_name == "sqlite":
        db_path = os.path.expanduser(os.getenv("DRIFTBASE_DB_PATH", "~/.driftbase/runs.db"))
        if not os.path.isfile(db_path):
            console.print(f"No local DB found at [bold]{db_path}[/]", style="red")
            console.print("Run some @track() decorated agents first.")
            ctx.exit(1)
    try:
        backend = get_backend()
        rows = backend.get_versions()
    except Exception as e:
        console.print(f"Backend error: [red]{e}[/]")
        ctx.exit(1)
    if not rows:
        console.print("No runs recorded yet.")
        return
    table = Table(show_header=True, header_style="bold")
    table.add_column("VERSION")
    table.add_column("RUNS", justify="right")
    for version, count in rows:
        table.add_row(version or "unknown", str(count))
    console.print(table)


@cli.command("watch")
@click.option("--against", "-a", required=True, metavar="VERSION", help="Baseline version to compare against.")
@click.option("--interval", "-i", type=float, default=5.0, help="Poll interval in seconds (default 5).")
@click.option("--min-runs", type=int, default=10, help="Minimum runs before computing (default 10).")
@click.option("--last", "-n", type=int, default=20, help="Number of recent runs for current window (default 20).")
@click.option("--environment", "-e", default=None, help="Filter by environment.")
@click.option("--threshold", "-t", type=float, default=0.20, help="Drift threshold (default 0.20).")
@click.pass_context
def cmd_watch(
    ctx: click.Context,
    against: str,
    interval: float,
    min_runs: int,
    last: int,
    environment: str | None,
    threshold: float,
) -> None:
    """Live drift monitor against a baseline version."""
    from driftbase.cli.cli_diff import run_watch

    console: Console = ctx.obj["console"]
    use_color = not console.no_color
    run_watch(
        against,
        interval_seconds=interval,
        min_runs=min_runs,
        last_n=last,
        environment=environment,
        threshold=threshold,
        use_color=use_color,
        console=console,
    )


def main() -> int:
    """Entry point for the driftbase script."""
    cli(obj={})
    return 0


if __name__ == "__main__":
    sys.exit(main())
