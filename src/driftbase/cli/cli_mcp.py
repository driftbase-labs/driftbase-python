"""CLI commands for MCP server."""

from __future__ import annotations

import asyncio
import logging

import click

from driftbase.cli._deps import safe_import_rich

logger = logging.getLogger(__name__)

Console, Panel, _ = safe_import_rich()


@click.group("mcp")
@click.pass_context
def cmd_mcp(ctx: click.Context) -> None:
    """MCP server for AI assistant integration."""
    pass


@cmd_mcp.command("serve")
@click.option(
    "--log-level",
    type=click.Choice(["debug", "info", "warning", "error"]),
    default="warning",
    help="Logging level for server output (default: warning)",
)
@click.pass_context
def cmd_serve(ctx: click.Context, log_level: str) -> None:
    """Start MCP server (for Claude Desktop, Claude Code, etc.)."""
    console: Console = ctx.obj["console"]

    # Set logging level
    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    try:
        from driftbase.mcp.server import MCPServer
    except ImportError as e:
        console.print(
            Panel(
                "[bold red]MCP server not available[/]\n\n"
                "The mcp extra is not installed.\n\n"
                "Install with: [bold]pip install driftbase[mcp][/]",
                title="Error",
                border_style="red",
            )
        )
        ctx.exit(1)

    console.print(
        Panel(
            "[bold green]Starting Driftbase MCP server[/]\n\n"
            "Server will communicate over stdio.\n"
            "Add this server to your Claude Desktop config:\n\n"
            '[dim]{\n  "mcpServers": {\n    "driftbase": {\n'
            '      "command": "driftbase",\n'
            '      "args": ["mcp", "serve"]\n'
            "    }\n  }\n}[/]",
            title="MCP Server",
            border_style="cyan",
        )
    )

    # Run server
    try:
        server = MCPServer()
        asyncio.run(server.run())
    except KeyboardInterrupt:
        console.print("\n[dim]Server stopped[/]")
    except Exception as e:
        logger.error(f"Server error: {e}")
        console.print(
            Panel(
                f"[bold red]Server error:[/]\n\n{str(e)}",
                title="Error",
                border_style="red",
            )
        )
        ctx.exit(1)
