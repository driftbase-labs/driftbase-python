"""MCP server implementation for Driftbase."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

try:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import TextContent, Tool

    MCP_AVAILABLE = True
except ImportError:
    MCP_AVAILABLE = False


class MCPServer:
    """MCP server for exposing Driftbase functionality to AI assistants."""

    def __init__(self):
        if not MCP_AVAILABLE:
            raise ImportError(
                "mcp extra not installed. Run: pip install driftbase[mcp]"
            )
        self.server = Server("driftbase")
        self._register_tools()

    def _register_tools(self):
        """Register all available tools."""

        @self.server.list_tools()
        async def list_tools() -> list[Tool]:
            """List available Driftbase tools."""
            return [
                Tool(
                    name="record_run",
                    description="Record a new agent run in Driftbase",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "session_id": {
                                "type": "string",
                                "description": "Agent/session identifier",
                            },
                            "deployment_version": {
                                "type": "string",
                                "description": "Version label (e.g., 'v1', 'prod-2024-01-15')",
                            },
                            "output": {
                                "type": "string",
                                "description": "Agent output text",
                            },
                            "latency_ms": {
                                "type": "number",
                                "description": "Response latency in milliseconds",
                            },
                            "prompt_tokens": {
                                "type": "number",
                                "description": "Input token count",
                            },
                            "completion_tokens": {
                                "type": "number",
                                "description": "Output token count",
                            },
                            "tool_sequence": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Ordered list of tool names called",
                            },
                            "error": {
                                "type": "boolean",
                                "description": "Whether the run resulted in an error",
                            },
                        },
                        "required": ["session_id", "deployment_version", "output"],
                    },
                ),
                Tool(
                    name="diagnose",
                    description="Run behavioral shift diagnosis on an agent",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "agent_id": {
                                "type": "string",
                                "description": "Agent identifier (optional, uses default if not provided)",
                            }
                        },
                    },
                ),
                Tool(
                    name="get_history",
                    description="Get behavioral timeline history for an agent",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "agent_id": {
                                "type": "string",
                                "description": "Agent identifier (optional, uses default if not provided)",
                            },
                            "limit": {
                                "type": "number",
                                "description": "Maximum number of epochs to return (default: 10)",
                            },
                        },
                    },
                ),
            ]

        @self.server.call_tool()
        async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
            """Handle tool calls."""
            try:
                if name == "record_run":
                    return await self._handle_record_run(arguments)
                elif name == "diagnose":
                    return await self._handle_diagnose(arguments)
                elif name == "get_history":
                    return await self._handle_get_history(arguments)
                else:
                    return [
                        TextContent(
                            type="text",
                            text=json.dumps(
                                {"error": f"Unknown tool: {name}"}, indent=2
                            ),
                        )
                    ]
            except Exception as e:
                logger.error(f"Tool call failed: {e}")
                return [
                    TextContent(
                        type="text",
                        text=json.dumps({"error": str(e)}, indent=2),
                    )
                ]

    async def _handle_record_run(self, arguments: dict[str, Any]) -> list[TextContent]:
        """Handle record_run tool call."""
        from driftbase.backends.factory import get_backend

        backend = get_backend()

        # Build run record
        run_data = {
            "session_id": arguments["session_id"],
            "deployment_version": arguments["deployment_version"],
            "raw_output": arguments["output"],
            "output_length": len(arguments["output"]),
            "latency_ms": arguments.get("latency_ms", 0),
            "prompt_tokens": arguments.get("prompt_tokens", 0),
            "completion_tokens": arguments.get("completion_tokens", 0),
            "tool_sequence": json.dumps(arguments.get("tool_sequence", [])),
            "tool_call_count": len(arguments.get("tool_sequence", [])),
            "error_count": 1 if arguments.get("error", False) else 0,
            "started_at": datetime.utcnow(),
            "completed_at": datetime.utcnow(),
            "environment": "production",
        }

        # Infer semantic cluster from output
        from driftbase.connectors.mapper import infer_semantic_cluster

        run_data["semantic_cluster"] = infer_semantic_cluster(
            arguments["output"], arguments.get("error", False)
        )

        # Write to backend
        backend.write_run(run_data)

        return [
            TextContent(
                type="text",
                text=json.dumps(
                    {
                        "success": True,
                        "message": f"Recorded run for {arguments['session_id']} version {arguments['deployment_version']}",
                    },
                    indent=2,
                ),
            )
        ]

    async def _handle_diagnose(self, arguments: dict[str, Any]) -> list[TextContent]:
        """Handle diagnose tool call."""
        from driftbase.backends.factory import get_backend
        from driftbase.config import get_settings
        from driftbase.local.epoch_detector import detect_epochs

        backend = get_backend()
        agent_id = arguments.get("agent_id")

        # Get all runs
        runs = backend.get_all_runs()

        # Filter by agent_id if provided
        if agent_id:
            runs = [
                r
                for r in runs
                if r.get("session_id") == agent_id or r.get("id") == agent_id
            ]

        if len(runs) < 40:
            return [
                TextContent(
                    type="text",
                    text=json.dumps(
                        {
                            "status": "insufficient_data",
                            "run_count": len(runs),
                            "message": f"Need 40+ runs to detect shifts. Currently have {len(runs)} runs.",
                        },
                        indent=2,
                    ),
                )
            ]

        # Get agent_id from most recent run if not provided
        if not agent_id:
            agent_id = runs[0].get("session_id") or runs[0].get("id")

        # Detect epochs
        db_path = get_settings().DRIFTBASE_DB_PATH
        epochs = detect_epochs(agent_id, db_path, window_size=20, sensitivity=0.15)

        if epochs and len(epochs) >= 2:
            latest_epoch = epochs[-1]
            return [
                TextContent(
                    type="text",
                    text=json.dumps(
                        {
                            "status": "shift_detected",
                            "total_runs": len(runs),
                            "epochs_detected": len(epochs),
                            "latest_epoch": {
                                "label": latest_epoch.label,
                                "run_count": latest_epoch.run_count,
                                "stability": latest_epoch.stability,
                                "summary": latest_epoch.summary,
                            },
                        },
                        indent=2,
                    ),
                )
            ]
        else:
            return [
                TextContent(
                    type="text",
                    text=json.dumps(
                        {
                            "status": "no_shift",
                            "total_runs": len(runs),
                            "message": "No behavioral shift detected. Behavior has been stable.",
                        },
                        indent=2,
                    ),
                )
            ]

    async def _handle_get_history(self, arguments: dict[str, Any]) -> list[TextContent]:
        """Handle get_history tool call."""
        from driftbase.backends.factory import get_backend
        from driftbase.config import get_settings
        from driftbase.local.epoch_detector import detect_epochs

        backend = get_backend()
        agent_id = arguments.get("agent_id")
        limit = arguments.get("limit", 10)

        # Get all runs
        runs = backend.get_all_runs()

        # Filter by agent_id if provided
        if agent_id:
            runs = [
                r
                for r in runs
                if r.get("session_id") == agent_id or r.get("id") == agent_id
            ]

        if len(runs) < 40:
            return [
                TextContent(
                    type="text",
                    text=json.dumps(
                        {
                            "status": "insufficient_data",
                            "run_count": len(runs),
                            "message": f"Need 40+ runs for timeline. Currently have {len(runs)} runs.",
                        },
                        indent=2,
                    ),
                )
            ]

        # Get agent_id from most recent run if not provided
        if not agent_id:
            agent_id = runs[0].get("session_id") or runs[0].get("id")

        # Detect epochs
        db_path = get_settings().DRIFTBASE_DB_PATH
        epochs = detect_epochs(agent_id, db_path, window_size=20, sensitivity=0.15)
        epochs = epochs[:limit]

        # Format response
        timeline = []
        for epoch in epochs:
            timeline.append(
                {
                    "label": epoch.label,
                    "start_time": epoch.start_time.isoformat()
                    if epoch.start_time
                    else None,
                    "end_time": epoch.end_time.isoformat() if epoch.end_time else None,
                    "run_count": epoch.run_count,
                    "stability": epoch.stability,
                    "summary": epoch.summary,
                }
            )

        return [
            TextContent(
                type="text",
                text=json.dumps(
                    {
                        "status": "success",
                        "total_runs": len(runs),
                        "epochs": timeline,
                    },
                    indent=2,
                ),
            )
        ]

    async def run(self):
        """Run the MCP server using stdio transport."""
        async with stdio_server() as (read_stream, write_stream):
            await self.server.run(
                read_stream,
                write_stream,
                self.server.create_initialization_options(),
            )
