"""
Plugin commands: Manage Driftbase plugins for custom integrations.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import click


def _safe_import_rich():
    try:
        from rich.console import Console
        from rich.panel import Panel
        from rich.table import Table

        return Console, Panel, Table
    except ImportError:
        return None, None, None


def _get_plugin_dir() -> Path:
    """Get the plugin directory path."""
    try:
        return Path.home() / ".driftbase" / "plugins"
    except Exception:
        return Path(".driftbase") / "plugins"


@click.group(name="plugin")
def plugin_group():
    """Manage plugins for custom checks and integrations."""
    pass


@plugin_group.command(name="list")
@click.pass_context
def plugin_list(ctx: click.Context):
    """
    List all installed plugins.

    Example:
        driftbase plugin list
    """
    Console, Panel, Table = _safe_import_rich()
    console = ctx.obj.get("console") if Console else None

    if not console:
        console = type("PlainConsole", (), {"print": lambda self, x: print(x)})()

    from driftbase.plugins import get_plugin_manager

    pm = get_plugin_manager()

    if not pm.plugins:
        console.print("[yellow]No plugins installed[/]")
        console.print()
        console.print("Install plugins by placing Python files in:")
        console.print(f"  {_get_plugin_dir()}")
        console.print()
        console.print("See documentation for plugin development guide.")
        ctx.exit(0)

    console.print(f"\n[bold cyan]🔌 Installed Plugins[/] ({len(pm.plugins)})\n")

    if Table:
        table = Table(show_header=True, header_style="bold")
        table.add_column("Name", style="cyan")
        table.add_column("Version")
        table.add_column("Description", max_width=50)
        table.add_column("Author", style="dim")

        for plugin in pm.plugins:
            table.add_row(
                plugin.name,
                plugin.version,
                plugin.description or "(no description)",
                plugin.author or "unknown",
            )

        console.print(table)
        console.print()
    else:
        for plugin in pm.plugins:
            print(f"\n{plugin.name} v{plugin.version}")
            if plugin.description:
                print(f"  {plugin.description}")
            if plugin.author:
                print(f"  Author: {plugin.author}")

    console.print(f"[dim]Plugin directory: {_get_plugin_dir()}[/]\n")
    ctx.exit(0)


@plugin_group.command(name="info")
@click.argument("plugin_name")
@click.pass_context
def plugin_info(ctx: click.Context, plugin_name: str):
    """
    Show detailed information about a plugin.

    Example:
        driftbase plugin info slack-notifier
    """
    Console, Panel, Table = _safe_import_rich()
    console = ctx.obj.get("console") if Console else None

    if not console:
        console = type("PlainConsole", (), {"print": lambda self, x: print(x)})()

    from driftbase.plugins import get_plugin_manager

    pm = get_plugin_manager()

    # Find plugin
    plugin = None
    for p in pm.plugins:
        if p.name == plugin_name:
            plugin = p
            break

    if not plugin:
        console.print(f"[red]Plugin '{plugin_name}' not found[/]")
        console.print()
        console.print("Available plugins:")
        for p in pm.plugins:
            console.print(f"  • {p.name}")
        ctx.exit(1)

    # Display plugin details
    info_lines = [
        f"[bold]Name:[/] {plugin.name}",
        f"[bold]Version:[/] {plugin.version}",
        f"[bold]Author:[/] {plugin.author or 'unknown'}",
        "",
        "[bold]Description:[/]",
        f"{plugin.description or '(no description)'}",
        "",
        "[bold]Hooks implemented:[/]",
    ]

    # Check which hooks are implemented
    from driftbase.plugins import Plugin

    hooks = []
    if plugin.on_pre_diff.__func__ != Plugin.on_pre_diff:  # type: ignore
        hooks.append("  • on_pre_diff - Called before diff computation")
    if plugin.on_post_diff.__func__ != Plugin.on_post_diff:  # type: ignore
        hooks.append("  • on_post_diff - Called after diff computation")
    if plugin.on_pre_report.__func__ != Plugin.on_pre_report:  # type: ignore
        hooks.append("  • on_pre_report - Called before report generation")
    if plugin.on_post_report.__func__ != Plugin.on_post_report:  # type: ignore
        hooks.append("  • on_post_report - Called after report generation")
    if plugin.on_drift_detected.__func__ != Plugin.on_drift_detected:  # type: ignore
        hooks.append("  • on_drift_detected - Called when drift exceeds threshold")
    if plugin.custom_check.__func__ != Plugin.custom_check:  # type: ignore
        hooks.append("  • custom_check - Custom check for 'driftbase doctor'")

    if hooks:
        info_lines.extend(hooks)
    else:
        info_lines.append("  (no hooks implemented)")

    if Panel:
        panel = Panel(
            "\n".join(info_lines),
            title=f"[bold cyan]Plugin: {plugin.name}[/]",
            border_style="cyan",
        )
        console.print()
        console.print(panel)
        console.print()
    else:
        print(f"\nPlugin: {plugin.name}")
        for line in info_lines:
            print(line)
        print()

    ctx.exit(0)


@plugin_group.command(name="init")
@click.pass_context
def plugin_init(ctx: click.Context):
    """
    Initialize plugin directory and create example plugin.

    This creates ~/.driftbase/plugins/ and generates an example plugin
    to help you get started with plugin development.

    Example:
        driftbase plugin init
    """
    Console, Panel, Table = _safe_import_rich()
    console = ctx.obj.get("console") if Console else None

    if not console:
        console = type("PlainConsole", (), {"print": lambda self, x: print(x)})()

    plugin_dir = _get_plugin_dir()

    # Create plugin directory
    plugin_dir.mkdir(parents=True, exist_ok=True)

    # Create example plugin
    example_file = plugin_dir / "example_plugin.py"

    if example_file.exists():
        console.print(f"[yellow]Example plugin already exists:[/] {example_file}")
        if not click.confirm("Overwrite?", default=False):
            console.print("[dim]Cancelled[/]")
            ctx.exit(0)

    example_code = '''"""
Example Driftbase plugin.

This plugin demonstrates the plugin API and hook system.
"""

from driftbase.plugins import Plugin


class ExamplePlugin(Plugin):
    """Example plugin showing available hooks."""

    name = "example"
    version = "1.0.0"
    description = "Example plugin demonstrating the plugin API"
    author = "Driftbase Team"

    def on_drift_detected(self, context):
        """Log when drift is detected."""
        drift_score = context.get("drift_score", 0)
        threshold = context.get("threshold", 0)
        baseline = context.get("baseline_version", "unknown")
        current = context.get("current_version", "unknown")

        print(f"[Plugin] Drift detected: {current} vs {baseline}")
        print(f"[Plugin] Score: {drift_score:.3f} (threshold: {threshold:.3f})")

        # You could send notifications, log to external system, etc.
        return None  # Return None to continue unchanged

    def custom_check(self, context):
        """Custom check for 'driftbase doctor' command."""
        return {
            "status": "pass",
            "message": "Example plugin check",
            "details": "Plugin is working correctly",
        }
'''

    example_file.write_text(example_code)

    console.print("[green]✓[/] Plugin system initialized")
    console.print()
    console.print(f"Plugin directory: [cyan]{plugin_dir}[/]")
    console.print(f"Example plugin:   [cyan]{example_file}[/]")
    console.print()
    console.print("To create your own plugin:")
    console.print("  1. Create a .py file in the plugins directory")
    console.print("  2. Define a class that inherits from Plugin")
    console.print("  3. Implement hook methods (on_drift_detected, etc.)")
    console.print("  4. Test with 'driftbase plugin list'")
    console.print()
    console.print("Available hooks:")
    console.print("  • on_pre_diff - Before diff computation")
    console.print("  • on_post_diff - After diff computation")
    console.print("  • on_pre_report - Before report generation")
    console.print("  • on_post_report - After report generation")
    console.print("  • on_drift_detected - When drift exceeds threshold")
    console.print("  • custom_check - Custom check for 'doctor' command")

    ctx.exit(0)


@plugin_group.command(name="disable")
@click.argument("plugin_name")
@click.pass_context
def plugin_disable(ctx: click.Context, plugin_name: str):
    """
    Disable a plugin by renaming it to .disabled.

    Example:
        driftbase plugin disable example
    """
    Console, Panel, Table = _safe_import_rich()
    console = ctx.obj.get("console") if Console else None

    if not console:
        console = type("PlainConsole", (), {"print": lambda self, x: print(x)})()

    plugin_dir = _get_plugin_dir()
    plugin_file = plugin_dir / f"{plugin_name}.py"

    if not plugin_file.exists():
        console.print(f"[red]Plugin file not found:[/] {plugin_file}")
        ctx.exit(1)

    disabled_file = plugin_dir / f"{plugin_name}.py.disabled"

    try:
        plugin_file.rename(disabled_file)
        console.print(f"[green]✓[/] Plugin disabled: [cyan]{plugin_name}[/]")
        console.print(f"  Renamed to: {disabled_file.name}")
        console.print()
        console.print(f"To re-enable: driftbase plugin enable {plugin_name}")
    except Exception as e:
        console.print(f"[red]Error:[/] Failed to disable plugin: {e}")
        ctx.exit(1)

    ctx.exit(0)


@plugin_group.command(name="enable")
@click.argument("plugin_name")
@click.pass_context
def plugin_enable(ctx: click.Context, plugin_name: str):
    """
    Enable a disabled plugin.

    Example:
        driftbase plugin enable example
    """
    Console, Panel, Table = _safe_import_rich()
    console = ctx.obj.get("console") if Console else None

    if not console:
        console = type("PlainConsole", (), {"print": lambda self, x: print(x)})()

    plugin_dir = _get_plugin_dir()
    disabled_file = plugin_dir / f"{plugin_name}.py.disabled"

    if not disabled_file.exists():
        console.print(f"[red]Disabled plugin not found:[/] {disabled_file}")
        ctx.exit(1)

    plugin_file = plugin_dir / f"{plugin_name}.py"

    try:
        disabled_file.rename(plugin_file)
        console.print(f"[green]✓[/] Plugin enabled: [cyan]{plugin_name}[/]")
        console.print(f"  Renamed to: {plugin_file.name}")
        console.print()
        console.print("Plugin will be loaded on next command execution")
    except Exception as e:
        console.print(f"[red]Error:[/] Failed to enable plugin: {e}")
        ctx.exit(1)

    ctx.exit(0)
