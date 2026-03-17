"""
CLI for driftbase: versions, diff, watch, inspect, report, push, demo.
Uses click for parsing and rich for output.
"""

from __future__ import annotations

import os
import sys

import click

from driftbase.backends.factory import get_backend
from driftbase.cli._deps import safe_import_rich

# Lazy import of heavy [analyze] dependencies
Console, Panel, Table = safe_import_rich()


def _get_version() -> str:
    """Read version from package metadata (setuptools_scm at build time). Fallback when run from source."""
    try:
        from importlib.metadata import version

        return version("driftbase")
    except Exception:
        return "0.0.0.dev0"


def _console_no_color(no_color_flag: bool) -> bool:
    """True if output should be uncolored: --no-color wins, else use DRIFTBASE_OUTPUT_COLOR."""
    if no_color_flag:
        return True
    try:
        from driftbase.config import get_settings

        return not get_settings().DRIFTBASE_OUTPUT_COLOR
    except Exception:
        return False


@click.group()
@click.version_option(version=_get_version(), prog_name="driftbase")
@click.option(
    "--no-color",
    is_flag=True,
    help="Disable colored output (overrides DRIFTBASE_OUTPUT_COLOR).",
)
@click.pass_context
def cli(ctx: click.Context, no_color: bool) -> None:
    """Behavioral watchdog for AI agents — versions, diff, watch, inspect, report."""
    ctx.ensure_object(dict)
    ctx.obj["console"] = Console(no_color=_console_no_color(no_color))


from driftbase.cli.cli_baseline import baseline_group
from driftbase.cli.cli_bookmark import bookmark_group
from driftbase.cli.cli_chart import cmd_chart
from driftbase.cli.cli_compare import cmd_compare
from driftbase.cli.cli_cost import cmd_cost
from driftbase.cli.cli_demo import cmd_demo
from driftbase.cli.cli_diff import cmd_diff
from driftbase.cli.cli_doctor import cmd_doctor
from driftbase.cli.cli_explore import cmd_explore
from driftbase.cli.cli_export import export_command, import_command
from driftbase.cli.cli_git import git_group
from driftbase.cli.cli_init import cmd_init
from driftbase.cli.cli_inspect import cmd_inspect
from driftbase.cli.cli_plugin import plugin_group
from driftbase.cli.cli_prune import cmd_prune
from driftbase.cli.cli_push import cmd_push
from driftbase.cli.cli_report import cmd_report
from driftbase.cli.cli_status import cmd_status
from driftbase.cli.cli_tail import cmd_tail
from driftbase.cli.cli_upgrade import cmd_upgrade

cli.add_command(cmd_init)
cli.add_command(cmd_diff)
cli.add_command(cmd_inspect)
cli.add_command(cmd_report)
cli.add_command(cmd_push)
cli.add_command(cmd_demo)
cli.add_command(export_command)
cli.add_command(import_command)
# Phase 1 commands (comprehensive improvements)
cli.add_command(cmd_doctor)
cli.add_command(cmd_upgrade)
cli.add_command(baseline_group)
cli.add_command(cmd_tail)
cli.add_command(cmd_prune)
cli.add_command(cmd_status)
# Phase 2 commands (medium effort, high value)
cli.add_command(cmd_chart)
cli.add_command(cmd_compare)
cli.add_command(bookmark_group)
cli.add_command(cmd_explore)
# Phase 3 commands (future / high effort, high value)
cli.add_command(git_group)
cli.add_command(cmd_cost)
cli.add_command(plugin_group)

# Command aliases are added at the end of the file after all commands are defined


def _mask_secret(value: str) -> str:
    """Mask values that look like API keys or secrets."""
    if not value or len(value) < 8:
        return value
    import re

    s = value.strip()
    if s.startswith("sk-") and len(s) > 20:
        return "sk-***[REDACTED]"
    if s.startswith("pk_") or s.startswith("sk_"):
        return s[:6] + "***[REDACTED]"
    if re.match(r"^[a-zA-Z0-9_\-]{32,}$", s):
        return "***[REDACTED]"
    return value


def _load_config_file() -> dict[str, str]:
    """Load KEY=value from DRIFTBASE_CONFIG_PATH or ~/.driftbase/config."""
    config_path = os.environ.get("DRIFTBASE_CONFIG_PATH") or os.path.expanduser(
        "~/.driftbase/config"
    )
    if not os.path.isfile(config_path):
        return {}
    out: dict[str, str] = {}
    try:
        with open(config_path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    k, v = line.split("=", 1)
                    out[k.strip()] = v.strip().strip("'\"")
    except Exception:
        pass
    return out


def _get_config_rows() -> list[tuple[str, str, str, str]]:
    """Return list of (name, value, source, description) for config table.
    Source: env, config file (~/.driftbase/config or DRIFTBASE_CONFIG_PATH), or default.
    """
    file_config = _load_config_file()

    def _get(key: str, default: str) -> tuple[str, str]:
        if key in os.environ:
            return os.environ[key].strip(), "env"
        if key in file_config:
            return file_config[key].strip(), "config file"
        return default, "default"

    try:
        from driftbase.config import get_settings

        settings = get_settings()
        if "DRIFTBASE_DB_PATH" in os.environ:
            db_path = settings.DRIFTBASE_DB_PATH
            db_path_source = "env"
        elif "DRIFTBASE_DB_PATH" in file_config:
            db_path = os.path.expanduser(file_config["DRIFTBASE_DB_PATH"])
            db_path_source = "config file"
        else:
            db_path = os.path.expanduser("~/.driftbase/runs.db")
            db_path_source = "default"
        if "DRIFTBASE_MIN_SAMPLES" in os.environ:
            min_samples = settings.DRIFTBASE_MIN_SAMPLES
            min_samples_source = "env"
        elif "DRIFTBASE_MIN_SAMPLES" in file_config:
            try:
                min_samples = int(file_config["DRIFTBASE_MIN_SAMPLES"])
            except ValueError:
                min_samples = 10
            min_samples_source = "config file"
        else:
            min_samples = settings.DRIFTBASE_MIN_SAMPLES
            min_samples_source = "default"
    except Exception:
        db_path_val, db_path_source = _get("DRIFTBASE_DB_PATH", "~/.driftbase/runs.db")
        db_path = os.path.expanduser(db_path_val)
        min_samples_val, min_samples_source = _get("DRIFTBASE_MIN_SAMPLES", "10")
        try:
            min_samples = int(min_samples_val)
        except ValueError:
            min_samples = 10

    backend_raw, backend_source = _get("DRIFTBASE_BACKEND", "sqlite")

    deployment_version, deployment_version_source = _get(
        "DRIFTBASE_DEPLOYMENT_VERSION", ""
    )
    if not deployment_version:
        deployment_version = "—"

    environment, environment_source = _get("DRIFTBASE_ENVIRONMENT", "production")

    threshold_raw, threshold_source = _get("DRIFTBASE_DRIFT_THRESHOLD", "0.20")
    try:
        threshold_val = str(float(threshold_raw))
    except ValueError:
        threshold_val = "0.20"

    scrub_raw, scrub_source = _get("DRIFTBASE_SCRUB_PII", "false")
    scrub_pii = "true" if scrub_raw.lower() in ("1", "true", "yes", "on") else "false"

    hypothesis_rules, hypothesis_rules_source = _get("DRIFTBASE_HYPOTHESIS_RULES", "")
    if not hypothesis_rules:
        try:
            from driftbase.local.hypothesis_engine import _rules_path

            hypothesis_rules = str(_rules_path())
        except Exception:
            hypothesis_rules = "(bundled)"

    rate_prompt_raw, rate_prompt_source = _get("DRIFTBASE_RATE_PROMPT_1M", "2.50")
    rate_comp_raw, rate_comp_source = _get("DRIFTBASE_RATE_COMPLETION_1M", "10.00")

    return [
        (
            "DRIFTBASE_DB_PATH",
            _mask_secret(db_path),
            db_path_source,
            "Path to the local SQLite database.",
        ),
        (
            "DRIFTBASE_BACKEND",
            _mask_secret(backend_raw),
            backend_source,
            "Storage backend (e.g. sqlite).",
        ),
        (
            "DRIFTBASE_DEPLOYMENT_VERSION",
            _mask_secret(deployment_version),
            deployment_version_source,
            "Default deployment version when not passed to @track().",
        ),
        (
            "DRIFTBASE_ENVIRONMENT",
            _mask_secret(environment),
            environment_source,
            "Default environment (e.g. production).",
        ),
        (
            "DRIFTBASE_DRIFT_THRESHOLD",
            threshold_val,
            threshold_source,
            "Drift score threshold for diff/report (default 0.20).",
        ),
        (
            "DRIFTBASE_MIN_SAMPLES",
            str(min_samples),
            min_samples_source,
            "Minimum runs to compute a fingerprint (default 10).",
        ),
        (
            "DRIFTBASE_SCRUB_PII",
            scrub_pii,
            scrub_source,
            "Whether to scrub PII before hashing (default false).",
        ),
        (
            "DRIFTBASE_HYPOTHESIS_RULES",
            _mask_secret(hypothesis_rules),
            hypothesis_rules_source,
            "Path to hypothesis rules YAML (default: bundled).",
        ),
        (
            "DRIFTBASE_RATE_PROMPT_1M",
            rate_prompt_raw,
            rate_prompt_source,
            "EUR per 1M prompt tokens (default 2.50).",
        ),
        (
            "DRIFTBASE_RATE_COMPLETION_1M",
            rate_comp_raw,
            rate_comp_source,
            "EUR per 1M completion tokens (default 10.00).",
        ),
    ]


@cli.command("config")
@click.pass_context
def cmd_config(ctx: click.Context) -> None:
    """Show current Driftbase configuration (env, config file, and defaults)."""
    console: Console = ctx.obj["console"]
    table = Table(show_header=True, header_style="bold")
    table.add_column("SETTING", style="cyan")
    table.add_column("VALUE")
    table.add_column("SOURCE")
    table.add_column("DESCRIPTION")
    for name, value, source, desc in _get_config_rows():
        table.add_row(name, value, source, desc)
    console.print(table)


cli.add_command(cmd_config)


@cli.command("db-stats")
@click.pass_context
def cmd_db_stats(ctx: click.Context) -> None:
    """Print semantic_cluster counts from the local SQLite DB (for debugging capture)."""
    import sqlite3

    console: Console = ctx.obj["console"]
    backend_name = (os.getenv("DRIFTBASE_BACKEND") or "sqlite").strip().lower()
    if backend_name != "sqlite":
        console.print("db-stats is only supported for SQLite backend.", style="yellow")
        ctx.exit(1)
    db_path = os.path.expanduser(os.getenv("DRIFTBASE_DB_PATH", "~/.driftbase/runs.db"))
    if not os.path.isfile(db_path):
        console.print(f"Database not found: [bold]{db_path}[/]", style="red")
        ctx.exit(1)
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.execute(
            "SELECT semantic_cluster, COUNT(*) FROM agent_runs_local GROUP BY semantic_cluster"
        )
        rows = cur.fetchall()
        conn.close()
    except sqlite3.OperationalError as e:
        if "no such table" in str(e).lower():
            console.print(f"Table agent_runs_local not found in {db_path}", style="red")
        else:
            console.print(f"Query failed: {e}", style="red")
        ctx.exit(1)
    if not rows:
        console.print("No rows in agent_runs_local (or empty table).")
        return
    table = Table(show_header=True, header_style="bold")
    table.add_column("semantic_cluster", style="cyan")
    table.add_column("COUNT(*)", justify="right")
    for cluster, count in rows:
        table.add_row(str(cluster) if cluster else "NULL", str(count))
    console.print(table)


@cli.command("runs")
@click.option(
    "--version",
    "-v",
    required=True,
    metavar="VERSION",
    help="Deployment version to list runs for.",
)
@click.option(
    "--limit",
    "-n",
    type=int,
    default=50,
    metavar="N",
    help="Maximum number of runs to show (default 50).",
)
@click.option(
    "--offset", type=int, default=0, help="Skip first N runs (for pagination)."
)
@click.option(
    "--outcome",
    help="Filter by outcome (resolved, escalated, fallback, error).",
)
@click.option(
    "--min-latency",
    type=int,
    metavar="MS",
    help="Filter runs with latency >= MS milliseconds.",
)
@click.option(
    "--max-latency",
    type=int,
    metavar="MS",
    help="Filter runs with latency <= MS milliseconds.",
)
@click.option(
    "--since", metavar="DURATION", help="Show runs since duration (e.g., 24h, 7d)."
)
@click.option(
    "--today",
    "smart_time",
    flag_value="today",
    help="Show runs from today (last 24h).",
)
@click.option(
    "--yesterday",
    "smart_time",
    flag_value="yesterday",
    help="Show runs from yesterday.",
)
@click.option(
    "--this-week",
    "smart_time",
    flag_value="this-week",
    help="Show runs from this week.",
)
@click.option(
    "--errors-only",
    "quality_filter",
    flag_value="errors-only",
    help="Show only runs with errors.",
)
@click.option(
    "--slow",
    "quality_filter",
    flag_value="slow",
    help="Show only slow runs (>1s latency).",
)
@click.option(
    "--fast",
    "quality_filter",
    flag_value="fast",
    help="Show only fast runs (<100ms latency).",
)
@click.option(
    "--format",
    "-f",
    type=click.Choice(["table", "json", "csv"]),
    default="table",
    help="Output format.",
)
@click.pass_context
def cmd_runs(
    ctx: click.Context,
    version: str,
    limit: int,
    offset: int,
    outcome: str | None,
    min_latency: int | None,
    max_latency: int | None,
    since: str | None,
    smart_time: str | None,
    quality_filter: str | None,
    format: str,
) -> None:
    """
    List runs for a deployment version from the local backend.

    \b
    Examples:
      driftbase runs -v v2.0                    # Show last 50 runs
      driftbase runs -v v2.0 --today            # Show today's runs
      driftbase runs -v v2.0 --errors-only      # Show only errors
      driftbase runs -v v2.0 --slow --format json  # Slow runs as JSON
      driftbase ls -v v2.0                      # Alias for runs
    """
    console: Console = ctx.obj["console"]

    # Parse smart time filter
    from driftbase.cli.filters import parse_quality_filter, smart_filter_to_hours

    since_hours = None
    if smart_time:
        since_hours = smart_filter_to_hours(smart_time)
    elif since:
        import re

        match = re.match(r"^(\d+)([hdw])$", since.lower())
        if match:
            value, unit = match.groups()
            value = int(value)
            if unit == "h":
                since_hours = value
            elif unit == "d":
                since_hours = value * 24
            elif unit == "w":
                since_hours = value * 24 * 7

    # Parse quality filter
    quality_params = parse_quality_filter(quality_filter) if quality_filter else {}

    # Override explicit filters if quality filter provides them
    if quality_filter == "errors-only":
        outcome = "error"
    elif quality_filter == "slow" and not min_latency:
        min_latency = 1000
    elif quality_filter == "fast" and not max_latency:
        max_latency = 100

    try:
        backend = get_backend()

        # Use enhanced filtering if available
        if hasattr(backend, "get_runs_filtered"):
            runs = backend.get_runs_filtered(
                deployment_version=version,
                outcomes=[outcome] if outcome else None,
                min_latency_ms=min_latency,
                max_latency_ms=max_latency,
                since_hours=since_hours,
                offset=offset,
                limit=limit,
            )

            # Get total count for pagination info
            total_count = backend.count_runs_filtered(
                deployment_version=version,
                outcomes=[outcome] if outcome else None,
                min_latency_ms=min_latency,
                since_hours=since_hours,
            )
        else:
            # Fallback to basic get_runs
            runs = backend.get_runs(deployment_version=version, limit=limit)
            total_count = len(runs)

    except Exception as e:
        console.print(f"Backend error: [red]{e}[/]")
        ctx.exit(1)

    if not runs:
        console.print(f"[yellow]❌ No runs found for version[/] [cyan]{version}[/]\n")

        # Provide helpful suggestions
        try:
            all_versions = backend.get_versions()
            if all_versions:
                console.print("💡 [dim]Suggestions:[/]")

                # Check for similar version names (did you mean?)
                similar = [
                    v
                    for v, _ in all_versions
                    if version.lower() in v.lower() or v.lower() in version.lower()
                ]
                if similar:
                    console.print(
                        f"  • Did you mean: [cyan]{', '.join(similar)}[/]?"
                    )

                # Show available versions
                available = ", ".join([v for v, _ in all_versions[:5]])
                if len(all_versions) > 5:
                    available += f", ... ({len(all_versions)} total)"
                console.print(f"  • Available versions: {available}")
                console.print(
                    "  • Run [cyan]driftbase versions[/] to see all versions"
                )
            else:
                console.print(
                    "💡 [dim]No versions found in database. Try:[/]"
                )
                console.print("  • Run [cyan]driftbase demo[/] to generate sample data")
                console.print(
                    "  • Check DRIFTBASE_DB_PATH is correct: [cyan]{}[/]".format(
                        get_settings().DRIFTBASE_DB_PATH
                    )
                )
        except Exception:
            pass

        return

    # Output formats
    if format == "json":
        import json

        output = {
            "schema_version": "1.0",
            "runs": runs,
            "total_count": total_count,
            "offset": offset,
            "limit": limit,
        }
        console.print(json.dumps(output, indent=2, default=str))

    elif format == "csv":
        import csv
        import sys

        if runs:
            writer = csv.DictWriter(sys.stdout, fieldnames=runs[0].keys())
            writer.writeheader()
            writer.writerows(runs)

    else:
        # Table format (default)
        if offset > 0 or total_count > limit:
            console.print(
                f"[dim]Showing {offset + 1}-{offset + len(runs)} of {total_count} runs[/]\n"
            )

        table = Table(show_header=True, header_style="bold")
        table.add_column("RUN_ID", style="dim")
        table.add_column("TIMESTAMP")
        table.add_column("LATENCY_MS", justify="right")
        table.add_column("TOOL_SEQUENCE", max_width=40, overflow="ellipsis")
        table.add_column("SEMANTIC_CLUSTER")
        table.add_column("ERROR_COUNT", justify="right")
        for r in runs:
            run_id = str(r.get("id", ""))[:8]
            started = r.get("started_at")
            if hasattr(started, "strftime"):
                ts = started.strftime("%Y-%m-%d %H:%M:%S")
            else:
                ts = str(started) if started else "—"
            latency = r.get("latency_ms", 0)
            raw_seq = str(r.get("tool_sequence", "[]"))
            tool_seq = (raw_seq[:39] + "…") if len(raw_seq) > 40 else raw_seq
            cluster = str(r.get("semantic_cluster", "—"))
            errors = r.get("error_count", 0)
            table.add_row(run_id, ts, str(latency), tool_seq, cluster, str(errors))
        console.print(table)


@cli.command("versions")
@click.pass_context
def cmd_versions(ctx: click.Context) -> None:
    """List deployment versions and run counts."""
    console: Console = ctx.obj["console"]
    try:
        backend = get_backend()
        versions = backend.get_versions()
    except Exception as e:
        console.print(f"Backend error: [red]{e}[/]")
        ctx.exit(1)
    if not versions:
        console.print("No versions in database.")
        return
    table = Table(show_header=True, header_style="bold")
    table.add_column("VERSION", style="cyan")
    table.add_column("RUNS", justify="right")
    for version, count in versions:
        table.add_row(version, str(count))
    console.print(table)


@cli.command("reset")
@click.option(
    "--version",
    "-v",
    required=True,
    metavar="VERSION",
    help="Deployment version whose runs to delete.",
)
@click.option(
    "--yes", "-y", is_flag=True, default=False, help="Skip confirmation prompt."
)
@click.pass_context
def cmd_reset(ctx: click.Context, version: str, yes: bool) -> None:
    """Delete all runs for a deployment version."""
    console: Console = ctx.obj["console"]
    if not yes and not click.confirm(
        f"This will delete all runs for version {version}. Are you sure? [y/N]",
        default=False,
    ):
        console.print("Aborted.")
        ctx.exit(0)
        return
    try:
        backend = get_backend()
        n = backend.delete_runs(deployment_version=version)
    except Exception as e:
        console.print(f"Backend error: [red]{e}[/]")
        ctx.exit(1)
    console.print(f"Deleted {n} runs for version {version}.")


@cli.command("watch")
@click.option(
    "--against",
    "-a",
    required=True,
    metavar="VERSION",
    help="Baseline version to compare against.",
)
@click.option(
    "--interval",
    "-i",
    type=float,
    default=5.0,
    help="Poll interval in seconds (default 5).",
)
@click.option(
    "--min-runs",
    type=int,
    default=10,
    help="Minimum runs before computing (default 10).",
)
@click.option(
    "--last",
    "-n",
    type=int,
    default=20,
    help="Number of recent runs for current window (default 20).",
)
@click.option("--environment", "-e", default=None, help="Filter by environment.")
@click.option(
    "--threshold",
    "-t",
    type=float,
    default=0.20,
    help="Drift threshold (default 0.20).",
)
@click.option(
    "--notify",
    is_flag=True,
    help="Send desktop notification when drift exceeds threshold.",
)
@click.pass_context
def cmd_watch(
    ctx: click.Context,
    against: str,
    interval: float,
    min_runs: int,
    last: int,
    environment: str | None,
    threshold: float,
    notify: bool,
) -> None:
    """
    Live drift monitor against a baseline version.

    \b
    Examples:
      driftbase watch -a v2.0                    # Monitor v2.0
      driftbase watch -a v2.0 -t 0.15            # Custom threshold
      driftbase watch -a v2.0 -i 10 --min-runs 20  # Poll every 10s, 20 min runs
      driftbase watch -a v2.0 --notify           # Send desktop notifications
    """
    from driftbase.cli.cli_diff import run_watch

    console: Console = ctx.obj["console"]
    use_color = not console.no_color
    run_watch(
        against,
        interval_seconds=interval,
        min_runs=min_runs,
        last_n=last,
        environment=environment,
        threshold=threshold,
        use_color=use_color,
        console=console,
        notify=notify,
    )


# Command aliases for familiar shortcuts (added after all commands are defined)
cli.add_command(cmd_inspect, name="cat")  # driftbase cat <run_id> = driftbase inspect
cli.add_command(cmd_tail, name="log")  # driftbase log = driftbase tail
cli.add_command(cmd_prune, name="clean")  # driftbase clean = driftbase prune


def main() -> int:
    """Entry point for the driftbase script."""
    cli(obj={})
    return 0


if __name__ == "__main__":
    sys.exit(main())
