"""
CLI commands for change event management (root cause analysis).
"""

from __future__ import annotations

import sys
from pathlib import Path

import click

from driftbase.backends.factory import get_backend
from driftbase.cli._deps import safe_import_rich

Console, Panel, Table = safe_import_rich()


@click.group(name="changes")
@click.pass_context
def cmd_changes(ctx: click.Context) -> None:
    """
    Manage change events for root cause analysis.

    Record infrastructure and code changes to correlate with drift.
    """
    pass


@cmd_changes.command(name="record")
@click.argument("agent_id")
@click.argument("version")
@click.option("--model-version", help="LLM model identifier (e.g., gpt-4o-2024-11)")
@click.option("--prompt-hash", help="SHA256 hash of system prompt")
@click.option("--rag-snapshot", help="RAG document snapshot identifier")
@click.option("--tool-version", multiple=True, help="Tool version (can be repeated)")
@click.option("--custom", multiple=True, help="Custom change (format: key=value)")
@click.option(
    "--config", "-c", type=click.Path(exists=True), help="YAML file with changes"
)
@click.pass_context
def cmd_changes_record(
    ctx: click.Context,
    agent_id: str,
    version: str,
    model_version: str | None,
    prompt_hash: str | None,
    rag_snapshot: str | None,
    tool_version: tuple[str, ...],
    custom: tuple[str, ...],
    config: str | None,
) -> None:
    """
    Record change events for a version.

    \b
    Examples:
      # Record model version change
      driftbase changes record my_agent v2.0 --model-version gpt-4o-2024-11

      # Record multiple changes
      driftbase changes record my_agent v2.0 \\
        --model-version gpt-4o-2024-11 \\
        --prompt-hash sha256:abc123 \\
        --rag-snapshot snapshot-2024-03-21

      # Record from YAML file
      driftbase changes record my_agent v2.0 --config changes.yaml

    YAML format:
      model_version: gpt-4o-2024-11
      prompt_hash: sha256:abc123
      rag_snapshot: snapshot-2024-03-21
      custom_deployed_by: ci-pipeline-447
    """
    console: Console = ctx.obj["console"]
    backend = get_backend()

    changes = {}

    # Load from config file if provided
    if config:
        try:
            import yaml

            config_path = Path(config)
            with config_path.open("r") as f:
                file_changes = yaml.safe_load(f) or {}
            changes.update(file_changes)
        except ImportError:
            console.print(
                "[bold red]Error:[/] PyYAML is required for config files. "
                "Install with: pip install pyyaml"
            )
            ctx.exit(1)
        except Exception as e:
            console.print(f"[bold red]Error reading config file:[/] {str(e)}")
            ctx.exit(1)

    # Add CLI options (override config file)
    if model_version:
        changes["model_version"] = model_version
    if prompt_hash:
        changes["prompt_hash"] = prompt_hash
    if rag_snapshot:
        changes["rag_snapshot"] = rag_snapshot
    if tool_version:
        # Store as comma-separated string if multiple
        changes["tool_version"] = ", ".join(tool_version)
    for custom_change in custom:
        if "=" not in custom_change:
            console.print(
                f"[bold red]Error:[/] Custom changes must be in format key=value, got: {custom_change}"
            )
            ctx.exit(1)
        key, value = custom_change.split("=", 1)
        if not key.startswith("custom_"):
            key = f"custom_{key}"
        changes[key] = value

    if not changes:
        console.print(
            "[bold yellow]No changes specified.[/] Use --model-version, --prompt-hash, "
            "--rag-snapshot, --tool-version, or --custom"
        )
        ctx.exit(1)

    # Write each change as a separate event
    written_count = 0
    for change_type, current_value in changes.items():
        try:
            backend.write_change_event(
                {
                    "agent_id": agent_id,
                    "version": version,
                    "change_type": change_type,
                    "previous": None,
                    "current": str(current_value),
                    "source": "cli",
                }
            )
            written_count += 1
        except Exception as e:
            console.print(
                f"[yellow]Warning:[/] Failed to write {change_type}: {str(e)}"
            )

    if written_count > 0:
        console.print(
            f"[green]✓[/] Recorded {written_count} change(s) for {agent_id}/{version}"
        )
    else:
        console.print("[bold red]Error:[/] No changes were recorded")
        ctx.exit(1)


@cmd_changes.command(name="list")
@click.argument("agent_id")
@click.argument("version", required=False)
@click.pass_context
def cmd_changes_list(ctx: click.Context, agent_id: str, version: str | None) -> None:
    """
    List recorded change events.

    \b
    Examples:
      # List all changes for an agent
      driftbase changes list my_agent

      # List changes for a specific version
      driftbase changes list my_agent v2.0
    """
    console: Console = ctx.obj["console"]
    backend = get_backend()

    try:
        if version:
            # List changes for specific version
            events = backend.get_change_events(agent_id, version)
            title = f"Change Events: {agent_id}/{version}"
        else:
            # List all changes for agent across all versions
            # Get all versions first
            versions = backend.get_versions()
            events = []
            for ver, _ in versions:
                ver_events = backend.get_change_events(agent_id, ver)
                events.extend(ver_events)
            title = f"Change Events: {agent_id}"

        if not events:
            if version:
                console.print(
                    f"[dim]No change events found for {agent_id}/{version}[/]"
                )
            else:
                console.print(f"[dim]No change events found for {agent_id}[/]")
            return

        # Create table
        table = Table(
            title=title,
            show_header=True,
            header_style="bold #8B5CF6",
            border_style="dim",
        )
        table.add_column("Version", style="")
        table.add_column("Change Type", style="")
        table.add_column("Previous", style="dim")
        table.add_column("Current", style="")
        table.add_column("Source", style="dim", justify="center")
        table.add_column("Recorded At", style="dim")

        for event in events:
            previous = event.get("previous") or "—"
            if len(previous) > 30:
                previous = previous[:27] + "..."

            current = event.get("current", "")
            if len(current) > 40:
                current = current[:37] + "..."

            recorded_at = event.get("recorded_at")
            if hasattr(recorded_at, "strftime"):
                recorded_at_str = recorded_at.strftime("%Y-%m-%d %H:%M")
            else:
                recorded_at_str = str(recorded_at)

            table.add_row(
                event.get("version", ""),
                event.get("change_type", "").replace("_", " "),
                previous,
                current,
                event.get("source", ""),
                recorded_at_str,
            )

        console.print(table)

    except Exception as e:
        console.print(f"[bold red]Error:[/] {str(e)}")
        ctx.exit(1)
