"""
Diagnose command for debugging and understanding drift patterns.
Provides actionable insights and root cause analysis.
"""

import json
from typing import Any

import click

from driftbase.backends.factory import get_backend
from driftbase.cli._deps import safe_import_rich_extended
from driftbase.cli.demo_templates import INDUSTRY_BENCHMARKS, REGRESSION_TYPES

Console, Panel, Table, Markdown, Prompt, Confirm = safe_import_rich_extended()


def _calculate_metrics(runs: list[dict[str, Any]]) -> dict[str, float]:
    """Calculate aggregate metrics from runs."""
    if not runs:
        return {}

    total = len(runs)
    return {
        "avg_latency": sum(r.get("latency_ms", 0) for r in runs) / total,
        "p95_latency": sorted([r.get("latency_ms", 0) for r in runs])[int(total * 0.95)]
        if total > 1
        else 0,
        "avg_prompt_tokens": sum(r.get("prompt_tokens", 0) for r in runs) / total,
        "avg_completion_tokens": sum(r.get("completion_tokens", 0) for r in runs)
        / total,
        "avg_loop_count": sum(r.get("loop_count", 0) for r in runs) / total,
        "avg_retry_count": sum(r.get("retry_count", 0) for r in runs) / total,
        "error_rate": sum(1 for r in runs if r.get("error_count", 0) > 0) / total,
        "escalation_rate": sum(
            1 for r in runs if r.get("semantic_cluster") == "escalated"
        )
        / total,
        "avg_tool_count": sum(r.get("tool_call_count", 0) for r in runs) / total,
    }


def _detect_regression_type(
    baseline_metrics: dict[str, float], current_metrics: dict[str, float]
) -> list[tuple[str, float]]:
    """Detect which regression types match the observed pattern.

    Returns list of (regression_type, confidence_score) tuples.
    """
    matches = []

    # Token bloat detection
    prompt_increase = (
        current_metrics.get("avg_prompt_tokens", 0)
        - baseline_metrics.get("avg_prompt_tokens", 1)
    ) / baseline_metrics.get("avg_prompt_tokens", 1)
    completion_increase = (
        current_metrics.get("avg_completion_tokens", 0)
        - baseline_metrics.get("avg_completion_tokens", 1)
    ) / baseline_metrics.get("avg_completion_tokens", 1)

    if completion_increase > 1.5:  # >150% increase
        confidence = min(completion_increase / 3.0, 1.0)  # Cap at 100%
        matches.append(("token-bloat", confidence))

    # Loop detection
    loop_increase = (
        current_metrics.get("avg_loop_count", 0)
        - baseline_metrics.get("avg_loop_count", 1)
    ) / baseline_metrics.get("avg_loop_count", 1)
    retry_increase = (
        current_metrics.get("avg_retry_count", 0)
        - baseline_metrics.get("avg_retry_count", 0.5)
    ) / baseline_metrics.get("avg_retry_count", 0.5)

    if loop_increase > 2.0 or retry_increase > 3.0:
        confidence = min((loop_increase + retry_increase) / 8.0, 1.0)
        matches.append(("loop-detection", confidence))

    # Tool dropout (lower tool count but same outcomes)
    tool_decrease = (
        baseline_metrics.get("avg_tool_count", 1)
        - current_metrics.get("avg_tool_count", 0)
    ) / baseline_metrics.get("avg_tool_count", 1)

    if tool_decrease > 0.2:  # >20% fewer tools called
        confidence = min(tool_decrease / 0.4, 1.0)
        matches.append(("tool-dropout", confidence))

    # Cost explosion (combined token and latency increase)
    total_token_increase = prompt_increase + completion_increase

    if total_token_increase > 2.0:  # >200% combined
        confidence = min(total_token_increase / 4.0, 1.0)
        matches.append(("cost-explosion", confidence))

    # Latency creep
    latency_increase = (
        current_metrics.get("avg_latency", 0) - baseline_metrics.get("avg_latency", 1)
    ) / baseline_metrics.get("avg_latency", 1)

    if latency_increase > 2.0:  # >200% increase
        confidence = min(latency_increase / 4.0, 1.0)
        matches.append(("latency-creep", confidence))

    # Sort by confidence
    matches.sort(key=lambda x: x[1], reverse=True)

    return matches


def _compare_to_benchmark(
    metrics: dict[str, float], benchmark_name: str
) -> dict[str, str]:
    """Compare metrics to industry benchmarks."""
    if benchmark_name not in INDUSTRY_BENCHMARKS:
        return {}

    benchmark = INDUSTRY_BENCHMARKS[benchmark_name]["metrics"]
    comparison = {}

    for key, value in metrics.items():
        benchmark_key = key.replace("avg_", "")
        if benchmark_key in benchmark:
            bench_val = benchmark[benchmark_key]
            diff_pct = ((value - bench_val) / bench_val * 100) if bench_val > 0 else 0

            if abs(diff_pct) < 10:
                status = "✓ GOOD"
                color = "green"
            elif diff_pct < 50:
                status = "⚠ WATCH"
                color = "yellow"
            else:
                status = "❌ BAD"
                color = "red"

            comparison[key] = f"[{color}]{status}[/] ({diff_pct:+.0f}% vs benchmark)"

    return comparison


def _generate_recommendations(
    regression_matches: list[tuple[str, float]],
    baseline_metrics: dict[str, float],
    current_metrics: dict[str, float],
) -> list[str]:
    """Generate actionable recommendations based on detected patterns."""
    recommendations = []

    if not regression_matches:
        return ["✅ No significant regressions detected. Metrics look healthy!"]

    top_match = regression_matches[0]
    regression_type, confidence = top_match

    if regression_type == "token-bloat":
        recommendations.extend(
            [
                "🔍 Review prompt changes - are you providing unnecessary context?",
                "🔍 Check for verbose system messages or instructions",
                "🔍 Consider using a shorter output format",
                "💡 Benchmark: Use `driftbase compare v1.0 v2.0 --focus verbosity`",
            ]
        )

    elif regression_type == "loop-detection":
        recommendations.extend(
            [
                "🔍 Profile agent reasoning - look for retry loops",
                "🔍 Check tool error rates - are failed calls causing retries?",
                "🔍 Review exit conditions - is agent getting stuck?",
                "💡 Inspect slow runs: `driftbase runs -v current --slow --limit 10`",
            ]
        )

    elif regression_type == "tool-dropout":
        recommendations.extend(
            [
                "🔍 Compare tool sequences: `driftbase chart -v v1.0 -m tools` vs v2.0",
                "🔍 Check if critical tools were removed or renamed",
                "🔍 Review prompt changes that might skip tool usage",
                "💡 Look for missing validations or context retrieval steps",
            ]
        )

    elif regression_type == "cost-explosion":
        recommendations.extend(
            [
                "🔍 Audit entire tool chain - excessive chaining detected",
                "🔍 Check for redundant API calls or duplicate operations",
                "🔍 Consider caching frequently accessed data",
                "💡 Cost breakdown: `driftbase cost -v current --groupby tool`",
            ]
        )

    elif regression_type == "latency-creep":
        recommendations.extend(
            [
                "🔍 Profile slow operations - database queries? API calls?",
                "🔍 Check for network timeouts or slow external services",
                "🔍 Review parallelization opportunities",
                "💡 Analyze p95/p99 latency: `driftbase runs -v current --slow`",
            ]
        )

    # Generic recommendations based on metrics
    if current_metrics.get("error_rate", 0) > baseline_metrics.get("error_rate", 0) * 2:
        recommendations.append("⚠️ Error rate doubled - investigate error logs")

    if (
        current_metrics.get("escalation_rate", 0)
        > baseline_metrics.get("escalation_rate", 0) * 2
    ):
        recommendations.append(
            "⚠️ Escalation rate doubled - agent confidence may have decreased"
        )

    return recommendations


@click.command("diagnose")
@click.option(
    "--runs",
    "-r",
    metavar="VERSION",
    required=True,
    help="Version to diagnose",
)
@click.option(
    "--compare",
    "-c",
    metavar="VERSION",
    help="Baseline version to compare against",
)
@click.option(
    "--benchmark",
    type=click.Choice(list(INDUSTRY_BENCHMARKS.keys())),
    help="Compare to industry benchmark",
)
@click.option(
    "--limit",
    "-n",
    type=int,
    default=100,
    help="Number of runs to analyze (default: 100)",
)
@click.pass_context
def cmd_diagnose(
    ctx: click.Context,
    runs: str,
    compare: str | None,
    benchmark: str | None,
    limit: int,
) -> None:
    """Debug and understand behavioral drift with actionable insights.

    \b
    Examples:
      driftbase diagnose --runs v2.0 --compare v1.0
      driftbase diagnose --runs production --benchmark rag-pipeline
      driftbase diagnose --runs v2.0 --compare v1.0 --limit 200
    """
    console: Console = ctx.obj["console"]
    backend = get_backend()

    # Get runs for current version
    current_runs = backend.get_runs(runs, limit=limit)

    if not current_runs:
        console.print(f"[red]No runs found for version: {runs}[/]")
        return

    console.print(
        Panel(
            f"[bold]Version:[/] {runs}\n"
            f"[bold]Runs analyzed:[/] {len(current_runs)}\n"
            f"[bold]Time range:[/] {current_runs[-1].get('started_at')} → {current_runs[0].get('started_at')}",
            title="🔬 Drift Diagnostics",
            border_style="cyan",
        )
    )

    # Calculate metrics for current version
    current_metrics = _calculate_metrics(current_runs)

    # Display current metrics
    console.print("\n[bold]Current Metrics:[/]")
    metrics_table = Table(show_header=True, header_style="bold")
    metrics_table.add_column("Metric")
    metrics_table.add_column("Value", justify="right")

    metrics_table.add_row("Average Latency", f"{current_metrics['avg_latency']:.0f}ms")
    metrics_table.add_row("P95 Latency", f"{current_metrics['p95_latency']:.0f}ms")
    metrics_table.add_row(
        "Prompt Tokens (avg)", f"{current_metrics['avg_prompt_tokens']:.0f}"
    )
    metrics_table.add_row(
        "Completion Tokens (avg)", f"{current_metrics['avg_completion_tokens']:.0f}"
    )
    metrics_table.add_row(
        "Loop Count (avg)", f"{current_metrics['avg_loop_count']:.1f}"
    )
    metrics_table.add_row(
        "Retry Count (avg)", f"{current_metrics['avg_retry_count']:.1f}"
    )
    metrics_table.add_row("Error Rate", f"{current_metrics['error_rate']:.1%}")
    metrics_table.add_row(
        "Escalation Rate", f"{current_metrics['escalation_rate']:.1%}"
    )
    metrics_table.add_row(
        "Tool Calls (avg)", f"{current_metrics['avg_tool_count']:.1f}"
    )

    console.print(metrics_table)

    # Compare to baseline if provided
    if compare:
        baseline_runs = backend.get_runs(compare, limit=limit)

        if not baseline_runs:
            console.print(
                f"\n[yellow]Warning: No runs found for baseline version: {compare}[/]"
            )
        else:
            baseline_metrics = _calculate_metrics(baseline_runs)

            # Show comparison
            console.print(f"\n[bold]Comparison vs {compare}:[/]")
            comparison_table = Table(show_header=True, header_style="bold")
            comparison_table.add_column("Metric")
            comparison_table.add_column(compare, justify="right", style="green")
            comparison_table.add_column(runs, justify="right")
            comparison_table.add_column("Change", justify="right")

            for key in [
                "avg_latency",
                "avg_prompt_tokens",
                "avg_completion_tokens",
                "avg_loop_count",
                "avg_retry_count",
                "error_rate",
                "escalation_rate",
            ]:
                baseline_val = baseline_metrics[key]
                current_val = current_metrics[key]

                if "rate" in key:
                    baseline_str = f"{baseline_val:.1%}"
                    current_str = f"{current_val:.1%}"
                    change_pct = (
                        ((current_val - baseline_val) / baseline_val * 100)
                        if baseline_val > 0
                        else 0
                    )
                else:
                    baseline_str = f"{baseline_val:.0f}"
                    current_str = f"{current_val:.0f}"
                    change_pct = (
                        ((current_val - baseline_val) / baseline_val * 100)
                        if baseline_val > 0
                        else 0
                    )

                if abs(change_pct) < 10:
                    change_str = f"[green]{change_pct:+.0f}%[/]"
                elif change_pct < 50:
                    change_str = f"[yellow]{change_pct:+.0f}%[/]"
                else:
                    change_str = f"[red]{change_pct:+.0f}%[/]"

                comparison_table.add_row(
                    key.replace("avg_", "").replace("_", " ").title(),
                    baseline_str,
                    current_str,
                    change_str,
                )

            console.print(comparison_table)

            # Detect regression type
            regression_matches = _detect_regression_type(
                baseline_metrics, current_metrics
            )

            if regression_matches:
                console.print("\n[bold]Detected Regression Patterns:[/]")

                for reg_type, confidence in regression_matches[:3]:  # Top 3 matches
                    reg_info = REGRESSION_TYPES[reg_type]
                    confidence_pct = confidence * 100

                    if confidence >= 0.7:
                        color = "red"
                        icon = "🔴"
                    elif confidence >= 0.4:
                        color = "yellow"
                        icon = "🟡"
                    else:
                        color = "dim"
                        icon = "⚪"

                    console.print(
                        f"  {icon} [{color}]{reg_info['name']}[/] "
                        f"[dim]({confidence_pct:.0f}% match)[/]"
                    )
                    console.print(f"     [dim]{reg_info['description']}[/]")

            # Generate recommendations
            console.print("\n[bold]🎯 Recommendations:[/]")
            recommendations = _generate_recommendations(
                regression_matches, baseline_metrics, current_metrics
            )

            for rec in recommendations:
                console.print(f"  • {rec}")

    # Compare to industry benchmark if provided
    if benchmark:
        console.print(f"\n[bold]Comparison to Industry Benchmark: {benchmark}[/]")

        bench_info = INDUSTRY_BENCHMARKS[benchmark]
        console.print(f"[dim]{bench_info['description']}[/]\n")

        comparison = _compare_to_benchmark(current_metrics, benchmark)

        bench_table = Table(show_header=True, header_style="bold")
        bench_table.add_column("Metric")
        bench_table.add_column("Your Value", justify="right")
        bench_table.add_column("Status")

        for key, status in comparison.items():
            metric_name = key.replace("avg_", "").replace("_", " ").title()
            value = current_metrics[key]

            if "rate" in key:
                value_str = f"{value:.1%}"
            else:
                value_str = f"{value:.0f}"

            bench_table.add_row(metric_name, value_str, status)

        console.print(bench_table)

    # Tool usage analysis
    console.print("\n[bold]Tool Usage Analysis:[/]")

    tool_sequences = []
    for run in current_runs:
        seq = run.get("tool_sequence", "[]")
        try:
            tools = json.loads(seq) if isinstance(seq, str) else seq
            tool_sequences.extend(tools)
        except (json.JSONDecodeError, TypeError):
            pass

    if tool_sequences:
        from collections import Counter

        tool_counts = Counter(tool_sequences)
        most_common = tool_counts.most_common(10)

        tool_table = Table(show_header=True, header_style="bold")
        tool_table.add_column("Tool")
        tool_table.add_column("Calls", justify="right")
        tool_table.add_column("% of Total", justify="right")

        total_calls = sum(tool_counts.values())

        for tool, count in most_common:
            pct = (count / total_calls * 100) if total_calls > 0 else 0
            tool_table.add_row(str(tool), str(count), f"{pct:.1f}%")

        console.print(tool_table)

    console.print(
        "\n[dim]💡 For detailed drift analysis, run:[/] [cyan]driftbase diff {compare} {runs}[/]".format(
            compare=compare or "baseline",
            runs=runs,
        )
    )
