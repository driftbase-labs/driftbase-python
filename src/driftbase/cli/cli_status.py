"""
Status command: Quick dashboard of key metrics and system health.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import click

from driftbase.backends.factory import get_backend
from driftbase.config import get_settings
from driftbase.pricing import calculate_cost_per_10k


def _safe_import_rich():
    try:
        from rich.console import Console
        from rich.panel import Panel
        from rich.table import Table

        return Console, Panel, Table
    except ImportError:
        return None, None, None


def _format_time_ago(dt: datetime) -> str:
    """Format datetime as 'Xh ago', 'Xd ago', etc."""
    if not dt:
        return "unknown"

    now = datetime.utcnow()
    delta = now - dt

    if delta.total_seconds() < 60:
        return "just now"
    elif delta.total_seconds() < 3600:
        mins = int(delta.total_seconds() / 60)
        return f"{mins}m ago"
    elif delta.total_seconds() < 86400:
        hours = int(delta.total_seconds() / 3600)
        return f"{hours}h ago"
    else:
        days = int(delta.total_seconds() / 86400)
        return f"{days}d ago"


def _drift_indicator(score: float, threshold: float = 0.20) -> str:
    """Return colored indicator for drift score."""
    if score < threshold * 0.5:
        return f"🟢 {score:.2f}"
    elif score < threshold:
        return f"🟡 {score:.2f}"
    else:
        return f"🔴 {score:.2f}"


@click.command(name="status")
@click.pass_context
def cmd_status(ctx: click.Context) -> None:
    """
    Quick dashboard of key metrics and system health.

    Shows latest version, baseline, drift score, today's statistics,
    recent versions, and database health.
    """
    Console, Panel, Table = _safe_import_rich()
    console = ctx.obj.get("console") if Console else None

    if not console:
        # Fallback to plain text if Rich not available
        console = type("PlainConsole", (), {"print": lambda self, x: print(x)})()

    try:
        backend = get_backend()
        settings = get_settings()
    except Exception as e:
        console.print(f"#FF6B6B]Error:[/] Failed to connect to backend: {e}")
        ctx.exit(1)

    # Get database stats
    try:
        db_stats = backend.get_db_stats()
        total_runs = db_stats.get("total_runs", 0)
        versions_list = db_stats.get("versions", [])
        disk_size_mb = db_stats.get("disk_size_mb", 0)
        newest_run_dt = db_stats.get("newest_run")
    except Exception:
        total_runs = 0
        versions_list = []
        disk_size_mb = 0
        newest_run_dt = None

    # Get latest version
    latest_version = None
    latest_count = 0
    if versions_list:
        latest_version = versions_list[0]["version"]
        latest_count = versions_list[0]["count"]

    # Get baseline from config
    baseline_version = settings.DRIFTBASE_BASELINE_VERSION

    # Compute drift vs baseline if both exist
    drift_score = None
    drift_status = "N/A"
    threshold = settings.DRIFTBASE_DRIFT_THRESHOLD

    if latest_version and baseline_version and latest_version != baseline_version:
        try:
            from driftbase.local.diff import compute_drift
            from driftbase.local.fingerprinter import build_fingerprint_from_runs
            from driftbase.local.local_store import run_dict_to_agent_run

            baseline_runs = backend.get_runs(
                deployment_version=baseline_version, limit=1000
            )
            current_runs = backend.get_runs(
                deployment_version=latest_version, limit=1000
            )

            if len(baseline_runs) >= 10 and len(current_runs) >= 10:
                baseline_fp = build_fingerprint_from_runs(
                    [run_dict_to_agent_run(r) for r in baseline_runs]
                )
                current_fp = build_fingerprint_from_runs(
                    [run_dict_to_agent_run(r) for r in current_runs]
                )
                drift_report = compute_drift(baseline_fp, current_fp)
                drift_score = drift_report.drift_score
                drift_status = _drift_indicator(drift_score, threshold)
        except Exception:
            drift_status = "Unable to compute"

    # Get today's stats
    today_runs = []
    try:
        if hasattr(backend, "get_runs_filtered"):
            today_runs = backend.get_runs_filtered(since_hours=24, limit=10000)
        else:
            # Fallback: get all recent runs and filter
            all_runs = backend.get_runs(limit=10000)
            cutoff = datetime.utcnow() - timedelta(hours=24)
            today_runs = [
                r for r in all_runs if r.get("started_at") and r["started_at"] >= cutoff
            ]
    except Exception:
        today_runs = []

    today_count = len(today_runs)
    today_errors = sum(1 for r in today_runs if r.get("error_count", 0) > 0)
    today_error_rate = (today_errors / today_count * 100) if today_count > 0 else 0

    today_latencies = [
        r.get("latency_ms", 0) for r in today_runs if r.get("latency_ms")
    ]
    avg_latency = sum(today_latencies) // len(today_latencies) if today_latencies else 0

    cost_per_10k = calculate_cost_per_10k(today_runs) if today_runs else 0

    # Build output
    if Panel:
        lines = []
        lines.append("[bold cyan]📊 Driftbase Status[/]")
        lines.append("")

        # Latest version
        if latest_version:
            time_ago = _format_time_ago(newest_run_dt) if newest_run_dt else "unknown"
            lines.append(
                f"[bold]Latest version:[/]        {latest_version} ({latest_count} runs, {time_ago})"
            )
        else:
            lines.append("[bold]Latest version:[/]        [dim]No data yet[/]")

        # Baseline
        if baseline_version:
            lines.append(
                f"[bold]Baseline:[/]              {baseline_version} (from config)"
            )
        else:
            lines.append("[bold]Baseline:[/]              [dim]Not set[/]")

        # Drift
        lines.append(f"[bold]Drift vs baseline:[/]     {drift_status}")

        lines.append("")
        lines.append("[bold]Today's stats:[/]")
        lines.append(f"  Runs:                {today_count}")

        if today_count > 0:
            error_color = (
                "red"
                if today_error_rate > 5
                else "yellow"
                if today_error_rate > 1
                else "green"
            )
            lines.append(
                f"  Error rate:          [{error_color}]{today_error_rate:.1f}%[/] ({today_errors} errors)"
            )
            lines.append(f"  Avg latency:         {avg_latency}ms")
            lines.append(f"  Cost per 10k:        €{cost_per_10k:.2f}")

        lines.append("")
        # Recent versions
        if versions_list:
            recent = ", ".join([v["version"] for v in versions_list[:5]])
            lines.append(f"[bold]Recent versions:[/]       {recent}")

        # Database
        lines.append(
            f"[bold]Database size:[/]         {disk_size_mb:.2f} MB ({total_runs:,} runs)"
        )

        panel = Panel("\n".join(lines), border_style="#8B5CF6", padding=(1, 2))
        console.print("\n")
        console.print(panel)
        console.print("\n")

        # Suggestions
        if not baseline_version:
            console.print(
                "💡 [dim]Tip: Set a baseline with[/] #8B5CF6]driftbase baseline set <version>[/]"
            )
        if total_runs == 0:
            console.print(
                "💡 [dim]Tip: No runs yet. Try[/] #8B5CF6]driftbase demo[/] [dim]to generate sample data[/]"
            )

    else:
        # Plain text fallback
        print("\n📊 Driftbase Status\n")
        print("━" * 50)
        if latest_version:
            time_ago = _format_time_ago(newest_run_dt) if newest_run_dt else "unknown"
            print(
                f"Latest version:        {latest_version} ({latest_count} runs, {time_ago})"
            )
        else:
            print("Latest version:        No data yet")

        if baseline_version:
            print(f"Baseline:              {baseline_version} (from config)")
        else:
            print("Baseline:              Not set")

        print(f"Drift vs baseline:     {drift_status}")

        print("\nToday's stats:")
        print(f"  Runs:                {today_count}")
        if today_count > 0:
            print(
                f"  Error rate:          {today_error_rate:.1f}% ({today_errors} errors)"
            )
            print(f"  Avg latency:         {avg_latency}ms")
            print(f"  Cost per 10k:        €{cost_per_10k:.2f}")

        if versions_list:
            recent = ", ".join([v["version"] for v in versions_list[:5]])
            print(f"\nRecent versions:       {recent}")

        print(f"Database size:         {disk_size_mb:.2f} MB ({total_runs:,} runs)")
        print()

    ctx.exit(0)
