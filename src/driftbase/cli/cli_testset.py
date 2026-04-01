"""
CLI commands for managing and generating test query sets.
Provides list, inspect, and generate commands for the 14 built-in use cases.
"""

from __future__ import annotations

import importlib.resources
import json
import logging
from datetime import datetime
from pathlib import Path

import click
import yaml

from driftbase.cli._deps import safe_import_rich
from driftbase.local.use_case_inference import USE_CASE_WEIGHTS

logger = logging.getLogger(__name__)

# Import rich components (now core dependencies)
Console, Panel, Table = safe_import_rich()


def _load_testset(use_case: str) -> dict | None:
    """Load testset YAML for a given use case."""
    try:
        # Convert uppercase USE_CASE to lowercase snake_case for filename
        use_case_lower = use_case.lower()

        # Python 3.9+ importlib.resources API
        files = importlib.resources.files("driftbase.testsets")
        testset_file = files / f"{use_case_lower}.yaml"

        if testset_file.is_file():
            content = testset_file.read_text()
            return yaml.safe_load(content)
        return None
    except Exception as e:
        logger.debug(f"Failed to load testset {use_case}: {e}")
        return None


@click.group("testset")
def cmd_testset() -> None:
    """Generate test queries for your agent type."""
    pass


@cmd_testset.command("list")
@click.pass_context
def cmd_list(ctx: click.Context) -> None:
    """List all available test query sets."""
    console: Console = ctx.obj["console"]

    table = Table(
        title="[bold]Available Test Query Sets[/]",
        show_header=True,
        header_style="bold cyan",
    )
    table.add_column("Use Case", style="cyan", width=20)
    table.add_column("Description", style="white", width=60)
    table.add_column("Total", justify="right", style="green")

    # Load all testsets
    for use_case_name in USE_CASE_WEIGHTS:
        testset = _load_testset(use_case_name)
        if testset:
            table.add_row(
                use_case_name,
                testset.get("description", ""),
                str(testset.get("total", 0)),
            )

    console.print(table)
    console.print(
        "\n[dim]Run [bold]driftbase testset inspect --use-case <name>[/] to preview queries.[/]"
    )


@cmd_testset.command("inspect")
@click.option(
    "--use-case",
    type=str,
    required=True,
    help="Use case to inspect (e.g., customer_support, code_generation)",
)
@click.pass_context
def cmd_inspect(ctx: click.Context, use_case: str) -> None:
    """Preview queries from a specific test set."""
    console: Console = ctx.obj["console"]

    testset = _load_testset(use_case)
    if not testset:
        console.print(
            Panel(
                f"Test set not found: [bold]{use_case}[/]\n\n"
                f"Run [bold]driftbase testset list[/] to see available sets.",
                title="Error",
                border_style="red",
            )
        )
        ctx.exit(1)

    # Header
    console.print(
        Panel(
            f"[bold]{testset['description']}[/]\n"
            f"Total queries: [bold green]{testset['total']}[/]",
            title=f"[bold cyan]{use_case.upper()}[/]",
            border_style="cyan",
        )
    )

    # Show queries by category
    categories = testset.get("categories", {})
    for category_name, category_data in categories.items():
        queries = category_data.get("queries", [])
        count = category_data.get("count", len(queries))

        table = Table(
            title=f"[bold]{category_name.replace('_', ' ').title()}[/] ({count} queries)",
            show_header=False,
            box=None,
            padding=(0, 2),
        )

        # Show first 3 queries as preview
        for i, query in enumerate(queries[:3], 1):
            table.add_row(f"[dim]{i}.[/]", query)

        if len(queries) > 3:
            table.add_row("[dim]...[/]", f"[dim]and {len(queries) - 3} more[/]")

        console.print(table)
        console.print()


@cmd_testset.command("generate")
@click.option(
    "--use-case",
    type=str,
    help="Use case to generate queries for (e.g., customer_support). If not provided, infers from recent runs.",
)
@click.option(
    "--output",
    type=click.Path(),
    default="test_queries.py",
    help="Output file path (default: test_queries.py)",
)
@click.option(
    "--version",
    type=str,
    default="baseline",
    help="Deployment version for tracking (default: baseline)",
)
@click.pass_context
def cmd_generate(
    ctx: click.Context, use_case: str | None, output: str, version: str
) -> None:
    """Generate a ready-to-run Python script for testing an agent."""
    console: Console = ctx.obj["console"]

    # If no use case provided, try to infer from recent runs
    if not use_case:
        from driftbase.backends.factory import get_backend
        from driftbase.local.use_case_inference import infer_use_case

        backend = get_backend()
        runs = backend.get_all_runs(limit=100)

        if not runs:
            console.print(
                Panel(
                    "No recent runs found for use case inference.\n\n"
                    "Please specify --use-case explicitly or run your agent first.",
                    title="Error",
                    border_style="red",
                )
            )
            ctx.exit(1)

        # Infer from recent runs
        inferred = infer_use_case(runs)
        use_case = inferred.use_case
        console.print(
            f"[dim]Inferred use case from recent runs: [bold]{use_case}[/][/]\n"
        )

    # Load testset
    testset = _load_testset(use_case)
    if not testset:
        console.print(
            Panel(
                f"Test set not found: [bold]{use_case}[/]\n\n"
                f"Run [bold]driftbase testset list[/] to see available sets.",
                title="Error",
                border_style="red",
            )
        )
        ctx.exit(1)

    # Collect all queries
    all_queries = []
    categories = testset.get("categories", {})
    for category_name, category_data in categories.items():
        queries = category_data.get("queries", [])
        for query in queries:
            all_queries.append(
                {"query": query, "category": category_name, "use_case": use_case}
            )

    # Generate Python script
    script_content = f'''"""
Auto-generated test queries for {use_case} use case.
Generated: {datetime.now().isoformat()}
Total queries: {len(all_queries)}

Instructions:
1. Replace YOUR_AGENT_FUNCTION with your actual agent implementation
2. Ensure driftbase.track() decorator is applied to your agent function
3. Run this script: python {Path(output).name}
4. View results: driftbase diff --use-case {use_case}
"""

from driftbase import track

# Replace this with your actual agent implementation
@track(deployment_version="{version}")
def YOUR_AGENT_FUNCTION(user_query: str) -> str:
    """
    Your agent implementation goes here.

    Args:
        user_query: The user's input query

    Returns:
        The agent's response as a string
    """
    # Example placeholder - replace with your actual agent logic
    # This could be:
    # - A call to OpenAI/Anthropic API
    # - A LangChain chain execution
    # - A custom agent framework
    # - Any other agent implementation

    raise NotImplementedError(
        "Replace YOUR_AGENT_FUNCTION with your actual agent implementation"
    )


def main():
    """Run all test queries through the agent."""
    queries = {json.dumps(all_queries, indent=8)}

    print(f"Running {{len(queries)}} test queries for {use_case}...")
    print(f"Deployment version: {version}\\n")

    for i, test_case in enumerate(queries, 1):
        query = test_case["query"]
        category = test_case["category"]

        print(f"[{{i}}/{{len(queries)}}] {{category}}: {{query[:60]}}...")

        try:
            result = YOUR_AGENT_FUNCTION(query)
            print(f"  ✓ Success\\n")
        except NotImplementedError:
            print("\\n⚠️  Please implement YOUR_AGENT_FUNCTION before running this script.\\n")
            return
        except Exception as e:
            print(f"  ✗ Error: {{e}}\\n")

    print(f"\\n✓ Completed {{len(queries)}} test queries")
    print(f"\\nNext steps:")
    print(f"  1. Run: driftbase diff --use-case {use_case}")
    print(f"  2. Review drift analysis and confidence metrics")
    print(f"  3. Iterate on your agent and re-run this script")


if __name__ == "__main__":
    main()
'''

    # Write to file
    output_path = Path(output)
    output_path.write_text(script_content)

    console.print(
        Panel(
            f"[bold green]✓[/] Generated test script with [bold]{len(all_queries)}[/] queries\n\n"
            f"[bold cyan]File:[/] {output}\n"
            f"[bold cyan]Use case:[/] {use_case}\n"
            f"[bold cyan]Version:[/] {version}\n\n"
            f"[bold]Next steps:[/]\n"
            f"  1. Edit [bold]{output}[/] and replace YOUR_AGENT_FUNCTION\n"
            f"  2. Run: [bold]python {output}[/]\n"
            f"  3. Analyze: [bold]driftbase diff --use-case {use_case}[/]",
            title="Test Script Generated",
            border_style="green",
        )
    )
