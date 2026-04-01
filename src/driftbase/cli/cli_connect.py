"""CLI commands for connector sync (LangSmith, LangFuse)."""

from __future__ import annotations

import os
from datetime import datetime, timedelta

import click

from driftbase.backends.factory import get_backend
from driftbase.cli._deps import safe_import_rich
from driftbase.config import get_settings

Console, Panel, Table = safe_import_rich()


@click.group("connect")
@click.pass_context
def cmd_connect(ctx: click.Context) -> None:
    """Import traces from LangSmith or LangFuse."""
    pass


@cmd_connect.command("langsmith")
@click.option("--project", required=True, help="LangSmith project name")
@click.option(
    "--since",
    help="Fetch runs since this date (YYYY-MM-DD, default: 30 days ago)",
)
@click.option("--limit", type=int, default=500, help="Max runs to fetch (default: 500)")
@click.option(
    "--agent-id", help="Override agent ID in Driftbase (default: project name)"
)
@click.option(
    "--dry-run", is_flag=True, help="Show what would be imported without writing"
)
@click.pass_context
def connect_langsmith(
    ctx: click.Context,
    project: str,
    since: str | None,
    limit: int,
    agent_id: str | None,
    dry_run: bool,
) -> None:
    """Import traces from LangSmith."""
    console: Console = ctx.obj["console"]

    # Check if langsmith is available
    try:
        from driftbase.connectors.langsmith import LANGSMITH_AVAILABLE

        if not LANGSMITH_AVAILABLE:
            console.print(
                "[#FF6B6B]langsmith extra not installed.[/]\n\n"
                "Install it with: [#8B5CF6]pip install driftbase[langsmith][/]"
            )
            ctx.exit(1)
    except ImportError:
        console.print(
            "[#FF6B6B]langsmith extra not installed.[/]\n\n"
            "Install it with: [#8B5CF6]pip install driftbase[langsmith][/]"
        )
        ctx.exit(1)

    # Check API key
    if not os.getenv("LANGSMITH_API_KEY"):
        console.print(
            "[#FF6B6B]LANGSMITH_API_KEY environment variable not set.[/]\n\n"
            "Set it with: [dim]export LANGSMITH_API_KEY=your-key[/]"
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
    console.print("[bold]DRIFTBASE CONNECT[/]  LangSmith")
    console.print("─" * 70)
    console.print()
    console.print(f"  Project         {project}")
    console.print(f"  Fetching runs since {since_dt.date().isoformat()}...")
    if dry_run:
        console.print("  [#FFA94D]DRY RUN - no data will be written[/]")
    console.print()

    # Create connector
    try:
        from driftbase.connectors.base import ConnectorConfig
        from driftbase.connectors.langsmith import LangSmithConnector

        connector = LangSmithConnector()

        # Validate credentials
        if not connector.validate_credentials():
            console.print("[#FF6B6B]Invalid LangSmith API key.[/]")
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
                f"  [#4ADE80]✓[/] Found {result.traces_fetched} traces in LangSmith"
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
                    source="langsmith",
                    project_name=project,
                    agent_id=agent_id or project,
                    runs_imported=result.runs_written,
                )

                console.print()
                console.print("  [dim]Approximations applied:[/]")
                console.print(
                    "  [dim]⚠  decision outcomes inferred from output content (heuristic)[/]"
                )
                console.print(
                    "  [dim]⚠  loop_count estimated from child run patterns[/]"
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
                "Install it with: [#8B5CF6]pip install driftbase[langfuse][/]"
            )
            ctx.exit(1)
    except ImportError:
        console.print(
            "[#FF6B6B]langfuse extra not installed.[/]\n\n"
            "Install it with: [#8B5CF6]pip install driftbase[langfuse][/]"
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

    # Check LangSmith
    langsmith_configured = bool(os.getenv("LANGSMITH_API_KEY"))
    console.print("[bold]LangSmith[/]")
    if langsmith_configured:
        console.print("  Status          [#4ADE80]✓ Connected[/]")

        # Get sync info (we need to query all syncs since we don't know project name)
        # For now, just show if configured
    else:
        console.print("  Status          [#FF6B6B]✗ Not configured[/]")
        console.print("  [dim]Set LANGSMITH_API_KEY to connect.[/]")

    console.print()

    # Check LangFuse
    langfuse_configured = bool(
        os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY")
    )
    console.print("[bold]LangFuse[/]")
    if langfuse_configured:
        console.print("  Status          [#4ADE80]✓ Connected[/]")
    else:
        console.print("  Status          [#FF6B6B]✗ Not configured[/]")
        console.print(
            "  [dim]Set LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY to connect.[/]"
        )

    console.print()
