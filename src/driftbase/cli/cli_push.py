import os
import sys
import requests
from datetime import datetime
import click
from rich.console import Console

from driftbase.backends.factory import get_backend

@click.command("push")
@click.option("--url", help="Platform API URL (overrides DRIFTBASE_API_URL).")
@click.option("--key", help="Platform API Key (overrides DRIFTBASE_API_KEY).")
@click.pass_context
def cmd_push(ctx: click.Context, url: str | None, key: str | None) -> None:
    """Push local agent runs to the Driftbase platform."""
    console: Console = ctx.obj["console"]
    
    target_url = url or os.getenv("DRIFTBASE_API_URL") or "http://localhost:8000"
    target_key = key or os.getenv("DRIFTBASE_API_KEY")

    if not target_key:
        console.print("[bold red]Error:[/] DRIFTBASE_API_KEY is missing. Cannot authenticate.", style="red")
        sys.exit(1)

    console.print("Connecting to local backend...")
    backend = get_backend()
    
    local_runs = backend.get_all_runs()
    
    if not local_runs:
        console.print("No local runs found to push.")
        return

    console.print(f"Found [bold]{len(local_runs)}[/] runs. Formatting payload...")

    payload = {"runs": []}
    for run in local_runs:
        started = run.get("started_at")
        completed = run.get("completed_at")
        
        payload["runs"].append({
            "session_id": run.get("session_id", ""),
            "deployment_version": run.get("deployment_version", ""),
            "environment": run.get("environment", "production"),
            "started_at": started.isoformat() if isinstance(started, datetime) else started,
            "completed_at": completed.isoformat() if isinstance(completed, datetime) else completed,
            "task_input_hash": run.get("task_input_hash", ""),
            "tool_sequence": run.get("tool_sequence", ""),
            "tool_call_count": run.get("tool_call_count", 0),
            "output_length": run.get("output_length", 0),
            "output_structure_hash": run.get("output_structure_hash", ""),
            "latency_ms": run.get("latency_ms", 0),
            "error_count": run.get("error_count", 0),
            "retry_count": run.get("retry_count", 0),
            "semantic_cluster": run.get("semantic_cluster", "cluster_none")
        })

    console.print(f"Pushing payload to [bold]{target_url}/ingest/runs[/] ...")
    
    try:
        response = requests.post(
            f"{target_url.rstrip('/')}/ingest/runs",
            json=payload,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {target_key}"},
            timeout=10
        )
        
        if response.status_code == 200:
            data = response.json()
            console.print(f"[bold green]Success![/] Platform ingested {data.get('ingested_count')} runs.")
        elif response.status_code == 401:
            console.print("[bold red]Error 401:[/] Unauthorized. Your API key was rejected by the platform.")
        else:
            console.print(f"[bold red]Error {response.status_code}:[/] {response.text}")
            
    except requests.exceptions.ConnectionError:
        console.print(f"[bold red]Connection Error:[/] Could not reach the platform at {target_url}.")
    except Exception as e:
        console.print(f"[bold red]Unexpected error:[/] {e}")