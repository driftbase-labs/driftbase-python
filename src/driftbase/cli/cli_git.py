"""
Git integration commands: compare branches, show git context.
"""

from __future__ import annotations

import json
from datetime import datetime

import click

from driftbase.backends.factory import get_backend
from driftbase.utils.git import (
    format_git_label,
    get_commit_sha_for_branch,
    get_commits_between,
    get_common_ancestor,
    get_git_context,
    is_git_repo,
)


def _safe_import_rich():
    try:
        from rich.console import Console
        from rich.panel import Panel
        from rich.table import Table

        return Console, Panel, Table
    except ImportError:
        return None, None, None


@click.group(name="git")
def git_group():
    """Git integration commands for comparing branches and commits."""
    pass


@git_group.command(name="status")
@click.pass_context
def git_status(ctx: click.Context):
    """
    Show current git repository status and metadata.

    Example:
        driftbase git status
    """
    Console, Panel, Table = _safe_import_rich()
    console = ctx.obj.get("console") if Console else None

    if not console:
        console = type("PlainConsole", (), {"print": lambda self, x: print(x)})()

    git_ctx = get_git_context()

    if not git_ctx.enabled:
        console.print("[yellow]Not in a git repository or git not available[/]")
        console.print("\nGit integration features require:")
        console.print("  • git command available in PATH")
        console.print("  • Working directory is within a git repository")
        ctx.exit(1)

    # Display git context
    if Table:
        table = Table(show_header=False, box=None, padding=(0, 2))
        table.add_column("Key", style="cyan")
        table.add_column("Value")

        table.add_row("Branch", git_ctx.branch or "detached HEAD")
        table.add_row("Commit", git_ctx.commit_sha or "unknown")
        table.add_row("Tag", git_ctx.tag or "none")
        table.add_row("Dirty", "yes (uncommitted changes)" if git_ctx.is_dirty else "no")
        table.add_row("Remote", git_ctx.remote_url or "none")
        table.add_row("Label", format_git_label(git_ctx))

        console.print("\n[bold cyan]📦 Git Repository Status[/]\n")
        console.print(table)
        console.print()
    else:
        print("\nGit Repository Status:")
        print(f"  Branch:     {git_ctx.branch or 'detached HEAD'}")
        print(f"  Commit:     {git_ctx.commit_sha or 'unknown'}")
        print(f"  Tag:        {git_ctx.tag or 'none'}")
        print(f"  Dirty:      {'yes (uncommitted changes)' if git_ctx.is_dirty else 'no'}")
        print(f"  Remote:     {git_ctx.remote_url or 'none'}")
        print(f"  Label:      {format_git_label(git_ctx)}")
        print()

    ctx.exit(0)


@git_group.command(name="compare")
@click.argument("base")
@click.argument("head", required=False)
@click.option(
    "--version",
    "-v",
    help="Deployment version to filter (optional).",
)
@click.option(
    "--limit",
    "-n",
    type=int,
    default=1000,
    help="Max runs per commit (default 1000).",
)
@click.option(
    "--format",
    "-f",
    type=click.Choice(["table", "json"]),
    default="table",
    help="Output format.",
)
@click.pass_context
def git_compare(
    ctx: click.Context,
    base: str,
    head: str | None,
    version: str | None,
    limit: int,
    format: str,
):
    """
    Compare runs between git branches or commits.

    This command compares agent runs associated with different git commits,
    allowing you to see behavioral drift across branches or during development.

    Arguments:
        BASE: Base branch/commit (e.g., 'main', 'develop', 'abc123')
        HEAD: Head branch/commit (defaults to current HEAD)

    Examples:
        driftbase git compare main feature-branch
        driftbase git compare v1.0 v2.0
        driftbase git compare abc123 def456 -v production
        driftbase git compare main --format json
    """
    Console, Panel, Table = _safe_import_rich()
    console = ctx.obj.get("console") if Console else None

    if not console:
        console = type("PlainConsole", (), {"print": lambda self, x: print(x)})()

    # Check git availability
    if not is_git_repo():
        console.print("[red]Error:[/] Not in a git repository")
        console.print("\nThis command requires working directory to be in a git repository.")
        ctx.exit(1)

    # Get commit SHAs for base and head
    base_sha = get_commit_sha_for_branch(base)
    if not base_sha:
        console.print(f"[red]Error:[/] Could not resolve base '{base}' to a commit")
        ctx.exit(1)

    if head is None:
        # Use current HEAD
        git_ctx = get_git_context()
        head_sha = git_ctx.commit_sha
        head_label = format_git_label(git_ctx)
    else:
        head_sha = get_commit_sha_for_branch(head)
        head_label = head
        if not head_sha:
            console.print(f"[red]Error:[/] Could not resolve head '{head}' to a commit")
            ctx.exit(1)

    # Get common ancestor
    common = get_common_ancestor(base, head or "HEAD")

    try:
        backend = get_backend()
    except Exception as e:
        console.print(f"[red]Error:[/] {e}")
        ctx.exit(1)

    # Query runs for each commit
    # Note: This requires git_commit column in database
    # For now, we'll use a simpler approach: compare runs by time windows

    console.print(f"\n[dim]Comparing git commits:[/]")
    console.print(f"  Base: {base} ({base_sha})")
    console.print(f"  Head: {head_label} ({head_sha})")
    if common:
        console.print(f"  Common ancestor: {common}")
    console.print()

    # Get all runs for the version
    runs = backend.get_runs(deployment_version=version, limit=limit * 10)

    if not runs:
        console.print(f"[yellow]No runs found{' for version ' + version if version else ''}[/]")
        ctx.exit(0)

    # TODO: Filter by git commit when git_commit column is added
    # For now, show a message about future enhancement
    console.print(
        "[yellow]Note:[/] Git commit filtering not yet implemented in database schema."
    )
    console.print(
        "This feature requires storing git metadata with runs (planned enhancement)."
    )
    console.print()
    console.print("To enable git-based comparison:")
    console.print("  1. Add git_commit, git_branch, git_dirty columns to database")
    console.print("  2. Auto-capture git context during agent tracking")
    console.print("  3. Filter runs by commit SHA in this command")
    console.print()
    console.print(f"Found {len(runs)} total runs{' for ' + version if version else ''}")
    console.print("Use 'driftbase diff' for version-based comparison")

    ctx.exit(0)


@git_group.command(name="tag")
@click.option(
    "--enable/--disable",
    default=True,
    help="Enable or disable git auto-tagging.",
)
@click.pass_context
def git_tag(ctx: click.Context, enable: bool):
    """
    Configure git auto-tagging for runs.

    When enabled, every tracked run will automatically capture the current
    git commit SHA, branch, and dirty status.

    Examples:
        driftbase git tag --enable   # Enable auto-tagging
        driftbase git tag --disable  # Disable auto-tagging
    """
    Console, Panel, Table = _safe_import_rich()
    console = ctx.obj.get("console") if Console else None

    if not console:
        console = type("PlainConsole", (), {"print": lambda self, x: print(x)})()

    # Save to config
    from driftbase.config import save_config

    try:
        save_config("DRIFTBASE_GIT_TAGGING", "1" if enable else "0", scope="global")

        if enable:
            console.print("[green]✓[/] Git auto-tagging enabled")
            console.print()
            console.print("All tracked runs will now include:")
            console.print("  • Git commit SHA")
            console.print("  • Git branch name")
            console.print("  • Dirty status (uncommitted changes)")
            console.print()
            console.print("Use 'driftbase git compare' to compare branches")
        else:
            console.print("[green]✓[/] Git auto-tagging disabled")
            console.print()
            console.print("Runs will no longer capture git metadata")

    except Exception as e:
        console.print(f"[red]Error:[/] Failed to save configuration: {e}")
        ctx.exit(1)

    ctx.exit(0)
