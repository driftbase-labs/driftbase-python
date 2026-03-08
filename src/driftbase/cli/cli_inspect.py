"""
CLI inspect: show what the SDK captured, hashed, and dropped for a run (verifiable privacy).
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any, Optional

import click

from driftbase.backends.base import StorageBackend
from driftbase.backends.factory import get_backend


DROPPED_ITEMS = [
    ("Raw user message", "never stored, never hashed, dropped"),
    ("Raw agent output", "never stored, never hashed, dropped"),
    ("System prompt", "never stored, never hashed, dropped"),
    ("API keys / headers", "never accessed"),
    ("User identifiers", "never accessed"),
]




def format_inspect_report(run: dict[str, Any], storage_location: str) -> str:
    """Produce the human-readable inspect output for a single run."""
    run_id = run.get("id", "unknown")
    lines = [
        f"DRIFTBASE INSPECT — run_id: {run_id}",
        "─" * 45,
        "WHAT WAS CAPTURED (stored locally)",
        "",
        "  tool_calls:",
    ]
    tool_sequence = run.get("tool_sequence", "[]")
    try:
        tools = json.loads(tool_sequence) if isinstance(tool_sequence, str) else tool_sequence
    except Exception:
        tools = []
    for i, name in enumerate(tools, 1):
        lines.append(f"    [{i}] {name}")
    lines.append("")
    decision = run.get("semantic_cluster") or "—"
    if decision == "cluster_none":
        decision = "—"
    lines.append(f"  decision_outcome:         {decision}")
    lines.append(f"  total_latency_ms:         {run.get('latency_ms', 0)}")
    lines.append(f"  error_count:              {run.get('error_count', 0)}")
    lines.append(f"  retry_count:              {run.get('retry_count', 0)}")
    pt = run.get("prompt_tokens")
    ct = run.get("completion_tokens")
    if pt is not None and ct is not None:
        total = pt + ct
        lines.append(f"  token_usage:              {total:,} tokens")
    else:
        lines.append("  token_usage:              —")
    lines.append("")
    lines.append("WHAT WAS HASHED (content never stored)")
    lines.append("")
    input_hash = run.get("task_input_hash") or ""
    lines.append("  input_hash:     sha256(user_input)  [original discarded]")
    lines.append(f"                  → {input_hash}")
    lines.append("")
    output_hash = run.get("output_structure_hash") or ""
    lines.append("  output_hash:    sha256(agent_output)  [original discarded]")
    lines.append(f"                  → {output_hash}")
    lines.append("")
    lines.append("  tool_inputs:    each tool input hashed individually")
    lines.append("                  → originals discarded immediately after hashing")
    lines.append("")
    lines.append("WHAT WAS DROPPED (never touched by driftbase)")
    lines.append("")
    for label, desc in DROPPED_ITEMS:
        lines.append(f"  ✗  {label:<25} — {desc}")
    lines.append("")
    lines.append("─" * 45)
    lines.append(f"Storage location: {storage_location}")
    lines.append("Nothing sent to any external server (free tier)")
    return "\n".join(lines)


def inspect_run_to_dict(run: dict[str, Any], storage_location: str) -> dict[str, Any]:
    """Produce a JSON-serializable inspect payload for --export."""
    tool_sequence = run.get("tool_sequence", "[]")
    try:
        tools = json.loads(tool_sequence) if isinstance(tool_sequence, str) else tool_sequence
    except Exception:
        tools = []
    pt = run.get("prompt_tokens")
    ct = run.get("completion_tokens")
    token_usage = (pt + ct) if (pt is not None and ct is not None) else None
    return {
        "run_id": run.get("id"),
        "what_was_captured": {
            "tool_calls": [{"index": i, "name": n} for i, n in enumerate(tools, 1)],
            "decision_outcome": run.get("semantic_cluster") or None,
            "total_latency_ms": run.get("latency_ms"),
            "error_count": run.get("error_count"),
            "retry_count": run.get("retry_count"),
            "token_usage": token_usage,
        },
        "what_was_hashed": {
            "input_hash": run.get("task_input_hash"),
            "output_hash": run.get("output_structure_hash"),
            "tool_inputs": "each tool input hashed individually; originals discarded",
        },
        "what_was_dropped": [{"item": label, "note": desc} for label, desc in DROPPED_ITEMS],
        "storage_location": storage_location,
        "no_external_transmission": True,
    }


def get_storage_location(backend: Optional[StorageBackend] = None) -> str:
    """Return the storage path/location string for the current backend."""
    if backend is None:
        backend = get_backend()
    if hasattr(backend, "_db_path"):
        return os.path.expanduser(backend._db_path) + " (local only)"
    return "configured backend (local only)"


def run_inspect(
    run_id_or_last: str,
    *,
    export_path: Optional[str] = None,
    backend: Optional[StorageBackend] = None,
    console: Optional[Any] = None,
) -> int:
    """
    Load a run by id or 'last', print inspect report, optionally export JSON.
    Returns 0 on success, 1 if run not found.
    """
    from rich.console import Console as RichConsole
    from rich.panel import Panel
    _console = console if console is not None else RichConsole()

    if backend is None:
        backend = get_backend()
    if run_id_or_last.strip().lower() == "last":
        run = backend.get_last_run()
    else:
        run = backend.get_run(run_id_or_last)
    if not run:
        _console.print(
            Panel(
                f"Run not found: {run_id_or_last}",
                title="[bold red]Error[/]",
                border_style="red",
            ),
        )
        return 1
    storage_location = get_storage_location(backend)
    text_report = format_inspect_report(run, storage_location)
    _console.print(text_report)
    if export_path:
        payload = inspect_run_to_dict(run, storage_location)
        with open(export_path, "w") as f:
            json.dump(payload, f, indent=2)
        _console.print(f"\nExported to: {export_path}")
    return 0


@click.command(name="inspect")
@click.option("--run", "-r", required=True, metavar="RUN_ID_OR_LAST", help="Run ID or 'last' for most recent run.")
@click.option("--export", "-o", "export_path", metavar="PATH", help="Export inspect output as JSON.")
@click.pass_context
def cmd_inspect(ctx: click.Context, run: str, export_path: str | None) -> None:
    """Show what was captured, hashed, and dropped for a run (verifiable privacy)."""
    console = ctx.obj["console"]
    code = run_inspect(run, export_path=export_path, console=console)
    ctx.exit(code)
