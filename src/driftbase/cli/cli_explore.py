"""
Explore command: Interactive terminal UI for browsing runs.
"""

from __future__ import annotations

import sys

import click

from driftbase.backends.factory import get_backend


def _safe_import_rich():
    try:
        from rich.console import Console
        from rich.layout import Layout
        from rich.live import Live
        from rich.panel import Panel
        from rich.table import Table

        return Console, Layout, Live, Panel, Table
    except ImportError:
        return None, None, None, None, None


@click.command(name="explore")
@click.option(
    "--version",
    "-v",
    help="Start with specific version selected.",
)
@click.pass_context
def cmd_explore(ctx: click.Context, version: str | None):
    """
    Interactive terminal UI for exploring runs.

    \b
    Navigation:
      ↑/↓    : Navigate runs
      Enter  : View run details
      v      : Switch version
      q      : Quit

    \b
    Example:
      driftbase explore
      driftbase explore -v v2.0
    """
    Console, Layout, Live, Panel, Table = _safe_import_rich()

    if not Console or not Live:
        print("Error: Rich library required for explore command")
        print("Install with: pip install 'driftbase[tui]'")
        ctx.exit(1)

    console = Console()

    try:
        backend = get_backend()
        versions = backend.get_versions()
    except Exception as e:
        console.print(f"[red]Error:[/] {e}")
        ctx.exit(1)

    if not versions:
        console.print("[yellow]No versions found in database[/]")
        console.print("\nTry:")
        console.print("  [cyan]driftbase demo[/] to generate sample data")
        ctx.exit(0)

    # Select initial version
    if version:
        current_version = version
    else:
        current_version = versions[0][0]

    selected_run_idx = 0
    view_mode = "list"  # "list" or "detail"
    selected_run = None

    def load_runs(ver: str) -> list:
        try:
            return backend.get_runs(deployment_version=ver, limit=100)
        except Exception:
            return []

    runs = load_runs(current_version)

    def render_screen():
        """Render the current screen state."""
        if view_mode == "list":
            # Versions panel
            versions_panel = Panel(
                "\n".join(
                    [
                        f"{'→ ' if v == current_version else '  '}{v} ({count} runs)"
                        for v, count in versions[:10]
                    ]
                ),
                title="[bold cyan]Versions[/]",
                border_style="cyan",
            )

            # Runs table
            if runs:
                table = Table(show_header=True, header_style="bold")
                table.add_column("", width=2)
                table.add_column("RUN_ID", style="dim")
                table.add_column("OUTCOME")
                table.add_column("LATENCY", justify="right")
                table.add_column("TOOLS", max_width=30)

                for i, run in enumerate(runs[:20]):
                    marker = "→" if i == selected_run_idx else ""
                    run_id = str(run.get("id", ""))[:8]
                    outcome = run.get("semantic_cluster", "unknown")
                    latency = f"{run.get('latency_ms', 0)}ms"
                    tools = str(run.get("tool_sequence", "[]"))[:30]

                    style = "bold" if i == selected_run_idx else ""
                    table.add_row(marker, run_id, outcome, latency, tools, style=style)

                runs_panel = Panel(
                    table,
                    title=f"[bold cyan]Runs ({current_version})[/]",
                    border_style="cyan",
                )
            else:
                runs_panel = Panel(
                    "[dim]No runs found[/]",
                    title=f"[bold cyan]Runs ({current_version})[/]",
                    border_style="cyan",
                )

            # Help panel
            help_panel = Panel(
                "[dim]↑/↓: Navigate | Enter: View details | v: Switch version | q: Quit[/]",
                border_style="dim",
            )

            # Create layout
            layout = Layout()
            layout.split_column(
                Layout(name="main", ratio=10),
                Layout(help_panel, size=3),
            )
            layout["main"].split_row(
                Layout(versions_panel, ratio=1),
                Layout(runs_panel, ratio=3),
            )

            return layout

        else:  # detail view
            if selected_run:
                run_id = selected_run.get("id", "")
                version = selected_run.get("deployment_version", "")
                outcome = selected_run.get("semantic_cluster", "unknown")
                latency = selected_run.get("latency_ms", 0)
                errors = selected_run.get("error_count", 0)
                tools = selected_run.get("tool_sequence", "[]")

                details = f"""[bold cyan]Run Details[/]

[bold]ID:[/]        {run_id}
[bold]Version:[/]   {version}
[bold]Outcome:[/]   {outcome}
[bold]Latency:[/]   {latency}ms
[bold]Errors:[/]    {errors}
[bold]Tools:[/]     {tools}
"""
                detail_panel = Panel(
                    details,
                    title="[bold cyan]Run Details[/]",
                    border_style="cyan",
                )

                help_panel = Panel(
                    "[dim]Esc/q: Back to list[/]",
                    border_style="dim",
                )

                layout = Layout()
                layout.split_column(
                    Layout(detail_panel, ratio=10),
                    Layout(help_panel, size=3),
                )

                return layout
            else:
                return Panel("[red]No run selected[/]")

    # Simple interactive loop (without full TUI framework)
    console.print("\n[bold cyan]🔍 Driftbase Explorer[/]\n")
    console.print("[dim]Interactive mode not fully implemented yet.[/]")
    console.print("[dim]Showing static view of current data...[/]\n")

    # For now, just show a static view
    with Live(render_screen(), console=console, refresh_per_second=4) as live:
        import time

        time.sleep(0.5)  # Show for a moment

    # Show instructions for full interactive mode
    console.print("\n[dim]📝 Note:[/] Full interactive navigation coming soon!")
    console.print("[dim]For now, use these commands to explore:[/]\n")
    console.print("  [cyan]driftbase runs -v <version>[/]     # List runs")
    console.print("  [cyan]driftbase inspect <run_id>[/]      # View details")
    console.print("  [cyan]driftbase chart -v <version>[/]    # Visualize metrics")
    console.print()

    ctx.exit(0)
