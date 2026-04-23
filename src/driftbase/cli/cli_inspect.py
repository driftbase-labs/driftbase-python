import json

import click

from driftbase.backends.factory import get_backend
from driftbase.cli._deps import safe_import_rich
from driftbase.pricing import estimate_run_cost

# Import rich components (now core dependencies)
Console, Panel, Table = safe_import_rich()

try:
    from rich.markdown import Markdown
except ImportError:
    Markdown = None  # Graceful degradation


def _format_tree(node: dict, indent: int = 0) -> str:
    """
    Format observation tree as hierarchical ASCII tree.

    Args:
        node: Tree node dict with {id, type, name, children}
        indent: Current indentation level

    Returns:
        Formatted tree string with indentation and branch characters
    """
    if not isinstance(node, dict):
        return ""

    lines = []
    prefix = "  " * indent

    # Node info
    node_type = node.get("type", "unknown")
    node_name = node.get("name", "unnamed")
    node_id = node.get("id", "")[:8]  # Show first 8 chars of ID

    # Color based on type
    type_colors = {
        "generation": "cyan",
        "tool": "green",
        "span": "blue",
        "event": "yellow",
        "trace": "magenta",
    }
    color = type_colors.get(node_type, "white")

    lines.append(
        f"{prefix}[{color}]{node_type}[/{color}] {node_name} [dim]({node_id})[/]"
    )

    # Recursively format children
    children = node.get("children", [])
    for i, child in enumerate(children):
        is_last = i == len(children) - 1
        child_prefix = "  " * (indent + 1)
        child_lines = _format_tree(child, indent + 1).split("\n")
        lines.extend(child_lines)

    return "\n".join(lines)


@click.command("inspect")
@click.argument("run_id")
@click.pass_context
def cmd_inspect(ctx: click.Context, run_id: str) -> None:
    """Deep-dive into a specific run."""
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

    # 3. Observation Tree (Phase 4)
    observation_tree_json = target_run.get("observation_tree_json")
    if observation_tree_json:
        try:
            tree = json.loads(observation_tree_json)
            tree_display = _format_tree(tree, indent=0)
            console.print(
                Panel(
                    tree_display,
                    title="[bold]Observation Tree[/] [dim](Phase 4)[/]",
                    border_style="#8B5CF6",
                )
            )
        except Exception as e:
            console.print(f"[dim]Failed to render observation tree: {e}[/]")

    # 4. Blob Content (Phase 4 - full input/output from blob storage)
    blobs = backend.get_blobs_for_run(full_id)
    for blob in blobs:
        field_name = blob.field_name
        content = blob.content
        truncated = blob.truncated
        size_kb = blob.content_length / 1024

        title_suffix = f" [dim]({size_kb:.1f}KB"
        if truncated:
            title_suffix += ", truncated at cap"
        title_suffix += ")[/]"

        if field_name == "input":
            console.print(
                Panel(
                    Markdown(content[:5000]) if Markdown else content[:5000],
                    title=f"[bold yellow]Full Input (Blob)[/]{title_suffix}",
                    border_style="#FFA94D",
                )
            )
        elif field_name == "output":
            console.print(
                Panel(
                    Markdown(content[:5000]) if Markdown else content[:5000],
                    title=f"[bold green]Full Output (Blob)[/]{title_suffix}",
                    border_style="#4ADE80",
                )
            )

    # 5. Raw Prompt (Local Flight Recorder - legacy, fallback if no blobs)
    if raw_prompt and not any(b.field_name == "input" for b in blobs):
        console.print(
            Panel(
                Markdown(raw_prompt) if Markdown else raw_prompt,
                title="[bold yellow]Raw Prompt[/] [dim](Local Only)[/]",
                border_style="#FFA94D",
            )
        )

    # 6. Raw Output (Local Flight Recorder - legacy, fallback if no blobs)
    if raw_output and not any(b.field_name == "output" for b in blobs):
        console.print(
            Panel(
                Markdown(raw_output) if Markdown else raw_output,
                title="[bold green]Raw Output[/] [dim](Local Only)[/]",
                border_style="#4ADE80",
            )
        )

    # 7. Privacy State
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
