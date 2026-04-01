"""
Deploy outcome labeling CLI commands.
"""

from __future__ import annotations

import click
from rich.markup import escape


@click.group(name="deploy")
def cmd_deploy():
    """Mark versions as good or bad."""
    pass


@cmd_deploy.command(name="mark")
@click.argument("version")
@click.option(
    "--outcome",
    type=click.Choice(["good", "bad"], case_sensitive=False),
    required=True,
    help="Outcome label: good or bad",
)
@click.option("--note", default="", help="Optional note describing the outcome")
@click.option("--agent", default=None, help="Agent ID (auto-detected if omitted)")
@click.option("--force", is_flag=True, help="Overwrite existing label without prompt")
@click.pass_context
def cmd_deploy_mark(
    ctx: click.Context,
    version: str,
    outcome: str,
    note: str,
    agent: str | None,
    force: bool,
) -> None:
    """Mark a version with a good or bad outcome for weight learning."""
    from driftbase.backends.factory import get_backend

    console = ctx.obj.get("console")
    backend = get_backend()

    # Auto-detect agent_id from runs if not provided
    if not agent:
        runs = backend.get_runs(deployment_version=version, limit=1)
        if not runs:
            console.print(
                f"[#FF6B6B]✗[/] No runs found for version {escape(version)}. "
                f"Specify --agent explicitly or run the agent first."
            )
            ctx.exit(1)
        agent = runs[0].get("session_id", "unknown")

    if not agent or agent == "unknown":
        console.print(
            "[#FF6B6B]✗[/] Could not determine agent ID. Specify --agent explicitly."
        )
        ctx.exit(1)

    # Check if runs exist for this version (warn but allow)
    runs = backend.get_runs(deployment_version=version, limit=1)
    runs = [r for r in runs if r.get("session_id") == agent]

    if not runs:
        console.print(
            f"[#FFA94D]⚠[/] Warning: No runs found for {escape(agent)}/{escape(version)}. "
            f"Labeling anyway."
        )

    # Check if already labeled
    existing = backend.get_deploy_outcome(agent, version)
    if existing and not force:
        console.print(
            f"[#FFA94D]⚠[/] {escape(version)} is already labeled as {existing['outcome']}."
        )
        if not click.confirm("Overwrite?", default=False):
            console.print("Cancelled.")
            ctx.exit(0)

    # Write outcome
    backend.write_deploy_outcome(agent, version, outcome.lower(), note)

    console.print(f"[#4ADE80]✓[/] Marked {escape(version)} as [bold]{outcome}[/]")
    console.print(f"  Agent: {escape(agent)}")
    if note:
        console.print(f"  Note: {escape(note)}")


@cmd_deploy.command(name="list")
@click.argument("agent_id", required=False)
@click.pass_context
def cmd_deploy_list(ctx: click.Context, agent_id: str | None) -> None:
    """List all labeled versions for an agent."""
    from rich.table import Table

    from driftbase.backends.factory import get_backend

    console = ctx.obj.get("console")
    backend = get_backend()

    # Auto-detect agent_id from most recent run if not provided
    if not agent_id:
        last_run = backend.get_last_run()
        if not last_run:
            console.print("[#FF6B6B]✗[/] No runs found. Specify agent_id explicitly.")
            ctx.exit(1)
        agent_id = last_run.get("session_id", "unknown")

    if not agent_id or agent_id == "unknown":
        console.print("[#FF6B6B]✗[/] Could not determine agent ID. Specify explicitly.")
        ctx.exit(1)

    outcomes = backend.get_deploy_outcomes(agent_id)

    if not outcomes:
        console.print(
            f"No labeled versions for [bold]{escape(agent_id)}[/]. "
            f"Run 'driftbase deploy mark' to label versions."
        )
        ctx.exit(0)

    # Build table
    table = Table(show_header=True, header_style="bold")
    table.add_column("Version", style="#8B5CF6")
    table.add_column("Outcome")
    table.add_column("Runs")
    table.add_column("Note", max_width=40)
    table.add_column("Labeled At", style="dim")

    for outcome in outcomes:
        version = outcome["version"]
        runs = backend.get_runs(deployment_version=version, limit=1000)
        runs = [r for r in runs if r.get("session_id") == agent_id]
        run_count = len(runs)

        # Color code outcome
        if outcome["outcome"] == "good":
            outcome_str = "[#4ADE80]✓ good[/]"
        else:
            outcome_str = "[#FF6B6B]✗ bad[/]"

        # Format labeled_at
        labeled_at = outcome.get("labeled_at", "")
        if "T" in labeled_at:
            labeled_at = labeled_at.split("T")[0]

        table.add_row(
            escape(version),
            outcome_str,
            str(run_count),
            escape(outcome.get("note", "")),
            labeled_at,
        )

    console.print(f"\nLabeled versions for [bold]{escape(agent_id)}[/]:\n")
    console.print(table)
    console.print()


@cmd_deploy.command(name="weights")
@click.argument("agent_id", required=False)
@click.pass_context
def cmd_deploy_weights(ctx: click.Context, agent_id: str | None) -> None:
    """Show learned weights for an agent."""
    from rich.table import Table

    from driftbase.backends.factory import get_backend
    from driftbase.local.weight_learner import learn_weights

    console = ctx.obj.get("console")
    backend = get_backend()

    # Auto-detect agent_id from most recent run if not provided
    if not agent_id:
        last_run = backend.get_last_run()
        if not last_run:
            console.print("[#FF6B6B]✗[/] No runs found. Specify agent_id explicitly.")
            ctx.exit(1)
        agent_id = last_run.get("session_id", "unknown")

    if not agent_id or agent_id == "unknown":
        console.print("[#FF6B6B]✗[/] Could not determine agent ID. Specify explicitly.")
        ctx.exit(1)

    # Get labeled outcomes count
    outcomes = backend.get_deploy_outcomes(agent_id)
    n_labeled = len(outcomes)

    if n_labeled < 10:
        console.print(
            f"[#FFA94D]Insufficient labeled deploys for weight learning "
            f"(n={n_labeled}, need 10+).[/]\n"
        )
        console.print("Run [bold]driftbase deploy mark[/] to label more versions.")
        ctx.exit(0)

    # Learn weights
    console.print(f"Computing learned weights for [bold]{escape(agent_id)}[/]...")
    learned = learn_weights(agent_id)

    if not learned:
        console.print(
            "[#FFA94D]Could not compute learned weights.[/] "
            "Ensure at least 10 labeled versions with runs exist."
        )
        ctx.exit(1)

    # Cache learned weights
    backend.write_learned_weights(
        agent_id,
        {
            "weights": learned.weights,
            "metadata": {
                "raw_correlations": learned.raw_correlations,
                "learned_factor": learned.learned_factor,
                "n_good": learned.n_good,
                "n_bad": learned.n_bad,
                "top_predictors": learned.top_predictors,
            },
            "n_total": learned.n_total,
        },
    )

    # Display results
    from driftbase.local.use_case_inference import USE_CASE_WEIGHTS

    preset = USE_CASE_WEIGHTS["GENERAL"]

    console.print(
        f"\n[bold]Learned Weights for {escape(agent_id)}[/] "
        f"(based on {learned.n_total} labeled deploys)\n"
    )

    table = Table(show_header=True, header_style="bold")
    table.add_column("Dimension", style="#8B5CF6")
    table.add_column("Preset", justify="right")
    table.add_column("Learned", justify="right")
    table.add_column("Change", justify="right")

    # Sort by learned weight descending
    sorted_dims = sorted(learned.weights.items(), key=lambda x: x[1], reverse=True)

    for dim, learned_w in sorted_dims:
        preset_w = preset.get(dim, 0.0)

        if learned_w == 0 and preset_w == 0:
            continue

        # Calculate change
        if preset_w > 0:
            pct_change = ((learned_w - preset_w) / preset_w) * 100
        else:
            pct_change = 0.0

        # Format change with arrow
        if pct_change > 5:
            change_str = f"[#4ADE80]↑ +{pct_change:.0f}%[/]"
        elif pct_change < -5:
            change_str = f"[#FF6B6B]↓ {pct_change:.0f}%[/]"
        else:
            change_str = "[dim]→ 0%[/]"

        # Map dimension key to display name
        dim_display = dim.replace("_", " ")

        table.add_row(
            dim_display,
            f"{preset_w:.2f}",
            f"{learned_w:.2f}",
            change_str,
        )

    console.print(table)
    console.print(
        f"\n[dim]Training set: {learned.n_good} good · {learned.n_bad} bad[/]"
    )
    console.print(f"[dim]Top predictors: {', '.join(learned.top_predictors)}[/]\n")
