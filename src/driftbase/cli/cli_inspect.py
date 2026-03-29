import json

import click

from driftbase.backends.factory import get_backend
from driftbase.cli._deps import safe_import_rich
from driftbase.pricing import estimate_run_cost

# Lazy import of heavy [analyze] dependencies
Console, Panel, Table = safe_import_rich()

try:
    from rich.markdown import Markdown
except ImportError:
    Markdown = None  # Graceful degradation


@click.command("inspect")
@click.argument("run_id")
@click.pass_context
def cmd_inspect(ctx: click.Context, run_id: str) -> None:
    """Deep-dive into a specific agent run (tools, latency, cost, and raw text)."""
    console: Console = ctx.obj["console"]
    backend = get_backend()

    runs = backend.get_all_runs()
    target_run = next(
        (
            r
            for r in runs
            if str(r.get("id", "")).startswith(run_id)
            or str(r.get("session_id", "")).startswith(run_id)
        ),
        None,
    )

    if not target_run:
        console.print(
            Panel(
                f"No run found matching ID: [bold]{run_id}[/]",
                title="Error",
                border_style="#FF6B6B",
            )
        )
        ctx.exit(1)

    full_id = target_run.get("id", target_run.get("session_id", "Unknown"))
    version = target_run.get("deployment_version", "unknown")
    outcome = target_run.get("semantic_cluster", "unknown")
    latency = target_run.get("latency_ms", 0)
    p_tokens = target_run.get("prompt_tokens", 0) or 0
    c_tokens = target_run.get("completion_tokens", 0) or 0
    cost = estimate_run_cost(p_tokens, c_tokens)
    raw_prompt = target_run.get("raw_prompt")
    raw_output = target_run.get("raw_output")

    outcome_color = "red" if outcome in ["error", "escalated"] else "green"

    # 1. Metadata Panel
    meta_table = Table(show_header=False, box=None, padding=(0, 2))
    meta_table.add_row("[dim]Run ID[/]", f"[bold]{full_id}[/]")
    meta_table.add_row("[dim]Version[/]", f"[bold cyan]{version}[/]")
    meta_table.add_row("[dim]Outcome[/]", f"[bold {outcome_color}]{outcome.upper()}[/]")
    meta_table.add_row("[dim]Latency[/]", f"{latency}ms")
    meta_table.add_row("[dim]Tokens[/]", f"{p_tokens} prompt / {c_tokens} completion")
    meta_table.add_row("[dim]Est. Cost[/]", f"€{cost:.6f}")

    console.print(Panel(meta_table, title="[bold]Run Metadata[/]", border_style="blue"))

    # 2. Tool Execution Path
    tools_raw = target_run.get("tool_sequence", "[]")
    try:
        tools = json.loads(tools_raw) if isinstance(tools_raw, str) else tools_raw
    except Exception:
        tools = []

    if tools:
        tool_steps = " ➔ ".join(f"[bold cyan]{t}[/]" for t in tools)
        console.print(
            Panel(
                tool_steps,
                title="[bold]Tool Execution Chain[/]",
                border_style="#8B5CF6",
            )
        )
    else:
        console.print(
            Panel(
                "[dim]No tools called during this run.[/]",
                title="[bold]Tool Execution Chain[/]",
                border_style="dim",
            )
        )

    # 3. Raw Prompt (Local Flight Recorder)
    if raw_prompt:
        console.print(
            Panel(
                Markdown(raw_prompt),
                title="[bold yellow]Raw Prompt[/] [dim](Local Only)[/]",
                border_style="#FFA94D",
            )
        )

    # 4. Raw Output (Local Flight Recorder)
    if raw_output:
        console.print(
            Panel(
                Markdown(raw_output),
                title="[bold green]Raw Output[/] [dim](Local Only)[/]",
                border_style="#4ADE80",
            )
        )

    # 5. Privacy State
    privacy_table = Table(show_header=False, box=None, padding=(0, 2))
    privacy_table.add_row(
        "[dim]Input Hash[/]", f"[bold dim]{target_run.get('task_input_hash', 'N/A')}[/]"
    )
    privacy_table.add_row(
        "[dim]Output Structure[/]",
        f"[bold dim]{target_run.get('output_structure_hash', 'N/A')}[/]",
    )

    console.print(
        Panel(
            privacy_table,
            title="[bold dim]Cloud Sync Payload[/]",
            border_style="dim",
            subtitle="[dim]Only structural hashes leave this machine during 'driftbase push'[/]",
        )
    )
