import os

import click
import httpx

from driftbase.backends.factory import get_backend
from driftbase.cli._deps import safe_import_rich

# Import rich components (now core dependencies)
Console, Panel, Table = safe_import_rich()

try:
    from rich.progress import Progress, SpinnerColumn, TextColumn
except ImportError:
    Progress = SpinnerColumn = TextColumn = None  # Graceful degradation


@click.command("push")
@click.pass_context
def cmd_push(ctx: click.Context):
    """Sync local runs to the Driftbase dashboard (Pro).

    Use this after subscribing to Pro to connect your existing local data,
    or run it anytime to sync new runs. Raw prompts and outputs are stripped
    before upload (GDPR-compliant). The dashboard shows runs, drift analytics,
    and version comparisons.
    """
    console: Console = ctx.obj["console"]

    api_key = os.getenv("DRIFTBASE_API_KEY")
    if not api_key:
        console.print(
            "[bold red]Error:[/] DRIFTBASE_API_KEY is required to sync to the dashboard."
        )
        console.print("Get your key from the dashboard after subscribing, then run:")
        console.print("  [bold cyan]export DRIFTBASE_API_KEY='your_key'[/]")
        console.print("  [bold cyan]driftbase push[/]")
        ctx.exit(1)

    api_url = os.getenv("DRIFTBASE_API_URL", "http://localhost:8000")

    backend = get_backend()
    if not hasattr(backend, "get_all_runs"):
        console.print(
            "[bold red]Error:[/] This backend does not support sync (use local SQLite)."
        )
        ctx.exit(1)
    runs = backend.get_all_runs()

    if not runs:
        console.print("#FFA94D]No local runs to sync.[/]")
        console.print(
            "[dim]Run your instrumented agent or 'driftbase demo', then try again.[/]"
        )
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
        console=console,
    ) as progress:
        task = progress.add_task(
            f"Syncing {len(payload_runs)} runs to Driftbase Pro...", total=None
        )

        try:
            response = httpx.post(
                f"{api_url}/api/v1/sync",
                json=payload,
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=10.0,
            )
            response.raise_for_status()
            data = response.json()
            progress.update(task, completed=True)

            inserted = data.get("inserted", len(payload_runs))
            tenant = data.get("tenant_id", "unknown")

            console.print(
                f"\n[bold green]✓ Synced {inserted} runs to your dashboard.[/]"
            )
            console.print(f"[dim]Workspace: {tenant}[/]")
            console.print(
                "[dim]View runs, drift analytics, and version comparisons in the dashboard.[/]"
            )
            console.print(
                "[dim]Raw prompts/outputs were stripped before upload (GDPR).[/]"
            )

        except httpx.HTTPStatusError as e:
            console.print(
                f"\n[bold red]API Error:[/] {e.response.status_code} - {e.response.text}"
            )
        except Exception as e:
            console.print(
                f"\n[bold red]Connection Error:[/] Could not reach {api_url}."
            )
            console.print(f"[dim]{str(e)}[/dim]")
