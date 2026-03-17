"""
Upgrade command: Upgrade driftbase to the latest version.
"""

from __future__ import annotations

import subprocess
import sys

import click


def _safe_import_rich():
    try:
        from rich.console import Console

        return Console
    except ImportError:
        return None


@click.command(name="upgrade")
@click.option(
    "--check-only",
    is_flag=True,
    help="Only check for updates without installing.",
)
@click.pass_context
def cmd_upgrade(ctx: click.Context, check_only: bool) -> None:
    """
    Upgrade driftbase to the latest version.

    \b
    Examples:
      driftbase upgrade              # Upgrade to latest version
      driftbase upgrade --check-only # Check for updates without installing
    """
    Console = _safe_import_rich()
    console = ctx.obj.get("console") if Console else None

    if not console:
        # Fallback to plain text if Rich not available
        console = type("PlainConsole", (), {"print": lambda self, x, **kw: print(x)})()

    # Get current version
    try:
        from importlib.metadata import version

        current_version = version("driftbase")
    except Exception:
        current_version = "unknown"

    console.print(f"Current version: [cyan]{current_version}[/]")

    if check_only:
        # Check PyPI for latest version
        try:
            import requests

            response = requests.get(
                "https://pypi.org/pypi/driftbase/json", timeout=10
            )
            if response.status_code == 200:
                data = response.json()
                latest_version = data["info"]["version"]
                console.print(f"Latest version:  [cyan]{latest_version}[/]")

                if current_version != latest_version and current_version != "unknown":
                    console.print(
                        f"\n[yellow]⚠[/] Update available: {current_version} → {latest_version}"
                    )
                    console.print(
                        "Run [cyan]driftbase upgrade[/] to install the latest version"
                    )
                else:
                    console.print("\n[green]✓[/] You are on the latest version")
            else:
                console.print(
                    f"[yellow]⚠[/] Could not check for updates (status {response.status_code})"
                )
        except Exception as e:
            console.print(f"[yellow]⚠[/] Could not check for updates: {e}")
        return

    # Perform upgrade
    console.print("\n[dim]Running: pip install --upgrade driftbase[/]\n")

    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--upgrade", "driftbase"],
            capture_output=True,
            text=True,
        )

        # Show output
        if result.stdout:
            console.print(result.stdout)

        if result.returncode == 0:
            # Get new version after upgrade
            try:
                # Need to reload metadata
                from importlib import metadata, reload

                if hasattr(metadata, "_cache"):
                    metadata._cache.clear()
                new_version = metadata.version("driftbase")
                console.print(
                    f"\n[green]✓[/] Successfully upgraded driftbase to version [cyan]{new_version}[/]"
                )

                if new_version != current_version:
                    console.print(
                        f"[dim]Upgraded from {current_version} → {new_version}[/]"
                    )
                else:
                    console.print("[dim]Already on the latest version[/]")
            except Exception:
                console.print("\n[green]✓[/] Successfully upgraded driftbase")
        else:
            console.print("\n[red]✗[/] Upgrade failed")
            if result.stderr:
                console.print(f"[red]{result.stderr}[/]")
            ctx.exit(1)

    except Exception as e:
        console.print(f"\n[red]✗[/] Upgrade failed: {e}[/]")
        console.print(
            "\n[dim]You can manually upgrade with:[/] [cyan]pip install --upgrade driftbase[/]"
        )
        ctx.exit(1)
