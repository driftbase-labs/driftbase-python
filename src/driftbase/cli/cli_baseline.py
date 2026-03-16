"""
Baseline command: Manage baseline version for drift comparison.
"""

from __future__ import annotations

import click

from driftbase.backends.factory import get_backend
from driftbase.config import (
    delete_config_key,
    get_config_source,
    get_settings,
    save_config,
)


@click.group(name="baseline")
def baseline_group():
    """Manage baseline version for drift comparison."""
    pass


@baseline_group.command(name="set")
@click.argument("version")
@click.option(
    "--global",
    "scope",
    flag_value="global",
    default=True,
    help="Save to global config (~/.driftbase/config).",
)
@click.option(
    "--local",
    "scope",
    flag_value="local",
    help="Save to project config (./.driftbase/config).",
)
@click.pass_context
def baseline_set(ctx: click.Context, version: str, scope: str):
    """
    Set the baseline version for drift comparison.

    Examples:
        driftbase baseline set v2.0
        driftbase baseline set v2.0 --local  # Project-specific baseline
    """
    console = ctx.obj.get("console")

    # Validate version exists in database
    try:
        backend = get_backend()
        versions = backend.get_versions()
        version_names = [ver for ver, _ in versions]

        if version not in version_names:
            console.print(f"[yellow]Warning:[/] Version '{version}' not found in database.")
            console.print(
                f"Available versions: {', '.join(version_names) if version_names else 'none'}"
            )
            # Don't fail - allow setting baseline for future versions
    except Exception as e:
        console.print(f"[yellow]Warning:[/] Could not validate version: {e}")

    # Save to config
    try:
        config_path = save_config("DRIFTBASE_BASELINE_VERSION", version, scope=scope)
        scope_label = "global" if scope == "global" else "local"
        console.print(f"[green]✓[/] Baseline set to [cyan]{version}[/] ({scope_label})")
        console.print(f"   Config saved to: {config_path}")
    except Exception as e:
        console.print(f"[red]Error:[/] Failed to save baseline: {e}")
        ctx.exit(1)


@baseline_group.command(name="get")
@click.pass_context
def baseline_get(ctx: click.Context):
    """
    Show the current baseline version.

    Example:
        driftbase baseline get
    """
    console = ctx.obj.get("console")

    settings = get_settings()
    baseline = settings.DRIFTBASE_BASELINE_VERSION

    if baseline:
        source = get_config_source("DRIFTBASE_BASELINE_VERSION")
        console.print(f"Current baseline: [cyan]{baseline}[/] (from {source})")
        ctx.exit(0)
    else:
        console.print("[yellow]No baseline version set.[/]")
        console.print("\nSet a baseline with:")
        console.print("  driftbase baseline set <version>")
        ctx.exit(1)


@baseline_group.command(name="clear")
@click.option(
    "--global",
    "scope",
    flag_value="global",
    default=True,
    help="Clear from global config.",
)
@click.option(
    "--local", "scope", flag_value="local", help="Clear from project config."
)
@click.pass_context
def baseline_clear(ctx: click.Context, scope: str):
    """
    Clear the baseline version.

    Examples:
        driftbase baseline clear
        driftbase baseline clear --local
    """
    console = ctx.obj.get("console")

    # Delete from config file
    deleted = delete_config_key("DRIFTBASE_BASELINE_VERSION", scope=scope)

    scope_label = "global" if scope == "global" else "local"
    if deleted:
        console.print(f"[green]✓[/] Baseline cleared ({scope_label})")
    else:
        console.print(
            f"[yellow]No baseline found in {scope_label} config[/]"
        )

    ctx.exit(0)
