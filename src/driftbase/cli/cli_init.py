"""
Interactive CLI command to help users get started with Driftbase.
Guides through connecting Langfuse for drift detection.
"""

from __future__ import annotations

import os
from pathlib import Path

import click

from driftbase.cli._deps import safe_import_rich

# Lazy import of rich dependencies
Console, Panel, Table = safe_import_rich()


@click.command(name="init")
@click.pass_context
def cmd_init(ctx: click.Context) -> None:
    """Interactive setup — get started with Langfuse in 2 minutes."""
    console: Console = ctx.obj["console"]
    use_color = not console.no_color

    # Welcome message
    if use_color:
        console.print()
        console.print(
            Panel(
                "[bold]Welcome to Driftbase![/]\n\n"
                "Driftbase detects behavioral drift in AI agents by analyzing\n"
                "your existing Langfuse traces. No SDK to install in your agent code.\n\n"
                "[dim]This wizard will help you connect Langfuse in 2 minutes.[/]",
                title="[bold cyan]🚀 Getting Started[/]",
                border_style="#8B5CF6",
            )
        )
        console.print()
    else:
        console.print("\n=== Welcome to Driftbase! ===\n")
        console.print("Driftbase detects behavioral drift in AI agents by analyzing")
        console.print(
            "your existing Langfuse traces. No SDK to install in your agent code.\n"
        )
        console.print("This wizard will help you connect Langfuse in 2 minutes.\n")

    # Check if Langfuse credentials are already set
    langfuse_public = os.getenv("LANGFUSE_PUBLIC_KEY")
    langfuse_secret = os.getenv("LANGFUSE_SECRET_KEY")
    langfuse_host = os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")

    if langfuse_public and langfuse_secret:
        console.print("[bold green]✓ Langfuse credentials detected![/]\n")
        console.print(f"  Public Key: {langfuse_public[:10]}...")
        console.print(f"  Host: {langfuse_host}\n")
        console.print(
            "[bold]Next step:[/] Run [#8B5CF6]driftbase connect[/] to import traces.\n"
        )
    else:
        # Show setup instructions
        if use_color:
            console.print(
                Panel(
                    "[bold]Step 1: Set up Langfuse credentials[/]\n\n"
                    "Add these environment variables to your shell:\n\n"
                    "  [dim]export LANGFUSE_PUBLIC_KEY=your-public-key[/]\n"
                    "  [dim]export LANGFUSE_SECRET_KEY=your-secret-key[/]\n"
                    "  [dim]export LANGFUSE_HOST=https://cloud.langfuse.com[/]  # optional\n\n"
                    "[bold]Where to find your keys:[/]\n"
                    "1. Log into Langfuse: [link]https://cloud.langfuse.com[/]\n"
                    "2. Go to Settings → API Keys\n"
                    "3. Copy your public and secret keys",
                    title="[bold yellow]Setup Required[/]",
                    border_style="#FFA94D",
                )
            )
        else:
            console.print("=== Step 1: Set up Langfuse credentials ===\n")
            console.print("Add these environment variables to your shell:\n")
            console.print("  export LANGFUSE_PUBLIC_KEY=your-public-key")
            console.print("  export LANGFUSE_SECRET_KEY=your-secret-key")
            console.print(
                "  export LANGFUSE_HOST=https://cloud.langfuse.com  # optional\n"
            )
            console.print("Where to find your keys:")
            console.print("1. Log into Langfuse: https://cloud.langfuse.com")
            console.print("2. Go to Settings → API Keys")
            console.print("3. Copy your public and secret keys\n")

        console.print()

        # Prompt for keys
        if click.confirm("Do you have your Langfuse API keys ready?", default=False):
            public_key = click.prompt("Public Key", type=str)
            secret_key = click.prompt("Secret Key", type=str, hide_input=True)
            host = click.prompt("Host", type=str, default="https://cloud.langfuse.com")

            # Save to config file
            config_dir = Path.home() / ".driftbase"
            config_dir.mkdir(exist_ok=True)
            env_path = config_dir / ".env"

            env_content = f"""# Driftbase + Langfuse configuration
LANGFUSE_PUBLIC_KEY={public_key}
LANGFUSE_SECRET_KEY={secret_key}
LANGFUSE_HOST={host}
"""
            env_path.write_text(env_content)

            if use_color:
                console.print(f"\n[bold green]✓ Credentials saved to {env_path}[/]\n")
                console.print("[dim]Add this to your shell profile to persist:[/]")
                console.print(f"[dim]  export $(cat {env_path} | xargs)[/]\n")
            else:
                console.print(f"\n✓ Credentials saved to {env_path}\n")
                console.print("Add this to your shell profile to persist:")
                console.print(f"  export $(cat {env_path} | xargs)\n")

    # Next steps
    if use_color:
        console.print(
            Panel(
                "[bold]Next steps:[/]\n\n"
                "  [#4ADE80]1. Import your Langfuse traces:[/]\n"
                "     [#8B5CF6]driftbase connect[/]\n\n"
                "  [#4ADE80]2. View behavioral history:[/]\n"
                "     [#8B5CF6]driftbase history[/]\n\n"
                "  [#4ADE80]3. Detect drift:[/]\n"
                "     [#8B5CF6]driftbase diagnose[/]\n\n"
                "[dim]💡 All analysis runs locally. Your traces stay on your machine.[/]",
                title="[bold yellow]What's Next[/]",
                border_style="#FFA94D",
            )
        )
    else:
        console.print("=== Next steps: ===\n")
        console.print("  1. Import your Langfuse traces:")
        console.print("     driftbase connect\n")
        console.print("  2. View behavioral history:")
        console.print("     driftbase history\n")
        console.print("  3. Detect drift:")
        console.print("     driftbase diagnose\n")
        console.print(
            "💡 All analysis runs locally. Your traces stay on your machine.\n"
        )

    console.print()

    if use_color:
        console.print("[bold green]Happy drift hunting! 🎯[/]\n")
    else:
        console.print("Happy drift hunting! 🎯\n")
