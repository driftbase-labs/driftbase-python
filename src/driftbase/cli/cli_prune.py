"""
Prune command: Explicit retention management for agent runs.
"""

from __future__ import annotations

import re

import click

from driftbase.backends.factory import get_backend


def _parse_duration(duration_str: str) -> int | None:
    """
    Parse duration string like '30d', '7d', '24h' into days.

    Returns None if parsing fails.
    """
    match = re.match(r"^(\d+)([dh])$", duration_str.lower())
    if not match:
        return None

    value, unit = match.groups()
    value = int(value)

    if unit == "d":
        return value
    elif unit == "h":
        # Convert hours to days (fractional)
        return max(1, value // 24)  # At least 1 day

    return None


@click.command(name="prune")
@click.option("--version", "-v", help="Prune specific version only.")
@click.option("--environment", "-e", help="Prune specific environment only.")
@click.option("--keep-last", type=int, metavar="N", help="Keep only the last N runs.")
@click.option(
    "--older-than",
    metavar="DURATION",
    help="Delete runs older than duration (e.g., 30d, 7d).",
)
@click.option(
    "--dry-run", is_flag=True, help="Show what would be deleted without deleting."
)
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt.")
@click.pass_context
def cmd_prune(
    ctx: click.Context,
    version: str | None,
    environment: str | None,
    keep_last: int | None,
    older_than: str | None,
    dry_run: bool,
    yes: bool,
):
    """
    Delete runs by retention criteria.

    You must specify at least one deletion criteria: --keep-last or --older-than.

    Examples:
        driftbase prune --keep-last 5000           # Keep only 5000 newest runs
        driftbase prune --older-than 30d           # Delete runs older than 30 days
        driftbase prune --version v1.0 --older-than 7d  # Delete old v1.0 runs
        driftbase prune --dry-run --keep-last 1000 # Preview deletion
    """
    console = ctx.obj.get("console")

    # Validate: at least one criteria
    if keep_last is None and older_than is None:
        console.print(
            "#FF6B6B]Error:[/] Must specify at least one criteria: --keep-last or --older-than"
        )
        ctx.exit(1)

    # Parse older_than duration
    older_than_days = None
    if older_than:
        older_than_days = _parse_duration(older_than)
        if older_than_days is None:
            console.print(f"#FF6B6B]Error:[/] Invalid duration format: {older_than}")
            console.print("  Expected format: 30d (days) or 24h (hours)")
            ctx.exit(1)

    # Get backend
    try:
        backend = get_backend()
    except Exception as e:
        console.print(f"#FF6B6B]Error:[/] Failed to connect to database: {e}")
        ctx.exit(1)

    # Determine what will be deleted
    try:
        if keep_last is not None:
            # Count total matching runs
            total_count = backend.count_runs_filtered(
                deployment_version=version, environment=environment
            )
            to_delete = max(0, total_count - keep_last)

            if dry_run or not yes:
                filter_desc = ""
                if version:
                    filter_desc += f" version={version}"
                if environment:
                    filter_desc += f" environment={environment}"

                console.print(
                    f"#FFA94D]Would delete {to_delete:,} runs[/]{filter_desc}"
                )
                console.print(f"  Total runs: {total_count:,}")
                console.print(f"  Keep last: {keep_last:,}")
                console.print(f"  To delete: {to_delete:,}")

        elif older_than_days is not None:
            # Estimate count (we don't have a direct count method for time-based)
            # Just show the criteria
            filter_desc = f" older than {older_than}"
            if version:
                filter_desc += f" for version={version}"
            if environment:
                filter_desc += f" environment={environment}"

            console.print(f"#FFA94D]Will delete runs{filter_desc}[/]")

    except Exception as e:
        console.print(f"#FF6B6B]Error:[/] Failed to query runs: {e}")
        ctx.exit(1)

    # Dry-run: stop here
    if dry_run:
        console.print("\n[dim]Dry-run mode: no changes made[/]")
        ctx.exit(0)

    # Confirmation prompt (if not --yes)
    if not yes:
        console.print(
            "\n#FFA94D]This will permanently delete runs from the database.[/]"
        )
        confirm = click.confirm("Do you want to continue?", default=False)
        if not confirm:
            console.print("[dim]Cancelled[/]")
            ctx.exit(0)

    # Perform deletion
    try:
        deleted_count = backend.delete_runs_filtered(
            deployment_version=version,
            environment=environment,
            older_than_days=older_than_days,
            keep_last_n=keep_last,
        )

        console.print(f"#4ADE80]✓[/] Deleted {deleted_count:,} runs")

    except Exception as e:
        console.print(f"#FF6B6B]Error:[/] Failed to delete runs: {e}")
        ctx.exit(1)

    ctx.exit(0)
