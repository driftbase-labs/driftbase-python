"""
CLI for feedback operations: dismiss, acknowledge, investigate verdicts.
"""

from __future__ import annotations

import logging
from typing import Any

import click

from driftbase.backends.factory import get_backend
from driftbase.cli._deps import safe_import_rich

logger = logging.getLogger(__name__)

Console, Panel, Table = safe_import_rich()


@click.command("feedback")
@click.argument("verdict_id", required=False)
@click.option(
    "--dismiss", is_flag=True, help="Dismiss this verdict (downweight dimensions)"
)
@click.option("--acknowledge", is_flag=True, help="Acknowledge this verdict")
@click.option("--investigate", is_flag=True, help="Mark for investigation")
@click.option("--reason", type=str, help="Explanation for this action")
@click.option(
    "--dimensions",
    type=str,
    help="Comma-separated dimension names to dismiss (e.g. 'latency_drift,error_rate')",
)
@click.option("--list", "list_mode", is_flag=True, help="List recent feedback records")
@click.option("--agent", type=str, help="Filter feedback by agent_id (with --list)")
@click.option(
    "--limit", type=int, default=20, help="Limit feedback records (with --list)"
)
@click.option("--impact", is_flag=True, help="Show weight adjustment impact")
@click.option("--reset", is_flag=True, help="Reset feedback for agent")
@click.option(
    "--confirm", is_flag=True, help="Confirm reset operation (required with --reset)"
)
@click.pass_context
def cmd_feedback(
    ctx: click.Context,
    verdict_id: str | None,
    dismiss: bool,
    acknowledge: bool,
    investigate: bool,
    reason: str | None,
    dimensions: str | None,
    list_mode: bool,
    agent: str | None,
    limit: int,
    impact: bool,
    reset: bool,
    confirm: bool,
) -> None:
    """Record feedback on drift verdicts to improve future detection."""
    console: Any = ctx.obj.get("console") or Console()
    backend = get_backend()

    # Handle --list mode
    if list_mode:
        _list_feedback(console, backend, agent, limit)
        return

    # Handle --impact mode
    if impact:
        if not verdict_id:
            console.print("[red]Error: agent_id required with --impact[/red]")
            raise click.UsageError("agent_id is required for --impact")
        _show_impact(console, backend, verdict_id)
        return

    # Handle --reset mode
    if reset:
        if not verdict_id:
            console.print("[red]Error: agent_id required with --reset[/red]")
            raise click.UsageError("agent_id is required for --reset")
        _reset_feedback(console, backend, verdict_id, confirm)
        return

    # Require verdict_id for non-list operations
    if not verdict_id:
        console.print("[red]Error: verdict_id required (or use --list)[/red]")
        raise click.UsageError("verdict_id is required for this operation")

    # Determine action
    action_flags = [dismiss, acknowledge, investigate]
    if sum(action_flags) == 0:
        console.print(
            "[red]Error: must specify --dismiss, --acknowledge, or --investigate[/red]"
        )
        raise click.UsageError(
            "One of --dismiss, --acknowledge, or --investigate is required"
        )
    if sum(action_flags) > 1:
        console.print("[red]Error: only one action allowed per feedback[/red]")
        raise click.UsageError(
            "Only one of --dismiss, --acknowledge, or --investigate allowed"
        )

    if dismiss:
        action = "dismiss"
    elif acknowledge:
        action = "acknowledge"
    else:
        action = "investigate"

    # Validate verdict exists
    verdict = backend.get_verdict(verdict_id)
    if not verdict:
        console.print(f"[red]Error: verdict {verdict_id} not found[/red]")
        return

    # Parse dismissed dimensions (only for dismiss action)
    dismissed_dims: list[str] | None = None
    if action == "dismiss" and dimensions:
        dismissed_dims = [d.strip() for d in dimensions.split(",") if d.strip()]

    # Extract agent_id from verdict
    # The verdict report_json contains the full DriftReport which should have agent info
    # For now, we'll use the session_id from runs as agent_id
    import json

    report_data = json.loads(verdict["report_json"])
    agent_id = report_data.get("baseline_session_id") or report_data.get(
        "current_session_id"
    )

    # Save feedback
    feedback_id = backend.save_feedback(
        verdict_id=verdict_id,
        action=action,
        agent_id=agent_id,
        reason=reason,
        dismissed_dimensions=dismissed_dims,
    )

    # Display confirmation
    console.print(
        Panel(
            f"[green]✓ Feedback recorded[/green]\n\n"
            f"Feedback ID: {feedback_id}\n"
            f"Verdict: {verdict['baseline_version']} → {verdict['current_version']}\n"
            f"Action: {action}\n"
            f"Agent: {agent_id or 'N/A'}\n"
            + (
                f"Dismissed dimensions: {', '.join(dismissed_dims)}\n"
                if dismissed_dims
                else ""
            )
            + (f"Reason: {reason}" if reason else ""),
            title=f"Feedback: {action}",
            border_style="green",
        )
    )


def _list_feedback(console: Any, backend: Any, agent: str | None, limit: int) -> None:
    """List feedback records."""
    if agent:
        feedback_list = backend.get_feedback_for_agent(agent)[:limit]
        title = f"Feedback for agent: {agent}"
    else:
        feedback_list = backend.list_feedback(limit=limit)
        title = "Recent feedback"

    if not feedback_list:
        console.print("[yellow]No feedback found[/yellow]")
        return

    table = Table(title=title)
    table.add_column("Verdict ID", style="cyan")
    table.add_column("Action", style="magenta")
    table.add_column("Agent", style="blue")
    table.add_column("Dismissed Dims", style="yellow")
    table.add_column("Created", style="dim")

    for f in feedback_list:
        dims_str = ""
        if f["dismissed_dimensions"]:
            dims_str = ", ".join(f["dismissed_dimensions"][:3])
            if len(f["dismissed_dimensions"]) > 3:
                dims_str += f" (+{len(f['dismissed_dimensions']) - 3})"

        table.add_row(
            f["verdict_id"][:8] + "...",
            f["action"],
            f["agent_id"] or "N/A",
            dims_str or "-",
            f["created_at"][:19] if f["created_at"] else "N/A",
        )

    console.print(table)


def _show_impact(console: Any, backend: Any, agent_id: str) -> None:
    """Show weight adjustment impact for an agent."""
    from driftbase.local.feedback_weights import get_feedback_impact

    # Get base weights from use case inference (use GENERAL defaults)
    from driftbase.local.use_case_inference import USE_CASE_WEIGHTS

    base_weights = USE_CASE_WEIGHTS.get("GENERAL", {})

    # Compute impact
    impact = get_feedback_impact(base_weights, agent_id, backend)

    if impact["total_dismissals"] == 0:
        console.print(f"[yellow]No feedback recorded for agent {agent_id}[/yellow]")
        return

    # Display impact table
    table = Table(title=f"Feedback Impact for Agent: {agent_id}")
    table.add_column("Dimension", style="cyan")
    table.add_column("Base Weight", justify="right", style="white")
    table.add_column("Adjusted Weight", justify="right", style="yellow")
    table.add_column("Dismiss Count", justify="right", style="magenta")
    table.add_column("Effective %", justify="right", style="green")

    # Show all dimensions that have been adjusted
    for change in impact["changes"]:
        dim = change["dimension"]
        base = change["base_weight"]
        adjusted = change["adjusted_weight"]
        count = change["dismiss_count"]
        reduction = change["reduction_pct"]

        # Calculate effective percentage (what % of original remains)
        effective_pct = 100 - reduction

        table.add_row(
            dim,
            f"{base:.3f}",
            f"{adjusted:.3f}",
            str(count),
            f"{effective_pct:.0f}%",
        )

    console.print(table)
    console.print(
        f"\n[dim]Total dismissals: {impact['total_dismissals']} across {len(impact['changes'])} dimensions[/]"
    )


def _reset_feedback(console: Any, backend: Any, agent_id: str, confirm: bool) -> None:
    """Reset (delete) all feedback for an agent."""
    # Get feedback count for this agent
    feedback_list = backend.get_feedback_for_agent(agent_id)
    count = len(feedback_list)

    if count == 0:
        console.print(f"[yellow]No feedback found for agent {agent_id}[/yellow]")
        return

    if not confirm:
        console.print(
            f"[yellow]This will delete {count} feedback record{'s' if count != 1 else ''} "
            f"for agent {agent_id}.[/yellow]\n"
            f"Re-run with --confirm to proceed."
        )
        return

    # Delete all feedback by deleting each record
    # (We don't have a bulk delete method yet, so we'll need to add one)
    # For now, let's add a method to the backend
    try:
        # We need to add a delete_feedback_for_agent method to the backend
        # For now, we'll use SQL directly
        from sqlalchemy import text
        from sqlmodel import Session

        with Session(backend._engine) as session:
            result = session.execute(
                text("DELETE FROM feedback WHERE agent_id = :agent_id"),
                {"agent_id": agent_id},
            )
            session.commit()
            deleted_count = result.rowcount

        console.print(
            Panel(
                f"[green]Reset {deleted_count} feedback record{'s' if deleted_count != 1 else ''} "
                f"for agent {agent_id}.[/green]\n\n"
                f"Weights restored to defaults.",
                title="Feedback Reset",
                border_style="green",
            )
        )
    except Exception as e:
        console.print(f"[red]Error resetting feedback: {e}[/red]")
