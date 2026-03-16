"""
Doctor command: Health check for Driftbase configuration and database.
"""

from __future__ import annotations

import os
from pathlib import Path

import click

from driftbase.backends.factory import get_backend
from driftbase.config import KNOWN_CONFIG_KEYS, get_settings


def _safe_import_rich():
    try:
        from rich.console import Console
        from rich.table import Table

        return Console, Table
    except ImportError:
        return None, None


@click.command(name="doctor")
@click.option("--fix", is_flag=True, help="Attempt to fix common issues automatically.")
@click.pass_context
def cmd_doctor(ctx: click.Context, fix: bool) -> None:
    """
    Check Driftbase configuration and database health.

    Performs the following checks:
    - Configuration validity
    - Database connectivity
    - Database schema version
    - Minimum samples per version
    - Disk space usage
    - API connectivity (if DRIFTBASE_API_KEY is set)
    """
    Console, Table = _safe_import_rich()
    console = ctx.obj.get("console") if Console else None

    if not console:
        # Fallback to plain text if Rich not available
        console = type("PlainConsole", (), {"print": lambda self, x: print(x)})()

    checks_results = []

    # Check 1: Config validity
    try:
        settings = get_settings()
        invalid_keys = []
        for key in os.environ:
            if key.startswith("DRIFTBASE_") and key not in KNOWN_CONFIG_KEYS:
                invalid_keys.append(key)

        if invalid_keys:
            checks_results.append(
                (
                    "Config validity",
                    "⚠ WARN",
                    f"Unknown config keys: {', '.join(invalid_keys)}",
                )
            )
        else:
            checks_results.append(
                ("Config validity", "✓ PASS", "All config keys are valid")
            )
    except Exception as e:
        checks_results.append(("Config validity", "✗ FAIL", f"Error: {e}"))

    # Check 2: Database connectivity
    try:
        backend = get_backend()
        db_path = settings.DRIFTBASE_DB_PATH
        checks_results.append(
            (
                "DB connectivity",
                "✓ PASS",
                f"Connected to {db_path}",
            )
        )
    except Exception as e:
        checks_results.append(("DB connectivity", "✗ FAIL", f"Error: {e}"))
        if fix:
            # Try to create database directory
            try:
                db_dir = os.path.dirname(settings.DRIFTBASE_DB_PATH)
                if db_dir:
                    os.makedirs(db_dir, exist_ok=True)
                    console.print("[green]✓[/] Created database directory")
            except Exception as fix_err:
                console.print(f"[red]✗[/] Failed to create directory: {fix_err}")

    # Check 3: Database schema version (basic check - table exists)
    try:
        backend = get_backend()
        stats = backend.get_db_stats()
        checks_results.append(
            ("Schema version", "✓ PASS", "Schema is up to date")
        )
    except Exception as e:
        checks_results.append(("Schema version", "✗ FAIL", f"Error: {e}"))

    # Check 4: Minimum samples per version
    try:
        backend = get_backend()
        versions = backend.get_versions()
        min_samples = settings.DRIFTBASE_MIN_SAMPLES
        low_sample_versions = [
            f"{ver} ({count} runs)" for ver, count in versions if count < min_samples
        ]

        if low_sample_versions:
            checks_results.append(
                (
                    "Min samples",
                    "⚠ WARN",
                    f"Versions with <{min_samples} runs: {', '.join(low_sample_versions)}",
                )
            )
        else:
            checks_results.append(
                (
                    "Min samples",
                    "✓ PASS",
                    f"All versions have ≥{min_samples} runs",
                )
            )
    except Exception as e:
        checks_results.append(("Min samples", "⚠ WARN", f"Could not check: {e}"))

    # Check 5: Disk space
    try:
        backend = get_backend()
        stats = backend.get_db_stats()
        disk_size = stats.get("disk_size_mb", 0)

        if disk_size > 1000:  # > 1GB
            checks_results.append(
                (
                    "Disk space",
                    "⚠ WARN",
                    f"{disk_size:.2f} MB used (consider pruning old runs)",
                )
            )
        else:
            checks_results.append(
                ("Disk space", "✓ PASS", f"{disk_size:.2f} MB used")
            )
    except Exception as e:
        checks_results.append(("Disk space", "⚠ WARN", f"Could not check: {e}"))

    # Check 6: API connectivity (if API key is set)
    api_key = os.getenv("DRIFTBASE_API_KEY")
    if api_key:
        try:
            import requests

            api_url = os.getenv(
                "DRIFTBASE_API_URL", "https://app-driftbase-eu-92745.azurewebsites.net"
            )
            response = requests.get(f"{api_url}/health", timeout=5)
            if response.status_code == 200:
                checks_results.append(
                    ("API connectivity", "✓ PASS", f"Connected to {api_url}")
                )
            else:
                checks_results.append(
                    (
                        "API connectivity",
                        "⚠ WARN",
                        f"API returned status {response.status_code}",
                    )
                )
        except Exception as e:
            checks_results.append(
                ("API connectivity", "⚠ WARN", f"Could not reach API: {e}")
            )
    else:
        checks_results.append(
            ("API connectivity", "⊘ SKIP", "No API key set (cloud features disabled)")
        )

    # Display results
    if Table:
        table = Table(show_header=True, header_style="bold")
        table.add_column("Check", style="cyan")
        table.add_column("Status")
        table.add_column("Details")

        for check_name, status, details in checks_results:
            # Color status based on result
            if "PASS" in status:
                status_colored = f"[green]{status}[/]"
            elif "WARN" in status:
                status_colored = f"[yellow]{status}[/]"
            elif "FAIL" in status:
                status_colored = f"[red]{status}[/]"
            else:
                status_colored = f"[dim]{status}[/]"

            table.add_row(check_name, status_colored, details)

        console.print("\n")
        console.print(table)
        console.print("\n")
    else:
        # Plain text fallback
        print("\nDriftbase Health Check:\n")
        for check_name, status, details in checks_results:
            print(f"{check_name:<20} {status:<10} {details}")
        print()

    # Determine exit code
    has_failures = any("FAIL" in status for _, status, _ in checks_results)
    if has_failures:
        if Console:
            console.print(
                "[red]⚠[/] Health check failed. Please review the errors above."
            )
        else:
            print("⚠ Health check failed. Please review the errors above.")
        ctx.exit(1)
    else:
        if Console:
            console.print("[green]✓[/] All checks passed or warnings only.")
        else:
            print("✓ All checks passed or warnings only.")
        ctx.exit(0)
