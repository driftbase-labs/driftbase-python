"""
CLI command: driftbase explain

Displays detailed breakdown of a drift verdict with evidence.
"""

from __future__ import annotations

import json
import logging

import click
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from driftbase.backends.factory import get_backend
from driftbase.output.evidence import generate_evidence

logger = logging.getLogger(__name__)


@click.command("explain")
@click.argument("verdict_id", required=False)
@click.pass_context
def cmd_explain(ctx: click.Context, verdict_id: str | None) -> None:
    """
    Explain a drift verdict in detail.

    Shows top contributors, evidence, confidence intervals, and MDEs.

    If VERDICT_ID is provided, explains that specific verdict.
    If omitted, explains the most recent verdict.

    Examples:
        driftbase explain
        driftbase explain abc-123-def
    """
    console: Console = ctx.obj["console"]
    backend = get_backend()

    # Load verdict
    if verdict_id:
        verdict_dict = backend.get_verdict(verdict_id)
        if verdict_dict is None:
            console.print(f"[red]Verdict {escape(verdict_id)} not found.[/red]")
            ctx.exit(1)
    else:
        verdicts = backend.list_verdicts(limit=1)
        if not verdicts:
            console.print(
                "[yellow]No verdict history found.[/yellow]\n"
                "Run [bold]driftbase diff[/bold] first to generate a verdict."
            )
            ctx.exit(0)
        verdict_dict = verdicts[0]

    # Parse report JSON
    try:
        report_data = json.loads(verdict_dict["report_json"])
    except (json.JSONDecodeError, KeyError) as e:
        console.print(f"[red]Failed to parse verdict report: {e}[/red]")
        ctx.exit(1)

    # Extract key fields
    baseline_version = verdict_dict.get("baseline_version", "unknown")
    current_version = verdict_dict.get("current_version", "unknown")
    verdict = verdict_dict.get("verdict") or "NONE"
    composite_score = verdict_dict.get("composite_score", 0.0)
    confidence_tier = verdict_dict.get("confidence_tier", "TIER3")
    severity = verdict_dict.get("severity", "none")

    # Get CIs, attribution, MDEs from report
    drift_score_lower = report_data.get("drift_score_lower", composite_score)
    drift_score_upper = report_data.get("drift_score_upper", composite_score)
    attribution = report_data.get("dimension_attribution", {})
    dimension_cis = report_data.get("dimension_cis", {})
    dimension_mdes = report_data.get("dimension_mdes", {})
    dimension_scores = _extract_dimension_scores(report_data)

    # Build header panel
    header_text = (
        f"[bold]Drift Report:[/bold] {escape(baseline_version)} → {escape(current_version)}\n"
        f"[bold]Verdict:[/bold] {_verdict_color(verdict)}\n"
        f"[bold]Composite Score:[/bold] {composite_score:.3f} "
        f"(CI: {drift_score_lower:.3f}–{drift_score_upper:.3f})\n"
        f"[bold]Severity:[/bold] {escape(severity)} │ "
        f"[bold]Confidence:[/bold] {escape(confidence_tier)}"
    )
    console.print(Panel(header_text, border_style="cyan", expand=False))
    console.print()

    # Top contributors
    if not attribution:
        console.print("[yellow]No attribution data available.[/yellow]")
        ctx.exit(0)

    # Sort by absolute attribution
    sorted_dims = sorted(attribution.items(), key=lambda x: abs(x[1]), reverse=True)
    top_3 = sorted_dims[:3]

    console.print("[bold]Top Contributors[/bold]")
    console.print("─" * 60)
    console.print()

    total_attribution = sum(abs(v) for v in attribution.values())

    for dim, attr_value in top_3:
        observed = dimension_scores.get(dim, 0.0)

        # Get CI data
        ci_data = dimension_cis.get(dim, {})
        if isinstance(ci_data, dict):
            ci_lower = ci_data.get("ci_lower", observed)
            ci_upper = ci_data.get("ci_upper", observed)
            significant = ci_data.get("significant", False)
        else:
            ci_lower = observed
            ci_upper = observed
            significant = False

        # Contribution percentage
        contribution_pct = 0.0
        if total_attribution > 0:
            contribution_pct = (abs(attr_value) / total_attribution) * 100

        # MDE
        mde = dimension_mdes.get(dim)
        mde_str = f"{mde:.3f}" if mde is not None else "N/A"

        # Build output
        sig_marker = " ■ significant" if significant else ""
        dim_line = (
            f"[bold cyan]{escape(dim)}:[/bold cyan] {observed:.3f} "
            f"(CI: {ci_lower:.3f}–{ci_upper:.3f}){sig_marker}"
        )
        console.print(dim_line)

        # Evidence (generic for now, will use fingerprints in full impl)
        evidence_str = f"Observed drift of {observed:.3f}"
        console.print(f"  → {escape(evidence_str)}")

        # Contribution + MDE
        console.print(
            f"  [dim]Contribution: {contribution_pct:.1f}% │ MDE: {mde_str}[/dim]"
        )
        console.print()

    # Show MDE table for all dimensions with data
    if dimension_mdes:
        console.print()
        console.print("[bold]Minimum Detectable Effects (MDEs)[/bold]")
        console.print("─" * 60)

        mde_table = Table(show_header=True, header_style="bold")
        mde_table.add_column("Dimension", style="cyan")
        mde_table.add_column("Observed", justify="right")
        mde_table.add_column("MDE", justify="right")
        mde_table.add_column("Status", justify="center")

        for dim in sorted(dimension_mdes.keys()):
            mde = dimension_mdes[dim]
            observed = dimension_scores.get(dim, 0.0)

            # Detectability status
            if observed >= mde:
                status = "[green]✓ Detectable[/green]"
            else:
                status = "[yellow]⚠ Below MDE[/yellow]"

            mde_table.add_row(
                escape(dim),
                f"{observed:.3f}",
                f"{mde:.3f}",
                status,
            )

        console.print(mde_table)


def _verdict_color(verdict: str) -> str:
    """Add color to verdict string."""
    colors = {
        "SHIP": "[green]SHIP[/green]",
        "MONITOR": "[yellow]MONITOR[/yellow]",
        "REVIEW": "[orange1]REVIEW[/orange1]",
        "BLOCK": "[red]BLOCK[/red]",
    }
    return colors.get(verdict, f"[dim]{escape(verdict)}[/dim]")


def _extract_dimension_scores(report_data: dict) -> dict[str, float]:
    """Extract dimension scores from report JSON."""
    return {
        "decision_drift": report_data.get("decision_drift", 0.0),
        "semantic_drift": report_data.get("semantic_drift", 0.0),
        "latency": report_data.get("latency_drift", 0.0),
        "error_rate": report_data.get("error_drift", 0.0),
        "tool_distribution": report_data.get("decision_drift", 0.0),
        "verbosity_ratio": report_data.get("verbosity_drift", 0.0),
        "loop_depth": report_data.get("loop_depth_drift", 0.0),
        "output_length": report_data.get("output_length_drift", 0.0),
        "tool_sequence": report_data.get("tool_sequence_drift", 0.0),
        "retry_rate": report_data.get("retry_drift", 0.0),
        "time_to_first_tool": report_data.get("planning_latency_drift", 0.0),
        "tool_sequence_transitions": report_data.get(
            "tool_sequence_transitions_drift", 0.0
        ),
    }
