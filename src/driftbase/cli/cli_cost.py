"""
Cost command: Enhanced cost tracking and budget analysis.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta

import click

from driftbase.backends.factory import get_backend


def _safe_import_rich():
    try:
        from rich.console import Console
        from rich.panel import Panel
        from rich.table import Table

        return Console, Panel, Table
    except ImportError:
        return None, None, None


def _parse_cost(run: dict) -> float:
    """Extract cost from run dict (in USD cents)."""
    cost_str = run.get("cost_usd_cents", "0")
    try:
        return float(cost_str) if cost_str else 0.0
    except (ValueError, TypeError):
        return 0.0


def _parse_provider(run: dict) -> str:
    """Extract provider from run (based on model_id or other fields)."""
    model_id = run.get("model_id", "")
    if not model_id:
        return "unknown"

    # Detect provider from model ID patterns
    if "gpt" in model_id.lower() or "openai" in model_id.lower():
        return "OpenAI"
    elif "claude" in model_id.lower() or "anthropic" in model_id.lower():
        return "Anthropic"
    elif "gemini" in model_id.lower() or "google" in model_id.lower():
        return "Google"
    elif "llama" in model_id.lower() or "meta" in model_id.lower():
        return "Meta"
    else:
        return "Other"


@click.command(name="cost")
@click.option(
    "--version",
    "-v",
    help="Deployment version to analyze.",
)
@click.option(
    "--environment",
    "-e",
    help="Filter by environment.",
)
@click.option(
    "--since",
    metavar="DURATION",
    help="Analyze costs since duration (e.g., 24h, 7d, 30d).",
)
@click.option(
    "--groupby",
    type=click.Choice(["version", "outcome", "provider", "day"]),
    default="version",
    help="Group costs by dimension (default: version).",
)
@click.option(
    "--budget",
    type=float,
    metavar="USD",
    help="Monthly budget in USD (shows burn rate and forecast).",
)
@click.option(
    "--format",
    "-f",
    type=click.Choice(["table", "json"]),
    default="table",
    help="Output format.",
)
@click.option(
    "--limit",
    "-n",
    type=int,
    default=10000,
    help="Maximum runs to analyze (default 10000).",
)
@click.pass_context
def cmd_cost(
    ctx: click.Context,
    version: str | None,
    environment: str | None,
    since: str | None,
    groupby: str,
    budget: float | None,
    format: str,
    limit: int,
):
    """
    Analyze costs with detailed breakdown and forecasting.

    Provides comprehensive cost analysis including:
    - Total costs and breakdown by version/outcome/provider
    - Cost trends over time
    - Budget tracking and burn rate
    - Cost per 1000 runs and other metrics

    Examples:
        driftbase cost                          # Overall cost summary
        driftbase cost -v v2.0                  # Costs for specific version
        driftbase cost --since 7d               # Last 7 days
        driftbase cost --groupby provider       # Group by provider
        driftbase cost --budget 100             # Track against $100/month budget
        driftbase cost --format json            # JSON output
    """
    Console, Panel, Table = _safe_import_rich()
    console = ctx.obj.get("console") if Console else None

    if not console:
        console = type("PlainConsole", (), {"print": lambda self, x: print(x)})()

    # Parse time filter
    since_hours = None
    if since:
        import re

        match = re.match(r"^(\d+)([hd])$", since.lower())
        if match:
            value, unit = match.groups()
            since_hours = int(value) if unit == "h" else int(value) * 24

    try:
        backend = get_backend()
    except Exception as e:
        console.print(f"[red]Error:[/] {e}")
        ctx.exit(1)

    # Fetch runs
    runs = backend.get_runs(
        deployment_version=version,
        environment=environment,
        limit=limit,
    )

    if not runs:
        console.print("[yellow]No runs found[/]")
        ctx.exit(0)

    # Filter by time if needed
    if since_hours:
        cutoff = datetime.utcnow() - timedelta(hours=since_hours)
        runs = [
            r
            for r in runs
            if r.get("started_at")
            and datetime.fromisoformat(str(r["started_at"]).replace("Z", "+00:00"))
            >= cutoff
        ]

    if not runs:
        console.print(f"[yellow]No runs found in last {since}[/]")
        ctx.exit(0)

    # Calculate costs
    total_cost_cents = sum(_parse_cost(r) for r in runs)
    total_cost_usd = total_cost_cents / 100.0

    # Group by dimension
    grouped_costs: dict[str, float] = defaultdict(float)

    for run in runs:
        cost = _parse_cost(run)

        if groupby == "version":
            key = run.get("deployment_version", "unknown")
        elif groupby == "outcome":
            key = run.get("semantic_cluster", "unknown")
        elif groupby == "provider":
            key = _parse_provider(run)
        elif groupby == "day":
            started_at = run.get("started_at")
            if started_at:
                try:
                    dt = datetime.fromisoformat(str(started_at).replace("Z", "+00:00"))
                    key = dt.strftime("%Y-%m-%d")
                except Exception:
                    key = "unknown"
            else:
                key = "unknown"
        else:
            key = "unknown"

        grouped_costs[key] += cost

    # Convert to USD
    grouped_costs_usd = {k: v / 100.0 for k, v in grouped_costs.items()}

    # JSON output
    if format == "json":
        output = {
            "schema_version": "1.0",
            "total_runs": len(runs),
            "total_cost_usd": total_cost_usd,
            "cost_per_1k_runs": (total_cost_usd / len(runs) * 1000) if runs else 0,
            "groupby": groupby,
            "breakdown": grouped_costs_usd,
        }

        if budget:
            # Calculate budget metrics
            if since_hours:
                days_analyzed = since_hours / 24.0
                daily_cost = total_cost_usd / days_analyzed if days_analyzed > 0 else 0
                monthly_projection = daily_cost * 30
                budget_remaining = budget - monthly_projection
                days_until_depleted = (
                    budget / daily_cost if daily_cost > 0 else float("inf")
                )

                output["budget_analysis"] = {
                    "monthly_budget_usd": budget,
                    "monthly_projection_usd": monthly_projection,
                    "budget_remaining_usd": budget_remaining,
                    "burn_rate_usd_per_day": daily_cost,
                    "days_until_depleted": (
                        days_until_depleted if days_until_depleted != float("inf") else None
                    ),
                }

        console.print(json.dumps(output, indent=2))
        ctx.exit(0)

    # Table output
    console.print(f"\n[bold cyan]💰 Cost Analysis[/]")
    console.print(f"[dim]Analyzing {len(runs)} runs{f' for {version}' if version else ''}[/]\n")

    # Summary panel
    summary_lines = [
        f"Total cost:       [bold]${total_cost_usd:.2f}[/]",
        f"Total runs:       {len(runs):,}",
        f"Cost per run:     ${total_cost_usd / len(runs):.4f}" if runs else "N/A",
        f"Cost per 1K runs: ${total_cost_usd / len(runs) * 1000:.2f}" if runs else "N/A",
    ]

    if since:
        summary_lines.append(f"Time period:      Last {since}")

    if Panel:
        summary_panel = Panel(
            "\n".join(summary_lines),
            title="[bold cyan]Summary[/]",
            border_style="cyan",
        )
        console.print(summary_panel)
        console.print()
    else:
        print("\nSummary:")
        for line in summary_lines:
            print(f"  {line}")
        print()

    # Breakdown table
    if Table:
        table = Table(show_header=True, header_style="bold")
        table.add_column(groupby.capitalize(), style="cyan")
        table.add_column("Runs", justify="right")
        table.add_column("Cost (USD)", justify="right")
        table.add_column("% of Total", justify="right")
        table.add_column("Cost/Run", justify="right")

        # Count runs per group
        run_counts = Counter()
        for run in runs:
            if groupby == "version":
                key = run.get("deployment_version", "unknown")
            elif groupby == "outcome":
                key = run.get("semantic_cluster", "unknown")
            elif groupby == "provider":
                key = _parse_provider(run)
            elif groupby == "day":
                started_at = run.get("started_at")
                if started_at:
                    try:
                        dt = datetime.fromisoformat(str(started_at).replace("Z", "+00:00"))
                        key = dt.strftime("%Y-%m-%d")
                    except Exception:
                        key = "unknown"
                else:
                    key = "unknown"
            else:
                key = "unknown"
            run_counts[key] += 1

        # Sort by cost descending
        sorted_items = sorted(
            grouped_costs_usd.items(), key=lambda x: x[1], reverse=True
        )

        for key, cost in sorted_items:
            count = run_counts[key]
            pct = (cost / total_cost_usd * 100) if total_cost_usd > 0 else 0
            cost_per_run = cost / count if count > 0 else 0

            table.add_row(
                key,
                f"{count:,}",
                f"${cost:.2f}",
                f"{pct:.1f}%",
                f"${cost_per_run:.4f}",
            )

        console.print(table)
        console.print()
    else:
        print(f"\nBreakdown by {groupby}:")
        sorted_items = sorted(
            grouped_costs_usd.items(), key=lambda x: x[1], reverse=True
        )
        for key, cost in sorted_items:
            pct = (cost / total_cost_usd * 100) if total_cost_usd > 0 else 0
            print(f"  {key:20s} ${cost:8.2f} ({pct:5.1f}%)")
        print()

    # Budget analysis
    if budget:
        if not since_hours:
            console.print(
                "[yellow]⚠[/] Budget tracking requires --since flag to calculate burn rate"
            )
            console.print("  Example: driftbase cost --budget 100 --since 7d")
        else:
            days_analyzed = since_hours / 24.0
            daily_cost = total_cost_usd / days_analyzed if days_analyzed > 0 else 0
            monthly_projection = daily_cost * 30
            budget_remaining = budget - monthly_projection
            burn_rate_pct = (monthly_projection / budget * 100) if budget > 0 else 0

            days_until_depleted = budget / daily_cost if daily_cost > 0 else float("inf")

            budget_lines = [
                f"Monthly budget:     ${budget:.2f}",
                f"Burn rate:          ${daily_cost:.2f}/day",
                f"Monthly projection: ${monthly_projection:.2f} ({burn_rate_pct:.1f}% of budget)",
                f"Budget remaining:   ${budget_remaining:.2f}",
            ]

            if days_until_depleted != float("inf"):
                budget_lines.append(
                    f"Days until depleted: {days_until_depleted:.1f} days"
                )

            # Color code based on burn rate
            if burn_rate_pct > 100:
                style = "red"
                status = "⚠️ OVER BUDGET"
            elif burn_rate_pct > 80:
                style = "yellow"
                status = "⚠ WARNING"
            else:
                style = "green"
                status = "✓ ON TRACK"

            if Panel:
                budget_panel = Panel(
                    "\n".join(budget_lines),
                    title=f"[bold {style}]Budget Analysis - {status}[/]",
                    border_style=style,
                )
                console.print(budget_panel)
                console.print()
            else:
                print(f"\nBudget Analysis - {status}:")
                for line in budget_lines:
                    print(f"  {line}")
                print()

    ctx.exit(0)
