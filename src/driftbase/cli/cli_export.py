"""
Export and import commands for driftbase runs.

Enables backing up and restoring run data across environments,
and sharing baseline data for CI/CD drift detection.
"""

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import click

from driftbase.backends.factory import get_backend


def _print_to_stderr(message: str) -> None:
    """Print to stderr to avoid polluting JSON output when piping to stdout."""
    click.echo(message, err=True)


def _safe_json_serialize(obj: Any) -> str:
    """Serialize object to JSON, handling datetime and other non-serializable types."""
    return json.dumps(obj, default=str, indent=2)


def _parse_datetime(dt_str: Any) -> datetime:
    """Parse datetime string to datetime object, handling various formats."""
    if isinstance(dt_str, datetime):
        return dt_str
    if not isinstance(dt_str, str):
        return datetime.utcnow()
    try:
        # Try ISO format first
        return datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        # Fall back to current time if parsing fails
        return datetime.utcnow()


def _prepare_run_for_import(run: dict[str, Any]) -> dict[str, Any]:
    """Convert datetime strings to datetime objects for database import."""
    prepared = run.copy()

    # Convert datetime fields from strings to datetime objects
    if "started_at" in prepared:
        prepared["started_at"] = _parse_datetime(prepared["started_at"])
    if "completed_at" in prepared:
        prepared["completed_at"] = _parse_datetime(prepared["completed_at"])

    return prepared


@click.command(name="export")
@click.option(
    "--output",
    "-o",
    type=click.Path(),
    default=None,
    help="Write to file instead of stdout (e.g., --output runs.json)",
)
@click.option(
    "--version",
    "-v",
    type=str,
    default=None,
    help="Export only runs for a specific deployment version (e.g., --version v1.0)",
)
@click.pass_context
def export_command(
    ctx: click.Context, output: Optional[str], version: Optional[str]
) -> None:
    """
    Export all runs from local SQLite database to JSON.

    By default, writes JSON to stdout so you can pipe to a file:
        driftbase export > runs.json

    Or write directly to a file:
        driftbase export --output runs.json

    Export only a specific version:
        driftbase export --version v1.0 --output v1_runs.json
    """
    try:
        backend = get_backend()

        # Get all versions or filter to specific version
        if version:
            versions_to_export = [(version, 0)]  # count is not needed
            _print_to_stderr(f"Exporting runs for version: {version}")
        else:
            versions_to_export = backend.get_versions()
            _print_to_stderr(f"Exporting runs for {len(versions_to_export)} version(s)")

        # Collect all runs
        all_runs = []
        runs_per_version = {}

        for ver, _ in versions_to_export:
            # Fetch runs for this version (large limit to get all)
            runs = backend.get_runs(deployment_version=ver, limit=1000000)
            all_runs.extend(runs)
            runs_per_version[ver] = len(runs)

        # Serialize to JSON
        json_output = _safe_json_serialize(all_runs)

        # Write output
        if output:
            output_path = Path(output)
            output_path.write_text(json_output)
            _print_to_stderr(f"✓ Wrote {len(all_runs)} runs to {output}")
        else:
            # Write to stdout (don't use click.echo as it may add formatting)
            sys.stdout.write(json_output)
            sys.stdout.write("\n")

        # Print summary to stderr
        _print_to_stderr("\nExport summary:")
        for ver, count in sorted(runs_per_version.items()):
            _print_to_stderr(f"  {ver}: {count} runs")
        _print_to_stderr(f"  Total: {len(all_runs)} runs")

    except Exception as e:
        _print_to_stderr(f"Error during export: {e}")
        sys.exit(1)


@click.command(name="import")
@click.argument("json_file", type=click.Path(exists=True))
@click.option(
    "--merge/--no-merge",
    default=True,
    help="Skip runs whose ID already exists (default: --merge)",
)
@click.option(
    "--replace",
    is_flag=True,
    default=False,
    help="Clear all runs for each version in import file before importing",
)
@click.pass_context
def import_command(
    ctx: click.Context,
    json_file: str,
    merge: bool,
    replace: bool,
) -> None:
    """
    Import runs from JSON file into local SQLite database.

    Import runs from exported file:
        driftbase import runs.json

    Replace existing runs for imported versions:
        driftbase import runs.json --replace

    Overwrite duplicate runs (no merge):
        driftbase import runs.json --no-merge
    """
    try:
        backend = get_backend()
        json_path = Path(json_file)

        # Read and parse JSON
        click.echo(f"Reading {json_path}...")
        try:
            json_text = json_path.read_text()
            runs = json.loads(json_text)
        except json.JSONDecodeError as e:
            click.echo(f"Error: Invalid JSON in {json_path}: {e}", err=True)
            sys.exit(1)

        if not isinstance(runs, list):
            click.echo(
                f"Error: Expected JSON array, got {type(runs).__name__}", err=True
            )
            sys.exit(1)

        click.echo(f"✓ Loaded {len(runs)} runs from {json_path}")

        # Group runs by version for replace mode
        versions_in_import = set()
        for run in runs:
            ver = run.get("deployment_version", "unknown")
            versions_in_import.add(ver)

        # Replace mode: delete existing runs for versions in import file
        if replace:
            click.echo(
                f"\n--replace mode: Clearing existing runs for {len(versions_in_import)} version(s)..."
            )
            for ver in versions_in_import:
                deleted = backend.delete_runs(ver)
                click.echo(f"  Deleted {deleted} runs for version {ver}")

        # Merge mode: filter out runs that already exist
        if merge and not replace:
            click.echo("\n--merge mode: Checking for duplicate run IDs...")
            existing_ids = set()
            for ver in versions_in_import:
                existing_runs = backend.get_runs(deployment_version=ver, limit=1000000)
                for run in existing_runs:
                    existing_ids.add(run.get("id"))

            original_count = len(runs)
            runs = [r for r in runs if r.get("id") not in existing_ids]
            skipped = original_count - len(runs)
            if skipped > 0:
                click.echo(f"  Skipped {skipped} duplicate runs")

        # Import runs
        if not runs:
            click.echo("\nNo runs to import (all duplicates or empty file)")
            return

        click.echo(f"\nImporting {len(runs)} runs...")

        # Write in batches for efficiency
        batch_size = 100
        imported = 0
        for i in range(0, len(runs), batch_size):
            batch = runs[i : i + batch_size]
            # Convert datetime strings to datetime objects
            prepared_batch = [_prepare_run_for_import(run) for run in batch]
            try:
                backend.write_runs(prepared_batch)
                imported += len(batch)
                if (i + batch_size) % 1000 == 0:
                    click.echo(f"  Imported {imported}/{len(runs)} runs...")
            except Exception as e:
                click.echo(
                    f"Warning: Failed to import batch at index {i}: {e}", err=True
                )
                # Continue with next batch instead of failing completely

        click.echo(f"✓ Imported {imported} runs")

        # Print summary by version
        runs_per_version = {}
        for run in runs:
            ver = run.get("deployment_version", "unknown")
            runs_per_version[ver] = runs_per_version.get(ver, 0) + 1

        click.echo("\nImport summary:")
        for ver, count in sorted(runs_per_version.items()):
            click.echo(f"  {ver}: {count} runs")
        click.echo(f"  Total: {imported} runs")

    except Exception as e:
        click.echo(f"Error during import: {e}", err=True)
        import traceback

        traceback.print_exc()
        sys.exit(1)
