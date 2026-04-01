"""
CLI commands for budget management.
"""

from __future__ import annotations

import sys
from pathlib import Path

import click

from driftbase.backends.factory import get_backend
from driftbase.cli._deps import safe_import_rich

Console, Panel, Table = safe_import_rich()


@click.group(name="budgets")
@click.pass_context
def cmd_budgets(ctx: click.Context) -> None:
    """
    Define acceptance criteria for CI gating.

    Budget commands for viewing breaches, setting limits, and clearing history.
    """
    pass


@cmd_budgets.command(name="show")
@click.argument("agent_id", required=False)
@click.argument("version", required=False)
@click.pass_context
def cmd_budgets_show(
    ctx: click.Context, agent_id: str | None, version: str | None
) -> None:
    """
    Show budget breaches.

    \b
    Examples:
      # Show all breaches
      driftbase budgets show

      # Show breaches for specific agent
      driftbase budgets show my_agent_id

      # Show breaches for specific version
      driftbase budgets show my_agent_id v1.0
    """
    console: Console = ctx.obj["console"]
    backend = get_backend()

    breaches = backend.get_budget_breaches(agent_id=agent_id, version=version)

    if not breaches:
        if agent_id and version:
            console.print(f"[dim]No budget breaches found for {agent_id}/{version}[/]")
        elif agent_id:
            console.print(f"[dim]No budget breaches found for {agent_id}[/]")
        else:
            console.print("[dim]No budget breaches found[/]")
        ctx.exit(0)

    # Create table
    try:
        table = Table(
            title="Budget Breaches",
            show_header=True,
            header_style="bold #8B5CF6",
            border_style="dim",
        )
        table.add_column("Agent", style="")
        table.add_column("Version", style="")
        table.add_column("Dimension", style="")
        table.add_column("Limit", justify="right")
        table.add_column("Actual", justify="right")
        table.add_column("Direction", justify="center")
        table.add_column("Window", justify="center")
        table.add_column("Breached At", style="dim")

        for breach in breaches:
            # Format values based on dimension
            budget_key = breach["budget_key"]
            limit_value = breach["limit"]
            actual_value = breach["actual"]

            if "latency" in budget_key:
                limit_str = f"{limit_value:.1f}s"
                actual_str = f"{actual_value / 1000:.1f}s"
            elif "rate" in budget_key or "ratio" in budget_key:
                limit_str = f"{limit_value * 100:.1f}%"
                actual_str = f"{actual_value * 100:.1f}%"
            else:
                limit_str = f"{limit_value:.1f}"
                actual_str = f"{actual_value:.1f}"

            direction_color = "#FF6B6B" if breach["direction"] == "above" else "#FFA94D"
            direction_display = f"[{direction_color}]{breach['direction'].upper()}[/]"

            breached_at = breach["breached_at"]
            if hasattr(breached_at, "strftime"):
                breached_at_str = breached_at.strftime("%Y-%m-%d %H:%M:%S")
            else:
                breached_at_str = str(breached_at)

            table.add_row(
                breach["agent_id"][:20],  # Truncate long agent IDs
                breach["version"],
                breach["dimension"].replace("_", " "),
                limit_str,
                actual_str,
                direction_display,
                f"n={breach['run_count']}",
                breached_at_str,
            )

        console.print(table)

        # Exit with code 1 if any breaches exist (for CI)
        ctx.exit(1)

    except Exception as e:
        console.print(f"[bold red]Error:[/] {str(e)}")
        ctx.exit(1)


@cmd_budgets.command(name="set")
@click.argument("agent_id")
@click.argument("version")
@click.option(
    "--config",
    "-c",
    type=click.Path(exists=True),
    required=True,
    help="Path to budget YAML file",
)
@click.pass_context
def cmd_budgets_set(
    ctx: click.Context, agent_id: str, version: str, config: str
) -> None:
    """
    Set budget configuration from YAML file.

    \b
    Examples:
      driftbase budgets set my_agent v1.0 --config budget.yaml

    YAML format:
      max_p95_latency: 4.0
      max_error_rate: 0.05
      max_escalation_rate: 0.20
    """
    console: Console = ctx.obj["console"]
    backend = get_backend()

    try:
        import yaml

        from driftbase.local.budget import parse_budget

        config_path = Path(config)
        with config_path.open("r") as f:
            budget_dict = yaml.safe_load(f) or {}

        # Validate budget keys
        budget_config = parse_budget(budget_dict)

        # Write to backend
        backend.write_budget_config(
            agent_id=agent_id,
            version=version,
            config=budget_config.limits,
            source="config_file",
        )

        console.print(f"[green]✓[/] Budget configuration set for {agent_id}/{version}")
        console.print(f"[dim]  {len(budget_config.limits)} limits configured[/]")

    except ImportError:
        console.print(
            "[bold red]Error:[/] PyYAML is required for this command. Install with: pip install pyyaml"
        )
        ctx.exit(1)
    except ValueError as e:
        console.print(f"[bold red]Invalid budget configuration:[/] {str(e)}")
        ctx.exit(1)
    except Exception as e:
        console.print(f"[bold red]Error:[/] {str(e)}")
        ctx.exit(1)


@cmd_budgets.command(name="clear")
@click.argument("agent_id", required=False)
@click.argument("version", required=False)
@click.option("--all", "-a", is_flag=True, help="Clear all breach records")
@click.pass_context
def cmd_budgets_clear(
    ctx: click.Context, agent_id: str | None, version: str | None, all: bool
) -> None:
    """
    Clear budget breach records.

    Does not delete budget configurations, only breach history.

    \b
    Examples:
      # Clear breaches for specific version
      driftbase budgets clear my_agent v1.0

      # Clear all breaches for an agent
      driftbase budgets clear my_agent

      # Clear all breaches
      driftbase budgets clear --all
    """
    console: Console = ctx.obj["console"]
    backend = get_backend()

    try:
        if not all and not agent_id:
            console.print(
                "[bold yellow]Warning:[/] Specify --all to clear all breaches, or provide agent_id"
            )
            ctx.exit(1)

        deleted_count = backend.delete_budget_breaches(
            agent_id=agent_id, version=version
        )

        if deleted_count > 0:
            console.print(f"[green]✓[/] Cleared {deleted_count} breach record(s)")
        else:
            console.print("[dim]No breach records found to clear[/]")

    except Exception as e:
        console.print(f"[bold red]Error:[/] {str(e)}")
        ctx.exit(1)
