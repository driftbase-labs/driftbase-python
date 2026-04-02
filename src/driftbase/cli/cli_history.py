"""History command for showing longitudinal behavioral timeline."""

import json
import os
from datetime import datetime
from typing import Any

import click

from driftbase.backends.factory import get_backend
from driftbase.cli._deps import safe_import_rich_extended
from driftbase.config import get_settings

Console, Panel, Table, _, _, _ = safe_import_rich_extended()


def _render_progress_bar(
    run_count: int, target: int = 40, use_color: bool = True
) -> str:
    """Render a progress bar showing runs collected vs target."""
    percentage = min(100, int(run_count / target * 100))
    filled = int(percentage / 5)
    empty = 20 - filled

    if use_color:
        filled_char = "█"
        empty_char = "░"
    else:
        filled_char = "#"
        empty_char = "-"

    bar = filled_char * filled + empty_char * empty
    return f"{bar}  {run_count} / {target} runs recorded  ({percentage}%)"


@click.command("history")
@click.option(
    "--days",
    "-d",
    type=int,
    default=30,
    help="Number of days to show (default: 30)",
)
@click.option(
    "--format",
    "-f",
    type=click.Choice(["text", "json"]),
    default="text",
    help="Output format",
)
@click.pass_context
def cmd_history(ctx: click.Context, days: int, format: str) -> None:
    """
    Full behavioral timeline of your agent.

    Displays how agent behavior evolved over time with automatically detected epochs,
    stability analysis, and key changes at each transition.

    \b
    Examples:
      driftbase history
      driftbase history --days 60
      driftbase history --format json
    """
    console: Console = ctx.obj["console"]
    backend = get_backend()

    # Get all runs
    all_runs = backend.get_all_runs()
    if not all_runs:
        console.print("[#FF6B6B]No runs found. Run your agent with @track() first.[/]")
        return

    # Get agent_id from most recent run
    agent_id = all_runs[0].get("session_id") or all_runs[0].get("id")
    total_runs = len(all_runs)

    # Check if enough data
    if total_runs < 40:
        use_color = not console.no_color
        progress_bar = _render_progress_bar(total_runs, 40, use_color)

        # Check for LangSmith/LangFuse credentials
        langsmith_hint = ""
        langfuse_hint = ""
        if os.environ.get("LANGSMITH_API_KEY"):
            langsmith_hint = (
                "    export LANGSMITH_API_KEY=your-key     # Already set ✓\n"
            )
        else:
            langsmith_hint = "    export LANGSMITH_API_KEY=your-key     # LangSmith\n"

        if os.environ.get("LANGFUSE_PUBLIC_KEY") and os.environ.get(
            "LANGFUSE_SECRET_KEY"
        ):
            langfuse_hint = "    export LANGFUSE_PUBLIC_KEY=your-key   # Already set ✓\n    export LANGFUSE_SECRET_KEY=your-secret\n"
        else:
            langfuse_hint = "    export LANGFUSE_PUBLIC_KEY=your-key   # LangFuse\n    export LANGFUSE_SECRET_KEY=your-secret\n"

        console.print(f"\n[bold]DRIFTBASE HISTORY[/]  {agent_id}\n")
        console.print("  Building behavioral baseline...\n")
        console.print(f"  {progress_bar}\n")
        console.print(
            "  Keep running your agent — behavioral timeline appears automatically"
        )
        console.print("  once your baseline is established.\n")
        console.print("  ─────────────────────────────────────────────────────────────")
        console.print("  [bold]SKIP THE WAIT:[/]")
        console.print(
            "  ─────────────────────────────────────────────────────────────\n"
        )
        console.print(f"{langsmith_hint}{langfuse_hint}    driftbase connect\n")
        console.print("  Or generate a baseline from scratch:\n")
        console.print(
            "    driftbase testset generate --use-case <type> --output baseline.py"
        )
        console.print("    python baseline.py\n")
        console.print("  Available agent types:")
        console.print(
            "    customer_support · financial · healthcare · legal · code_generation"
        )
        console.print(
            "    data_analysis · devops_sre · automation · content_generation · general\n"
        )
        console.print("    Run: [bold]driftbase testset list[/]  (see all 14 types)\n")
        return

    # Detect epochs
    from driftbase.local.epoch_detector import detect_epochs

    db_path = get_settings().DRIFTBASE_DB_PATH
    epochs = detect_epochs(agent_id, db_path, window_size=20, sensitivity=0.15)

    if not epochs:
        console.print("[#FF6B6B]Failed to detect epochs. Check error logs.[/]")
        return

    # JSON output
    if format == "json":
        output = {
            "agent_id": agent_id,
            "total_runs": total_runs,
            "total_epochs": len(epochs),
            "epochs": [
                {
                    "label": e.label,
                    "run_count": e.run_count,
                    "stability": e.stability,
                    "start_time": e.start_time.isoformat() if e.start_time else None,
                    "end_time": e.end_time.isoformat() if e.end_time else None,
                    "summary": e.summary,
                }
                for e in epochs
            ],
        }
        console.print(json.dumps(output, indent=2))
        return

    # Text output
    console.print()
    console.print("[bold]DRIFTBASE HISTORY[/]  ·  Behavioral Timeline")
    console.print("─" * 70)
    console.print()

    # Create timeline table
    timeline_table = Table(show_header=True, header_style="bold", box=None)
    timeline_table.add_column("Epoch", style="cyan", no_wrap=True)
    timeline_table.add_column("Runs", justify="right")
    timeline_table.add_column("Stability", justify="center")
    timeline_table.add_column("Key changes")

    for _i, epoch in enumerate(epochs):
        # Format stability with indicator
        if epoch.stability == "HIGH":
            stability_str = "HIGH"
            stability_color = "green"
        elif epoch.stability == "MODERATE":
            stability_str = "MODERATE"
            stability_color = "yellow"
        elif epoch.stability == "LOW":
            stability_str = "LOW"
            stability_color = "red"
        else:
            stability_str = "UNKNOWN"
            stability_color = "dim"

        # Format time range
        if epoch.start_time and epoch.end_time:
            time_range = f"{epoch.start_time.strftime('%b %d')} – {epoch.end_time.strftime('%b %d')}"
        else:
            time_range = "Unknown dates"

        epoch_label = f"{epoch.label}\n[dim]{time_range}[/]"

        # Key changes (placeholder - would query change_events table in full implementation)
        changes_desc = epoch.summary

        timeline_table.add_row(
            epoch_label,
            str(epoch.run_count),
            f"[{stability_color}]{stability_str}[/]",
            changes_desc,
        )

    console.print(timeline_table)

    # Trend summary
    console.print()
    console.print("─" * 70)
    console.print("[bold]TREND[/]")
    console.print("─" * 70)
    console.print()

    # Count behavioral shifts
    behavioral_shifts = len(epochs) - 1

    # Determine current state based on latest epoch
    latest_epoch = epochs[-1]
    if latest_epoch.stability in ["HIGH", "MODERATE"]:
        current_state = "STABLE"
        current_color = "green"
    elif latest_epoch.stability == "LOW":
        current_state = "DEGRADED"
        current_color = "red"
    else:
        current_state = "INSUFFICIENT_DATA"
        current_color = "yellow"

    # Find longest stable period
    max_stable_runs = 0
    longest_epoch_label = ""
    for epoch in epochs:
        if epoch.stability == "HIGH" and epoch.run_count > max_stable_runs:
            max_stable_runs = epoch.run_count
            longest_epoch_label = epoch.label

    console.print(f"  Total runs recorded:    {total_runs}")
    console.print(f"  Behavioral shifts:      {behavioral_shifts}")
    console.print(f"  Current state:          [{current_color}]{current_state}[/]")
    if longest_epoch_label:
        console.print(
            f"  Longest stable period:  {longest_epoch_label} ({max_stable_runs} runs)"
        )

    console.print()
