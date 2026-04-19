"""Tests for MCP server functionality."""

import sys
from unittest.mock import Mock, patch

import pytest


def test_mcp_module_structure():
    """Verify MCP module imports exist."""
    from driftbase import mcp

    assert mcp is not None
    assert hasattr(mcp, "MCPServer")


def test_mcp_server_requires_mcp_extra():
    """MCPServer raises ImportError when mcp extra not installed."""
    # Mock the absence of mcp module
    with patch.dict(
        sys.modules,
        {"mcp": None, "mcp.server": None, "mcp.server.stdio": None, "mcp.types": None},
    ):
        # Force reimport
        if "driftbase.mcp.server" in sys.modules:
            del sys.modules["driftbase.mcp.server"]

        from driftbase.mcp.server import MCPServer

        with pytest.raises(ImportError, match="mcp extra not installed"):
            MCPServer()


def test_cli_mcp_group_exists():
    """CLI has mcp command group."""
    from driftbase.cli.cli import cli

    assert "mcp" in [cmd.name for cmd in cli.commands.values()]


def test_cli_mcp_help():
    """CLI mcp command shows help text."""
    from click.testing import CliRunner

    from driftbase.cli.main import cli

    runner = CliRunner()
    result = runner.invoke(cli, ["mcp", "--help"])

    assert result.exit_code == 0
    assert "MCP server" in result.output or "AI assistant" in result.output


def test_cli_mcp_serve_command_exists():
    """CLI mcp serve subcommand exists."""
    from click.testing import CliRunner

    from driftbase.cli.main import cli

    runner = CliRunner()
    result = runner.invoke(cli, ["mcp", "serve", "--help"])

    assert result.exit_code == 0
    assert "serve" in result.output.lower() or "server" in result.output.lower()


def test_mcp_in_command_groups():
    """MCP command is listed in Integrations group."""
    from driftbase.cli.cli import COMMAND_GROUPS

    assert "mcp" in COMMAND_GROUPS.get("Integrations", [])


# Check if mcp is available at module level
try:
    import mcp  # noqa: F401

    MCP_AVAILABLE_FOR_TESTS = True
except ImportError:
    MCP_AVAILABLE_FOR_TESTS = False


# Integration tests that require mcp package (skipped if not installed)


@pytest.mark.skipif(not MCP_AVAILABLE_FOR_TESTS, reason="mcp package not installed")
def test_mcp_server_initialization_with_package():
    """MCPServer initializes when mcp package is available."""
    try:
        from driftbase.mcp.server import MCPServer

        # This will only work if mcp is installed
        server = MCPServer()
        assert server is not None
        assert hasattr(server, "server")
        assert hasattr(server, "_register_tools")
    except ImportError:
        pytest.skip("mcp package not available")


@pytest.mark.skipif(not MCP_AVAILABLE_FOR_TESTS, reason="mcp package not installed")
@pytest.mark.asyncio
async def test_record_run_handler_signature():
    """Verify _handle_record_run has correct signature."""
    try:
        from driftbase.mcp.server import MCPServer

        server = MCPServer()
        assert hasattr(server, "_handle_record_run")
        assert callable(server._handle_record_run)
    except ImportError:
        pytest.skip("mcp package not available")


@pytest.mark.skipif(not MCP_AVAILABLE_FOR_TESTS, reason="mcp package not installed")
@pytest.mark.asyncio
async def test_diagnose_handler_signature():
    """Verify _handle_diagnose has correct signature."""
    try:
        from driftbase.mcp.server import MCPServer

        server = MCPServer()
        assert hasattr(server, "_handle_diagnose")
        assert callable(server._handle_diagnose)
    except ImportError:
        pytest.skip("mcp package not available")


@pytest.mark.skipif(not MCP_AVAILABLE_FOR_TESTS, reason="mcp package not installed")
@pytest.mark.asyncio
async def test_get_history_handler_signature():
    """Verify _handle_get_history has correct signature."""
    try:
        from driftbase.mcp.server import MCPServer

        server = MCPServer()
        assert hasattr(server, "_handle_get_history")
        assert callable(server._handle_get_history)
    except ImportError:
        pytest.skip("mcp package not available")


# Functional tests with mocks


@pytest.mark.skipif(not MCP_AVAILABLE_FOR_TESTS, reason="mcp package not installed")
@pytest.mark.asyncio
async def test_record_run_success():
    """record_run tool handler successfully records a run."""
    try:
        from driftbase.mcp.server import MCPServer

        server = MCPServer()

        # Mock backend
        with patch("driftbase.backends.factory.get_backend") as mock_get_backend:
            mock_backend = Mock()
            mock_get_backend.return_value = mock_backend

            arguments = {
                "session_id": "test-agent",
                "deployment_version": "v1.0",
                "output": "Test output",
                "latency_ms": 100,
                "prompt_tokens": 50,
                "completion_tokens": 75,
                "tool_sequence": ["tool_a", "tool_b"],
                "error": False,
            }

            result = await server._handle_record_run(arguments)

            assert len(result) == 1
            assert result[0].type == "text"

            # Verify backend.write_run was called
            mock_backend.write_run.assert_called_once()
    except ImportError:
        pytest.skip("mcp package not available")


@pytest.mark.skipif(not MCP_AVAILABLE_FOR_TESTS, reason="mcp package not installed")
@pytest.mark.asyncio
async def test_diagnose_insufficient_data():
    """diagnose tool handler returns insufficient_data status when < 40 runs."""
    try:
        from driftbase.mcp.server import MCPServer

        server = MCPServer()

        with patch("driftbase.backends.factory.get_backend") as mock_get_backend:
            mock_backend = Mock()
            mock_backend.get_all_runs.return_value = [
                {"id": f"run-{i}", "session_id": "test-agent"} for i in range(20)
            ]
            mock_get_backend.return_value = mock_backend

            result = await server._handle_diagnose({"agent_id": "test-agent"})

            assert len(result) == 1
            import json

            response = json.loads(result[0].text)
            assert response["status"] == "insufficient_data"
            assert response["run_count"] == 20
    except ImportError:
        pytest.skip("mcp package not available")


@pytest.mark.skipif(not MCP_AVAILABLE_FOR_TESTS, reason="mcp package not installed")
@pytest.mark.asyncio
async def test_get_history_insufficient_data():
    """get_history tool handler returns insufficient_data when < 40 runs."""
    try:
        from driftbase.mcp.server import MCPServer

        server = MCPServer()

        with patch("driftbase.backends.factory.get_backend") as mock_get_backend:
            mock_backend = Mock()
            mock_backend.get_all_runs.return_value = [
                {"id": f"run-{i}", "session_id": "test-agent"} for i in range(30)
            ]
            mock_get_backend.return_value = mock_backend

            result = await server._handle_get_history({"agent_id": "test-agent"})

            import json

            response = json.loads(result[0].text)
            assert response["status"] == "insufficient_data"
            assert response["run_count"] == 30
    except ImportError:
        pytest.skip("mcp package not available")
