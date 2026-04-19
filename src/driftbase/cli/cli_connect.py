"""CLI commands for Langfuse connector sync."""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta

import click

from driftbase.backends.factory import get_backend
from driftbase.cli._deps import safe_import_rich
from driftbase.config import get_settings

Console, Panel, Table = safe_import_rich()


def _run_auto_detect(ctx: click.Context) -> None:
    """Auto-detect and connect to Langfuse."""
    console: Console = ctx.obj["console"]

    langfuse_public = os.environ.get("LANGFUSE_PUBLIC_KEY")
    langfuse_secret = os.environ.get("LANGFUSE_SECRET_KEY")

    console.print()
    console.print("[bold]DRIFTBASE CONNECT[/]")
    console.print()
    console.print("  Scanning your environment...")
    console.print()

    # Check Langfuse
    if langfuse_public and langfuse_secret:
        console.print("  ─────────────────────────────────────────────────────────────")
        console.print("  [bold]LANGFUSE DETECTED[/]")
        console.print("  ─────────────────────────────────────────────────────────────")
        console.print()
        _connect_langfuse_auto(console, ctx)
    else:
        _show_fallback(console)


def _connect_langfuse_auto(console: Console, ctx: click.Context) -> None:
    """Auto-connect to LangFuse."""
    try:
        from driftbase.connectors.langfuse import LANGFUSE_AVAILABLE, LangFuseConnector

        if not LANGFUSE_AVAILABLE:
            console.print("  [#FFA94D]✗ LangFuse package not installed[/]")
            console.print("    Run: [#8B5CF6]pip install driftbase[/]")
            return

        console.print("  [#4ADE80]✓[/] LangFuse credentials detected")
        console.print("    Connecting...")
        console.print()

        connector = LangFuseConnector()
        projects = connector.list_projects()

        if not projects:
            console.print("    [#FFA94D]Unable to fetch project info.[/]")
            return

        project = projects[0]
        console.print(
            f"    Project: [bold]{project['name']}[/]  (approx. {project['run_count']} traces)"
        )
        console.print()

        # Ask for confirmation if interactive
        is_interactive = sys.stdin.isatty()
        if is_interactive:
            try:
                confirm = input("    Import traces? [Y/n]: ").strip().lower()
                if confirm and confirm not in ["y", "yes"]:
                    console.print("    [#FFA94D]Cancelled.[/]")
                    return
            except KeyboardInterrupt:
                console.print("\n    [#FFA94D]Cancelled.[/]")
                return

        console.print("    Importing traces from LangFuse...")

        # Run the actual import
        from driftbase.connectors.base import ConnectorConfig

        since_dt = datetime.utcnow() - timedelta(days=90)
        config = ConnectorConfig(
            project_name=project["name"],
            since=since_dt,
            limit=5000,
            agent_id=None,
        )

        db_path = get_settings().DRIFTBASE_DB_PATH
        result = connector.sync(config, db_path, dry_run=False)

        if result.success:
            console.print(
                f"    ████████████████████  {result.runs_written}/{result.traces_fetched}  done"
            )
            console.print()
            console.print(f"    [#4ADE80]✓[/] {result.runs_written} runs imported")
            console.print(
                "    [dim]⚠ decision outcomes inferred from output content (heuristic)[/]"
            )
            console.print()
            console.print(
                "    Even if you use LangGraph, CrewAI, or any other framework —"
            )
            console.print(
                "    your LangFuse traces contain behavioral data Driftbase can use."
            )
        else:
            console.print("    [#FF6B6B]✗ Import failed[/]")
            for error in result.errors[:3]:
                console.print(f"    [dim]{error}[/]")

    except Exception as e:
        console.print(f"    [#FF6B6B]Error: {e}[/]")


def _show_fallback(console: Console) -> None:
    """Show fallback instructions when no credentials are found."""
    console.print("  ─────────────────────────────────────────────────────────────")
    console.print("  [bold]LANGFUSE NOT DETECTED[/]")
    console.print("  ─────────────────────────────────────────────────────────────")
    console.print()
    console.print("  Driftbase analyzes drift from your existing Langfuse traces.")
    console.print()
    console.print("  To get started:")
    console.print()
    console.print("  1. Set up Langfuse credentials:")
    console.print("     export LANGFUSE_PUBLIC_KEY=your-public-key")
    console.print("     export LANGFUSE_SECRET_KEY=your-secret-key")
    console.print("     export LANGFUSE_HOST=https://cloud.langfuse.com  # optional")
    console.print()
    console.print("  2. Run driftbase connect again:")
    console.print("     driftbase connect")
    console.print()
    console.print("  3. Analyze drift:")
    console.print("     driftbase history")
    console.print("     driftbase diagnose")
    console.print()
    console.print("  Need test data? Generate synthetic traces:")
    console.print("    driftbase testset generate --use-case <agent-type>")
    console.print("    driftbase testset list  # see all agent types")
    console.print()


@click.group("connect", invoke_without_command=True)
@click.pass_context
def cmd_connect(ctx: click.Context) -> None:
    """Auto-detect and connect to Langfuse."""
    # If a subcommand was invoked, don't run auto-detection
    if ctx.invoked_subcommand is not None:
        return

    # Run auto-detection when called without subcommand
    _run_auto_detect(ctx)


@cmd_connect.command("langfuse")
@click.option("--project", required=True, help="LangFuse project name")
@click.option(
    "--host",
    default="https://cloud.langfuse.com",
    help="LangFuse host (default: https://cloud.langfuse.com)",
)
@click.option(
    "--since", help="Fetch traces since this date (YYYY-MM-DD, default: 30 days ago)"
)
@click.option(
    "--limit", type=int, default=500, help="Max traces to fetch (default: 500)"
)
@click.option("--agent-id", help="Override agent ID in Driftbase")
@click.option(
    "--dry-run", is_flag=True, help="Show what would be imported without writing"
)
@click.pass_context
def connect_langfuse(
    ctx: click.Context,
    project: str,
    host: str,
    since: str | None,
    limit: int,
    agent_id: str | None,
    dry_run: bool,
) -> None:
    """Import traces from LangFuse."""
    console: Console = ctx.obj["console"]

    # Check if langfuse is available
    try:
        from driftbase.connectors.langfuse import LANGFUSE_AVAILABLE

        if not LANGFUSE_AVAILABLE:
            console.print(
                "[#FF6B6B]langfuse extra not installed.[/]\n\n"
                "Install it with: [#8B5CF6]pip install driftbase[/]"
            )
            ctx.exit(1)
    except ImportError:
        console.print(
            "[#FF6B6B]langfuse extra not installed.[/]\n\n"
            "Install it with: [#8B5CF6]pip install driftbase[/]"
        )
        ctx.exit(1)

    # Check API keys
    if not os.getenv("LANGFUSE_PUBLIC_KEY") or not os.getenv("LANGFUSE_SECRET_KEY"):
        console.print(
            "[#FF6B6B]LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY environment variables not set.[/]\n\n"
            "Set them with:\n"
            "  [dim]export LANGFUSE_PUBLIC_KEY=your-public-key[/]\n"
            "  [dim]export LANGFUSE_SECRET_KEY=your-secret-key[/]"
        )
        ctx.exit(1)

    # Parse since date
    since_dt = None
    if since:
        try:
            since_dt = datetime.fromisoformat(since)
        except ValueError:
            console.print(
                f"[#FF6B6B]Invalid date format: {since}[/]\nUse YYYY-MM-DD format."
            )
            ctx.exit(1)
    else:
        since_dt = datetime.utcnow() - timedelta(days=30)

    console.print()
    console.print("[bold]DRIFTBASE CONNECT[/]  LangFuse")
    console.print("─" * 70)
    console.print()
    console.print(f"  Project         {project}")
    console.print(f"  Host            {host}")
    console.print(f"  Fetching traces since {since_dt.date().isoformat()}...")
    if dry_run:
        console.print("  [#FFA94D]DRY RUN - no data will be written[/]")
    console.print()

    # Create connector
    try:
        from driftbase.connectors.base import ConnectorConfig
        from driftbase.connectors.langfuse import LangFuseConnector

        connector = LangFuseConnector()

        # Validate credentials
        if not connector.validate_credentials():
            console.print("[#FF6B6B]Invalid LangFuse API keys.[/]")
            ctx.exit(1)

        # Create config
        config = ConnectorConfig(
            project_name=project,
            since=since_dt,
            limit=limit,
            agent_id=agent_id,
        )

        # Sync
        db_path = get_settings().DRIFTBASE_DB_PATH
        result = connector.sync(config, db_path, dry_run=dry_run)

        # Display results
        if result.success:
            console.print(
                f"  [#4ADE80]✓[/] Found {result.traces_fetched} traces in LangFuse"
            )
            if result.skipped > 0:
                console.print(f"  Already imported: {result.skipped}")
            console.print(f"  To import: {result.runs_written}")
            console.print()

            if not dry_run and result.runs_written > 0:
                console.print(
                    f'  [#4ADE80]✓[/] Imported {result.runs_written} runs as agent "{agent_id or project}"'
                )

                # Save sync metadata
                backend = get_backend()
                backend.write_connector_sync(
                    source="langfuse",
                    project_name=project,
                    agent_id=agent_id or project,
                    runs_imported=result.runs_written,
                )

                console.print()
                console.print("  [dim]Approximations applied:[/]")
                console.print(
                    "  [dim]⚠  decision outcomes inferred from output content (heuristic)[/]"
                )
                console.print()
                console.print("  [bold]Next steps:[/]")
                console.print("  Run: [#8B5CF6]driftbase history[/]")
                console.print("  Run: [#8B5CF6]driftbase diagnose[/]")
            elif dry_run:
                console.print(
                    f"  Would import {result.runs_written} runs (dry run mode)"
                )

            if result.errors:
                console.print()
                console.print("  [#FFA94D]Warnings:[/]")
                for error in result.errors[:5]:  # Show first 5 errors
                    console.print(f"  [dim]• {error}[/]")
        else:
            console.print("[#FF6B6B]Sync failed:[/]")
            for error in result.errors:
                console.print(f"  • {error}")
            ctx.exit(1)

    except Exception as e:
        console.print(f"[#FF6B6B]Error: {e}[/]")
        ctx.exit(1)


@cmd_connect.command("status")
@click.pass_context
def connect_status(ctx: click.Context) -> None:
    """Show connection status and last sync info."""
    console: Console = ctx.obj["console"]

    console.print()
    console.print("[bold]DRIFTBASE CONNECT STATUS[/]")
    console.print("─" * 70)
    console.print()

    backend = get_backend()

    # Check Langfuse
    langfuse_configured = bool(
        os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY")
    )
    console.print("[bold]Langfuse[/]")
    if langfuse_configured:
        console.print("  Status          [#4ADE80]✓ Connected[/]")
    else:
        console.print("  Status          [#FF6B6B]✗ Not configured[/]")
        console.print(
            "  [dim]Set LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY to connect.[/]"
        )

    console.print()
