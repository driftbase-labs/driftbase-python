"""
Chart command: Visual charts in terminal for metrics visualization.
"""

from __future__ import annotations

from collections import Counter

import click

from driftbase.backends.factory import get_backend


def _safe_import_rich():
    try:
        from rich.console import Console
        from rich.table import Table

        return Console, Table
    except ImportError:
        return None, None


def _create_histogram(values: list[int], bins: int = 20, width: int = 40) -> list[str]:
    """Create ASCII histogram from values."""
    if not values:
        return ["No data"]

    # Create bins
    min_val = min(values)
    max_val = max(values)
    if min_val == max_val:
        return [f"All values are {min_val}"]

    bin_size = (max_val - min_val) / bins
    bin_counts = [0] * bins

    for val in values:
        bin_idx = int((val - min_val) / bin_size)
        if bin_idx >= bins:
            bin_idx = bins - 1
        bin_counts[bin_idx] += 1

    max_count = max(bin_counts)
    lines = []

    # Create histogram bars
    for i, count in enumerate(bin_counts):
        bin_start = min_val + i * bin_size
        bin_end = bin_start + bin_size

        if count > 0:
            bar_length = int((count / max_count) * width)
            bar = "█" * bar_length
            label = f"{int(bin_start):5d}-{int(bin_end):5d}ms"
            count_str = f"({count:3d})"
            lines.append(f"{label} │ {bar} {count_str}")

    return lines


def _create_bar_chart(data: dict[str, int], width: int = 40) -> list[str]:
    """Create ASCII bar chart from labeled data."""
    if not data:
        return ["No data"]

    max_val = max(data.values())
    lines = []

    for label, value in sorted(data.items(), key=lambda x: -x[1]):
        bar_length = int((value / max_val) * width)
        bar = "█" * bar_length
        pct = (value / sum(data.values())) * 100
        lines.append(f"{label:15s} │ {bar} {value:4d} ({pct:4.1f}%)")

    return lines


@click.command(name="chart")
@click.option(
    "--version",
    "-v",
    required=True,
    help="Deployment version to visualize.",
)
@click.option(
    "--metric",
    "-m",
    type=click.Choice(["latency", "outcomes", "tools", "errors"]),
    default="latency",
    help="Metric to visualize (default: latency).",
)
@click.option(
    "--limit",
    "-n",
    type=int,
    default=1000,
    help="Maximum runs to include (default 1000).",
)
@click.pass_context
def cmd_chart(
    ctx: click.Context,
    version: str,
    metric: str,
    limit: int,
) -> None:
    """
    Display terminal charts for run metrics.

    \b
    Examples:
      driftbase chart -v v2.0 -m latency    # Latency distribution
      driftbase chart -v v2.0 -m outcomes   # Outcome breakdown
      driftbase chart -v v2.0 -m tools      # Tool usage frequency
      driftbase chart -v v2.0 -m errors     # Error distribution
    """
    Console, Table = _safe_import_rich()
    console = ctx.obj.get("console") if Console else None

    if not console:
        console = type("PlainConsole", (), {"print": lambda self, x: print(x)})()

    try:
        backend = get_backend()
        runs = backend.get_runs(deployment_version=version, limit=limit)
    except Exception as e:
        console.print(f"[red]Error:[/] {e}")
        ctx.exit(1)

    if not runs:
        console.print(f"[yellow]No runs found for version {version}[/]")
        ctx.exit(0)

    # Generate chart based on metric
    if metric == "latency":
        latencies = [r.get("latency_ms", 0) for r in runs]
        latencies = [l for l in latencies if l > 0]  # Filter zeros

        if not latencies:
            console.print("[yellow]No latency data available[/]")
            ctx.exit(0)

        # Calculate statistics
        latencies_sorted = sorted(latencies)
        p50 = latencies_sorted[len(latencies) // 2]
        p95 = latencies_sorted[int(len(latencies) * 0.95)]
        avg = sum(latencies) // len(latencies)

        console.print(f"\n[bold cyan]Latency Distribution[/] ({version}, {len(runs)} runs)\n")

        # Create histogram
        lines = _create_histogram(latencies, bins=15, width=50)
        for line in lines:
            console.print(line)

        console.print(
            f"\n[dim]Stats:[/] avg={avg}ms, p50={p50}ms, p95={p95}ms, min={min(latencies)}ms, max={max(latencies)}ms\n"
        )

    elif metric == "outcomes":
        outcomes = Counter(r.get("semantic_cluster", "unknown") for r in runs)

        console.print(f"\n[bold cyan]Outcome Distribution[/] ({version}, {len(runs)} runs)\n")

        # Create bar chart
        lines = _create_bar_chart(dict(outcomes), width=50)
        for line in lines:
            console.print(line)

        console.print(f"\n[dim]Total: {sum(outcomes.values())} runs[/]\n")

    elif metric == "tools":
        import json

        tool_counts = Counter()
        for r in runs:
            tools_str = r.get("tool_sequence", "[]")
            try:
                tools = json.loads(tools_str)
                for tool in tools:
                    tool_counts[tool] += 1
            except Exception:
                pass

        if not tool_counts:
            console.print("[yellow]No tool usage data available[/]")
            ctx.exit(0)

        console.print(f"\n[bold cyan]Tool Usage Frequency[/] ({version}, {len(runs)} runs)\n")

        # Show top 15 tools
        top_tools = dict(tool_counts.most_common(15))
        lines = _create_bar_chart(top_tools, width=50)
        for line in lines:
            console.print(line)

        console.print(f"\n[dim]Total tool calls: {sum(tool_counts.values())}[/]\n")

    elif metric == "errors":
        error_counts = Counter(r.get("error_count", 0) for r in runs)

        console.print(f"\n[bold cyan]Error Count Distribution[/] ({version}, {len(runs)} runs)\n")

        # Create bar chart
        error_data = {f"{k} errors": v for k, v in sorted(error_counts.items())}
        lines = _create_bar_chart(error_data, width=50)
        for line in lines:
            console.print(line)

        total_errors = sum(k * v for k, v in error_counts.items())
        console.print(
            f"\n[dim]Total errors: {total_errors}, Error rate: {(sum(v for k,v in error_counts.items() if k > 0) / len(runs) * 100):.1f}%[/]\n"
        )

    ctx.exit(0)
