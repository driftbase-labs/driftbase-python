import os
import httpx
import click
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from driftbase.backends.factory import get_backend

@click.command("push")
@click.pass_context
def cmd_push(ctx: click.Context):
    """Sync local telemetry to Driftbase Pro (removes raw text)."""
    console: Console = ctx.obj["console"]

    api_key = os.getenv("DRIFTBASE_API_KEY")
    if not api_key:
        console.print("[bold red]Error:[/] DRIFTBASE_API_KEY environment variable is missing.")
        console.print("To authenticate with Driftbase Pro, run:")
        console.print("👉 [bold cyan]export DRIFTBASE_API_KEY='drift_abc123'[/]")
        ctx.exit(1)

    api_url = os.getenv("DRIFTBASE_API_URL", "http://localhost:8000")
    
    backend = get_backend()
    runs = backend.get_all_runs()
    
    if not runs:
        console.print("[yellow]No local runs found to sync. Run 'driftbase demo' first.[/]")
        ctx.exit(0)

    # Enforce strict European data boundary: drop raw text before it touches the network
    payload_runs = []
    for r in runs:
        safe_run = r.copy()
        safe_run.pop("raw_prompt", None)
        safe_run.pop("raw_output", None)
        
        # Ensure datetimes are ISO strings for JSON serialization
        if hasattr(safe_run.get("started_at"), "isoformat"):
            safe_run["started_at"] = safe_run["started_at"].isoformat()
        if hasattr(safe_run.get("completed_at"), "isoformat"):
            safe_run["completed_at"] = safe_run["completed_at"].isoformat()
            
        payload_runs.append(safe_run)

    payload = {"runs": payload_runs}
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console
    ) as progress:
        task = progress.add_task(f"Syncing {len(payload_runs)} runs to Driftbase Pro...", total=None)
        
        try:
            response = httpx.post(
                f"{api_url}/api/v1/sync",
                json=payload,
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=10.0
            )
            response.raise_for_status()
            data = response.json()
            progress.update(task, completed=True)
            
            inserted = data.get("inserted", 0)
            tenant = data.get("tenant_id", "unknown")
            
            console.print(f"\n[bold green]✓ Successfully synced {inserted} new runs.[/]")
            console.print(f"[dim]Workspace: {tenant}[/]")
            console.print("[dim]Raw prompts and outputs were stripped to maintain GDPR compliance.[/]")

        except httpx.HTTPStatusError as e:
            console.print(f"\n[bold red]API Error:[/] {e.response.status_code} - {e.response.text}")
        except Exception as e:
            console.print(f"\n[bold red]Connection Error:[/] Could not reach {api_url}.")
            console.print(f"[dim]{str(e)}[/dim]")