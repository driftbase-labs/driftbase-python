import json
import os
import random
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import click

from driftbase.cli._deps import safe_import_rich_extended
from driftbase.cli.demo_templates import (
    COST_MODELS,
    FRAMEWORK_TEMPLATES,
    INDUSTRY_BENCHMARKS,
    REGRESSION_TYPES,
    ScenarioTemplate,
)
from driftbase.local.local_store import enqueue_run

# Import rich components (now core dependencies)
Console, Panel, Table, Markdown, Prompt, Confirm = safe_import_rich_extended()


def generate_synthetic_runs(
    version: str,
    count: int,
    scenarios: list[ScenarioTemplate],
    annotate: bool = False,
    console: Any = None,
) -> None:
    """Generates synthetic telemetry data from scenario templates."""
    now = datetime.utcnow()

    for i in range(count):
        # Time distribution over the last hour
        run_time = now - timedelta(minutes=random.randint(1, 60))

        # Weighted scenario selection
        scenario = random.choices(
            scenarios, weights=[s["weight"] for s in scenarios], k=1
        )[0]

        # Generate metrics based on scenario
        tools = scenario["tools"].copy()
        outcome = scenario["outcome"]
        p_tokens = random.randint(*scenario["p_tokens"])
        c_tokens = random.randint(*scenario["c_tokens"])
        latency = random.randint(*scenario["latency"])
        loop_count = random.randint(*scenario["loop_count"])
        retry_count = random.randint(*scenario["retry_count"])
        error_count = scenario.get("error_count", (0, 0))
        error_count = (
            random.randint(*error_count) if isinstance(error_count, tuple) else 0
        )

        # Add some randomness: occasionally insert/remove a tool
        if random.random() < 0.15:
            all_tools = [
                "query_database",
                "search_documents",
                "retrieve_context",
                "web_search",
                "calculate",
                "format_response",
            ]
            tools.insert(random.randint(0, len(tools)), random.choice(all_tools))
        if random.random() < 0.10 and len(tools) > 3:
            tools.pop(random.randint(0, len(tools) - 1))

        time_to_first_tool_ms = random.randint(20, 100)

        # Compute verbosity_ratio
        verbosity_ratio = c_tokens / p_tokens if p_tokens > 0 else 0.0

        # Varied prompts
        prompts = [
            "Find the latest transaction for user ID 8472 and summarize the status.",
            "Check if order #12345 has shipped and provide tracking details.",
            "What was the total revenue for Q3 2023?",
            "Retrieve all support tickets from the last 7 days for account ABC-789.",
            "Calculate the average response time for customer support this month.",
        ]
        outputs = [
            "Transaction TXN-8472 is marked as COMPLETED. Amount: €450.00.",
            "Order #12345 shipped on 2024-03-15. Tracking: TRK-999888777.",
            "Q3 2023 revenue: €1,245,890.50 (+12% vs Q2).",
            "Found 47 support tickets for account ABC-789 in the last 7 days.",
            "Average customer support response time this month: 2.3 hours.",
        ]

        prompt_text = random.choice(prompts)
        output_text = random.choice(outputs)

        # Annotate if requested
        if annotate and console and i % 10 == 0:
            console.print(
                f"[dim]Run {i + 1}/{count}: {outcome} ({len(tools)} tools, {latency}ms)[/]"
            )

        payload = {
            "session_id": f"demo_session_{version}_{i}",
            "deployment_version": version,
            "environment": "production",
            "started_at": run_time,
            "completed_at": run_time + timedelta(milliseconds=latency),
            "task_input_hash": f"hash_{random.randint(1000, 9999)}",
            "tool_sequence": json.dumps(tools),
            "tool_call_count": len(tools),
            "output_length": c_tokens * 4,
            "output_structure_hash": f"struct_hash_{random.randint(100, 999)}",
            "latency_ms": latency,
            "error_count": error_count,
            "retry_count": retry_count,
            "semantic_cluster": outcome,
            "prompt_tokens": p_tokens,
            "completion_tokens": c_tokens,
            "raw_prompt": prompt_text,
            "raw_output": output_text,
            "loop_count": loop_count,
            "time_to_first_tool_ms": time_to_first_tool_ms,
            "verbosity_ratio": verbosity_ratio,
        }
        enqueue_run(payload)


def get_baseline_regression_scenarios(
    regression_type: str | None, framework: str | None
) -> tuple[list[ScenarioTemplate], list[ScenarioTemplate]]:
    """Get baseline and regression scenarios based on type or framework."""

    # Framework-specific templates
    if framework and framework in FRAMEWORK_TEMPLATES:
        template = FRAMEWORK_TEMPLATES[framework]
        return template["baseline_scenarios"], template["regression_scenarios"]

    # Regression type gallery
    if regression_type and regression_type in REGRESSION_TYPES:
        # Create baseline scenarios (efficient versions)
        baseline = [
            {
                "weight": 0.70,
                "tools": ["validate_input", "query_database", "format_response"],
                "outcome": "resolved",
                "p_tokens": (350, 500),
                "c_tokens": (40, 80),
                "latency": (250, 450),
                "loop_count": (1, 2),
                "retry_count": (0, 0),
            },
            {
                "weight": 0.20,
                "tools": [
                    "validate_input",
                    "query_database",
                    "retrieve_context",
                    "format_response",
                ],
                "outcome": "resolved",
                "p_tokens": (450, 650),
                "c_tokens": (50, 100),
                "latency": (350, 600),
                "loop_count": (2, 3),
                "retry_count": (0, 1),
            },
            {
                "weight": 0.05,
                "tools": [
                    "validate_input",
                    "query_database",
                    "escalate_to_human",
                ],
                "outcome": "escalated",
                "p_tokens": (400, 600),
                "c_tokens": (30, 60),
                "latency": (350, 600),
                "loop_count": (2, 3),
                "retry_count": (0, 1),
            },
            {
                "weight": 0.05,
                "tools": ["validate_input", "query_database"],
                "outcome": "error",
                "p_tokens": (350, 550),
                "c_tokens": (20, 50),
                "latency": (300, 550),
                "loop_count": (1, 2),
                "retry_count": (1, 2),
                "error_count": (1, 1),
            },
        ]
        regression = REGRESSION_TYPES[regression_type]["scenarios"]
        return baseline, regression

    # Default scenarios (original demo behavior)
    baseline = [
        {
            "weight": 0.50,
            "tools": ["validate_input", "query_database", "format_response"],
            "outcome": "resolved",
            "p_tokens": (350, 500),
            "c_tokens": (40, 80),
            "latency": (250, 450),
            "loop_count": (1, 2),
            "retry_count": (0, 0),
        },
        {
            "weight": 0.20,
            "tools": [
                "validate_input",
                "query_database",
                "retrieve_context",
                "query_database",
                "summarize",
                "format_response",
            ],
            "outcome": "resolved",
            "p_tokens": (500, 700),
            "c_tokens": (60, 110),
            "latency": (400, 700),
            "loop_count": (2, 3),
            "retry_count": (0, 1),
        },
        {
            "weight": 0.15,
            "tools": [
                "validate_input",
                "search_documents",
                "retrieve_context",
                "summarize",
                "format_response",
            ],
            "outcome": "resolved",
            "p_tokens": (450, 650),
            "c_tokens": (50, 100),
            "latency": (350, 600),
            "loop_count": (2, 3),
            "retry_count": (0, 1),
        },
        {
            "weight": 0.10,
            "tools": [
                "validate_input",
                "query_database",
                "calculate",
                "calculate",
                "format_response",
            ],
            "outcome": "resolved",
            "p_tokens": (400, 600),
            "c_tokens": (45, 85),
            "latency": (300, 550),
            "loop_count": (2, 3),
            "retry_count": (0, 1),
        },
        {
            "weight": 0.05,
            "tools": [
                "validate_input",
                "query_database",
                "check_permissions",
                "escalate_to_human",
            ],
            "outcome": "escalated",
            "p_tokens": (400, 600),
            "c_tokens": (30, 60),
            "latency": (350, 600),
            "loop_count": (2, 3),
            "retry_count": (0, 1),
        },
    ]

    regression = [
        {
            "weight": 0.30,
            "tools": [
                "validate_input",
                "query_database",
                "retrieve_context",
                "validate_input",
                "query_database",
                "format_response",
                "format_response",
            ],
            "outcome": "resolved",
            "p_tokens": (700, 1000),
            "c_tokens": (120, 200),
            "latency": (900, 1500),
            "loop_count": (4, 6),
            "retry_count": (1, 2),
        },
        {
            "weight": 0.25,
            "tools": [
                "validate_input",
                "query_database",
                "web_search",
                "web_search",
                "retrieve_context",
                "query_database",
                "summarize",
                "format_response",
            ],
            "outcome": "resolved",
            "p_tokens": (900, 1200),
            "c_tokens": (150, 250),
            "latency": (1200, 2000),
            "loop_count": (5, 8),
            "retry_count": (2, 3),
        },
        {
            "weight": 0.20,
            "tools": [
                "validate_input",
                "check_permissions",
                "query_database",
                "check_permissions",
                "retrieve_context",
                "escalate_to_human",
            ],
            "outcome": "escalated",
            "p_tokens": (750, 1050),
            "c_tokens": (100, 180),
            "latency": (950, 1600),
            "loop_count": (4, 6),
            "retry_count": (1, 2),
        },
        {
            "weight": 0.15,
            "tools": [
                "validate_input",
                "fetch_api",
                "fetch_api",
                "parse_json",
                "query_database",
                "retrieve_context",
                "summarize",
                "format_response",
            ],
            "outcome": "resolved",
            "p_tokens": (800, 1100),
            "c_tokens": (140, 220),
            "latency": (1000, 1700),
            "loop_count": (4, 7),
            "retry_count": (2, 4),
        },
        {
            "weight": 0.10,
            "tools": [
                "validate_input",
                "query_database",
                "web_search",
                "query_database",
                "web_search",
                "retrieve_context",
                "web_search",
            ],
            "outcome": "error",
            "p_tokens": (1000, 1300),
            "c_tokens": (80, 150),
            "latency": (1500, 2500),
            "loop_count": (6, 10),
            "retry_count": (3, 5),
            "error_count": (1, 2),
        },
    ]

    return baseline, regression


def interactive_tutorial(console: Any, runs: int) -> None:
    """Interactive step-by-step tutorial mode."""
    console.print(
        Panel(
            "[bold cyan]🎓 Welcome to the Driftbase Interactive Tutorial![/]\n\n"
            "This guided walkthrough will teach you how to detect and analyze\n"
            "behavioral drift in AI agents. We'll generate data, run diffs, and\n"
            "interpret the results together.\n\n"
            "[dim]Press Enter to continue...[/]",
            title="Tutorial Mode",
            border_style="#8B5CF6",
        )
    )
    input()

    # Step 1: Explain what we're about to generate
    console.print("\n[bold]Step 1: Understanding Baseline vs Regression[/]\n")
    console.print(
        "We'll generate two versions of agent data:\n"
        "  • #4ADE80]v1.0 (Baseline)[/]: Efficient agent with low latency, minimal token usage\n"
        "  • #FF6B6B]v2.0 (Regression)[/]: Same agent after changes caused performance issues\n"
    )
    console.print(
        "\n#FFA94D]💡 Key Metrics We Track:[/]\n"
        "  • #8B5CF6]Tool sequences[/]: Which tools are called and in what order\n"
        "  • #8B5CF6]Token usage[/]: Prompt + completion tokens (affects cost)\n"
        "  • #8B5CF6]Latency[/]: Response time (affects user experience)\n"
        "  • #8B5CF6]Loop count[/]: How many reasoning iterations\n"
        "  • #8B5CF6]Retry count[/]: Failed tool calls requiring retries\n"
        "  • #8B5CF6]Escalation rate[/]: How often agent gives up\n"
    )
    console.print("\n[dim]Press Enter to generate baseline data...[/]")
    input()

    # Generate baseline
    console.print(f"\n#8B5CF6]Generating {runs} baseline runs (v1.0)...[/]")
    baseline, regression = get_baseline_regression_scenarios(None, None)
    generate_synthetic_runs("v1.0", runs, baseline, annotate=True, console=console)
    time.sleep(0.5)
    console.print("#4ADE80]✓ Baseline complete![/]\n")

    # Step 2: Explain regression
    console.print("[bold]Step 2: Simulating a Regression[/]\n")
    console.print(
        "Now we'll generate v2.0 data with these problems:\n"
        "  • #FF6B6B]Excessive loops[/]: Agent retries operations unnecessarily\n"
        "  • #FF6B6B]Tool sequence changes[/]: Different problem-solving approach\n"
        "  • #FF6B6B]Higher escalation rate[/]: Agent gives up more often\n"
        "  • #FF6B6B]Token bloat[/]: Wordier outputs without added value\n"
    )
    console.print("\n[dim]Press Enter to generate regression data...[/]")
    input()

    console.print(f"\n#8B5CF6]Generating {runs} regression runs (v2.0)...[/]")
    generate_synthetic_runs("v2.0", runs, regression, annotate=True, console=console)
    time.sleep(0.5)
    console.print("#4ADE80]✓ Regression complete![/]\n")

    # Step 3: Run the diff
    console.print("[bold]Step 3: Detecting Drift[/]\n")
    console.print(
        "Let's compare the two versions using the diff command.\n"
        "The drift score ranges from 0.0 (identical) to 1.0 (completely different).\n"
    )
    console.print("\n[dim]Press Enter to run: driftbase diff v1.0 v2.0[/]")
    input()

    console.print("\n#8B5CF6]Running drift detection...[/]\n")
    time.sleep(1)
    console.print("[bold green]Now run:[/] #8B5CF6]driftbase diff v1.0 v2.0[/]\n")

    # Step 4: What to look for
    console.print("[bold]Step 4: Interpreting Results[/]\n")
    console.print("In the diff output, pay attention to:\n")
    console.print(
        "  1. #FFA94D]Overall drift score[/]: Is it above your threshold (default: 0.20)?\n"
        "  2. #FFA94D]Component scores[/]: Which dimension drifted most?\n"
        "     • Decisions (escalation rate)\n"
        "     • Latency (p95 response time)\n"
        "     • Tool sequences (behavioral changes)\n"
        "  3. #FFA94D]Financial impact[/]: How much will this cost per 10k runs?\n"
        "  4. #FFA94D]Verdict & root cause[/]: Plain-English explanation\n"
    )

    # Step 5: Next steps
    console.print("\n[bold]Step 5: Exploring Further[/]\n")
    console.print("Try these commands to dive deeper:\n")
    console.print(
        "  • #8B5CF6]driftbase runs -v v2.0 --slow[/]\n"
        "    [dim]Inspect slow runs to understand latency regression[/]\n"
    )
    console.print(
        "  • #8B5CF6]driftbase chart -v v1.0 -m tools[/]\n"
        "    [dim]Visualize tool usage patterns in baseline[/]\n"
    )
    console.print(
        "  • #8B5CF6]driftbase compare v1.0 v2.0 --matrix[/]\n"
        "    [dim]Detailed component-by-component breakdown[/]\n"
    )
    console.print(
        "  • #8B5CF6]driftbase cost -v v2.0[/]\n"
        "    [dim]Detailed cost analysis with projections[/]\n"
    )

    console.print(
        "\n[bold green]🎉 Tutorial complete![/] You're ready to use Driftbase on real agents.\n"
    )


def export_fixtures(console: Any, format_type: str, output_dir: str) -> None:
    """Export test fixtures for integration testing."""
    from driftbase.backends.factory import get_backend

    backend = get_backend()

    # Get runs for both versions
    v1_runs = backend.get_runs("v1.0", limit=50)
    v2_runs = backend.get_runs("v2.0", limit=50)

    if not v1_runs or not v2_runs:
        console.print(
            "#FFA94D]No demo data found. Run 'driftbase demo' first.[/]",
            style="#FFA94D",
        )
        return

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    if format_type == "pytest":
        # Generate pytest fixtures
        fixture_content = f'''"""
Auto-generated test fixtures from driftbase demo data.
Generated: {datetime.utcnow().isoformat()}
"""

import pytest
from typing import Dict, List, Any


@pytest.fixture
def baseline_runs() -> List[Dict[str, Any]]:
    """v1.0 baseline runs for drift detection tests."""
    return {json.dumps(v1_runs[:10], indent=4, default=str)}


@pytest.fixture
def regression_runs() -> List[Dict[str, Any]]:
    """v2.0 regression runs for drift detection tests."""
    return {json.dumps(v2_runs[:10], indent=4, default=str)}


@pytest.fixture
def expected_drift_score() -> float:
    """Expected drift score for test validation."""
    return 0.28  # Moderate drift expected


def test_detects_drift(baseline_runs, regression_runs, expected_drift_score):
    """Test that drift detection identifies regression."""
    from driftbase.stats.drift import compute_drift_score

    drift = compute_drift_score(baseline_runs, regression_runs)
    assert drift >= expected_drift_score, f"Expected drift >= {{expected_drift_score}}, got {{drift}}"


def test_detects_latency_regression(regression_runs):
    """Test that latency increased in regression."""
    avg_latency = sum(r["latency_ms"] for r in regression_runs) / len(regression_runs)
    assert avg_latency > 800, f"Expected latency > 800ms, got {{avg_latency}}ms"


def test_detects_token_bloat(baseline_runs, regression_runs):
    """Test that token usage increased in regression."""
    baseline_tokens = sum(r["completion_tokens"] for r in baseline_runs) / len(baseline_runs)
    regression_tokens = sum(r["completion_tokens"] for r in regression_runs) / len(regression_runs)
    increase = (regression_tokens - baseline_tokens) / baseline_tokens
    assert increase > 0.5, f"Expected >50% token increase, got {{increase:.1%}}"
'''

        fixture_file = output_path / "test_fixtures.py"
        fixture_file.write_text(fixture_content)
        console.print(f"#4ADE80]✓ Generated pytest fixtures:[/] {fixture_file}")

    elif format_type == "json":
        # Generate JSON fixtures
        fixtures = {
            "schema_version": "1.0",
            "generated_at": datetime.utcnow().isoformat(),
            "baseline": {"version": "v1.0", "runs": v1_runs[:20]},
            "regression": {"version": "v2.0", "runs": v2_runs[:20]},
        }

        fixture_file = output_path / "drift_fixtures.json"
        fixture_file.write_text(json.dumps(fixtures, indent=2, default=str))
        console.print(f"#4ADE80]✓ Generated JSON fixtures:[/] {fixture_file}")


def show_cost_impact(
    console: Any, runs: int, cost_model: str, volume_per_month: int
) -> None:
    """Show detailed cost impact projection at scale."""
    from driftbase.backends.factory import get_backend

    backend = get_backend()

    # Get runs
    v1_runs = backend.get_runs("v1.0", limit=runs)
    v2_runs = backend.get_runs("v2.0", limit=runs)

    if not v1_runs or not v2_runs:
        console.print("#FFA94D]No demo data found. Run without --cost-model first.[/]")
        return

    # Get cost model
    model = COST_MODELS.get(cost_model, COST_MODELS["standard"])

    # Calculate average token usage
    v1_avg_prompt = sum(r.get("prompt_tokens", 0) for r in v1_runs) / len(v1_runs)
    v1_avg_completion = sum(r.get("completion_tokens", 0) for r in v1_runs) / len(
        v1_runs
    )
    v2_avg_prompt = sum(r.get("prompt_tokens", 0) for r in v2_runs) / len(v2_runs)
    v2_avg_completion = sum(r.get("completion_tokens", 0) for r in v2_runs) / len(
        v2_runs
    )

    # Cost per run
    v1_cost_per_run = (
        v1_avg_prompt / 1_000_000 * model["rate_prompt_1m"]
        + v1_avg_completion / 1_000_000 * model["rate_completion_1m"]
    )
    v2_cost_per_run = (
        v2_avg_prompt / 1_000_000 * model["rate_prompt_1m"]
        + v2_avg_completion / 1_000_000 * model["rate_completion_1m"]
    )

    # Monthly costs
    v1_monthly = v1_cost_per_run * volume_per_month
    v2_monthly = v2_cost_per_run * volume_per_month
    delta_monthly = v2_monthly - v1_monthly
    delta_pct = ((v2_monthly - v1_monthly) / v1_monthly * 100) if v1_monthly > 0 else 0

    # Display
    console.print(
        Panel(
            f"[bold]Cost Model:[/] {model['name']}\n"
            f"[dim]{model['description']}[/]\n\n"
            f"[bold]Rates:[/]\n"
            f"  Prompt tokens: €{model['rate_prompt_1m']:.2f} per 1M\n"
            f"  Completion tokens: €{model['rate_completion_1m']:.2f} per 1M\n\n"
            f"[bold]Volume:[/] {volume_per_month:,} runs/month",
            title="💰 Cost Impact Simulator",
            border_style="#FFA94D",
        )
    )

    table = Table(show_header=True, header_style="bold", title="\nPer-Run Breakdown")
    table.add_column("Version")
    table.add_column("Prompt Tokens", justify="right")
    table.add_column("Completion Tokens", justify="right")
    table.add_column("Cost/Run", justify="right")

    table.add_row(
        "#4ADE80]v1.0[/]",
        f"{v1_avg_prompt:.0f}",
        f"{v1_avg_completion:.0f}",
        f"€{v1_cost_per_run:.4f}",
    )
    table.add_row(
        "#FF6B6B]v2.0[/]",
        f"{v2_avg_prompt:.0f}",
        f"{v2_avg_completion:.0f}",
        f"€{v2_cost_per_run:.4f}",
    )
    console.print(table)

    # Monthly projection
    console.print(
        Panel(
            f"[bold]v1.0 Baseline:[/] €{v1_monthly:,.2f}/month\n"
            f"[bold]v2.0 Regression:[/] €{v2_monthly:,.2f}/month\n\n"
            f"[bold {'#FF6B6B' if delta_monthly > 0 else '#4ADE80'}]Delta:[/] "
            f"€{delta_monthly:+,.2f}/month ({delta_pct:+.1f}%)\n\n"
            f"[#FFA94D]💡 Projected Annual Impact:[/] €{delta_monthly * 12:,.2f}/year",
            title="📊 Monthly Cost Projection",
            border_style="#FF6B6B" if delta_monthly > 0 else "#4ADE80",
        )
    )


@click.command("demo")
@click.option(
    "--runs",
    "-n",
    type=int,
    default=50,
    help="Number of runs per version (default: 50)",
)
@click.option(
    "--quick",
    is_flag=True,
    help="Quick mode: 10 runs per version (~5 seconds total)",
)
@click.option(
    "--regression-type",
    type=click.Choice(list(REGRESSION_TYPES.keys())),
    help="Specific regression pattern to demonstrate",
)
@click.option(
    "--template",
    type=click.Choice(list(FRAMEWORK_TEMPLATES.keys())),
    help="Framework-specific agent template",
)
@click.option(
    "--scenario",
    type=click.Path(exists=True),
    help="Path to custom YAML scenario file",
)
@click.option(
    "--init-scenario",
    type=click.Path(),
    help="Generate template YAML scenario at path",
)
@click.option(
    "--interactive",
    is_flag=True,
    help="Interactive tutorial mode with step-by-step guidance",
)
@click.option(
    "--cost-model",
    type=click.Choice(list(COST_MODELS.keys())),
    help="Show cost impact with specific pricing model",
)
@click.option(
    "--volume",
    type=int,
    default=100000,
    help="Monthly run volume for cost projections (default: 100k)",
)
@click.option(
    "--verbose",
    is_flag=True,
    help="Show detailed technical output (disables narrative mode)",
)
@click.pass_context
def cmd_demo(
    ctx: click.Context,
    runs: int,
    quick: bool,
    regression_type: str | None,
    template: str | None,
    scenario: str | None,
    init_scenario: str | None,
    interactive: bool,
    cost_model: str | None,
    volume: int,
    verbose: bool,
) -> None:
    """Generate synthetic runs to explore Driftbase.

    \b
    Basic Usage:
      driftbase demo                     # Standard demo (50 runs each)
      driftbase demo --quick             # Fast demo (10 runs, ~5 seconds)
      driftbase demo --runs 100          # Custom run count

    \b
    Regression Gallery:
      driftbase demo --regression-type token-bloat      # Excessive verbosity
      driftbase demo --regression-type loop-detection   # Stuck in retry cycles
      driftbase demo --regression-type tool-dropout     # Missing critical tools
      driftbase demo --regression-type cost-explosion   # 3-5x token usage
      driftbase demo --regression-type latency-creep    # Slow performance

    \b
    Framework Templates:
      driftbase demo --template langgraph-rag           # RAG pipeline
      driftbase demo --template autogen-research        # Multi-agent research
      driftbase demo --template crewai-customer-support # Support bot
      driftbase demo --template code-generation         # Code gen agent

    \b
    Custom Scenarios:
      driftbase demo --init-scenario ./my_scenario.yaml # Generate template
      driftbase demo --scenario ./my_scenario.yaml      # Use custom scenario

    \b
    Learning:
      driftbase demo --interactive       # Step-by-step tutorial

    \b
    Cost Analysis:
      driftbase demo --cost-model enterprise --volume 100000
      driftbase demo --cost-model budget --volume 50000
    """
    console: Console = ctx.obj["console"]

    # Handle scenario template generation
    if init_scenario:
        from driftbase.cli.demo_scenario_loader import generate_template_yaml

        generate_template_yaml(init_scenario)
        console.print(
            f"#4ADE80]✓ Generated scenario template:[/] {init_scenario}\n"
            f"[dim]Edit the template and run with: driftbase demo --scenario {init_scenario}[/]"
        )
        return

    # Quick mode overrides
    if quick:
        runs = 10

    # Narrative mode (default, unless --verbose or customization flags are used)
    is_narrative_mode = not verbose and all(
        [
            scenario is None,
            regression_type is None,
            template is None,
            cost_model is None,
        ]
    )

    if is_narrative_mode:
        from driftbase.cli.demo_narrative import run_narrative_demo

        run_narrative_demo(ctx, quick, interactive)
        return

    # Interactive tutorial mode (legacy, for verbose/customized demos)
    if interactive:
        interactive_tutorial(console, runs)
        return

    # Get scenarios based on input
    baseline = None
    regression = None

    # Priority 1: Custom YAML scenario
    if scenario:
        from driftbase.cli.demo_scenario_loader import load_yaml_scenario

        try:
            baseline, regression = load_yaml_scenario(scenario)
            console.print(f"#4ADE80]✓ Loaded custom scenario from:[/] {scenario}\n")
        except Exception as e:
            console.print(f"#FF6B6B]Error loading scenario:[/] {e}")
            return

    # Priority 2: Predefined regression type or framework template
    else:
        baseline, regression = get_baseline_regression_scenarios(
            regression_type, template
        )

    # Show what we're generating
    if regression_type:
        rt = REGRESSION_TYPES[regression_type]
        console.print(
            Panel(
                f"[bold]{rt['name']}[/]\n\n{rt['description']}\n\n"
                f"#FFA94D]Expected Drift:[/]\n"
                + "\n".join(f"  • {k}: {v}" for k, v in rt["expected_drift"].items()),
                title="🧪 Regression Type Demo",
                border_style="#8B5CF6",
            )
        )
    elif template:
        tmpl = FRAMEWORK_TEMPLATES[template]
        console.print(
            Panel(
                f"[bold]{tmpl['name']}[/]\n\n{tmpl['description']}\n\n"
                f"#8B5CF6]Tools:[/] {', '.join(tmpl['tools'][:5])}...",
                title="🔧 Framework Template",
                border_style="#8B5CF6",
            )
        )
    else:
        console.print("🧪 [bold cyan]Injecting realistic synthetic telemetry...[/]")
        if quick:
            console.print("[dim]Quick mode: 10 runs per version (~5 seconds)[/]\n")
        else:
            console.print(
                f"[dim]Generating {runs} runs per version with varied patterns[/]\n"
            )

    # Generate baseline
    console.print(f"  ✓ Generating {runs} runs for [bold]v1.0[/] [dim](Baseline)[/]")
    generate_synthetic_runs("v1.0", runs, baseline, annotate=False, console=console)

    # Generate regression
    console.print(f"  ✓ Generating {runs} runs for [bold]v2.0[/] [dim](Regression)[/]")
    generate_synthetic_runs("v2.0", runs, regression, annotate=False, console=console)

    # Allow background SQLite thread to flush
    time.sleep(1.0)

    console.print("\n[bold green]✓ Success![/] Local database populated.\n")

    # Show cost impact if requested
    if cost_model:
        console.print()
        show_cost_impact(console, runs, cost_model, volume)
        console.print()

    # Show next steps
    console.print("[bold]Try these commands:[/]")
    console.print("  👉 #8B5CF6]driftbase diff v1.0 v2.0[/]")
    console.print("     [dim]See overall drift score, cost impact, and verdict[/]\n")

    if regression_type == "latency-creep":
        console.print("  👉 #8B5CF6]driftbase runs -v v2.0 --slow[/]")
        console.print("     [dim]Inspect slow runs to understand latency issues[/]\n")
    elif regression_type == "tool-dropout":
        console.print("  👉 #8B5CF6]driftbase chart -v v1.0 -m tools[/]")
        console.print("     [dim]Compare tool usage: what's missing in v2.0?[/]\n")
    else:
        console.print("  👉 #8B5CF6]driftbase compare v1.0 v2.0 --matrix[/]")
        console.print("     [dim]Detailed component-by-component comparison[/]\n")

    console.print("  👉 #8B5CF6]driftbase cost -v v2.0[/]")
    console.print("     [dim]Analyze cost impact with projections[/]\n")
