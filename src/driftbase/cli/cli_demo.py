import json
import random
import time
from datetime import datetime, timedelta

import click

from driftbase.cli._deps import safe_import_rich
from driftbase.local.local_store import enqueue_run

# Lazy import of heavy [analyze] dependencies
Console, Panel, Table = safe_import_rich()


def generate_synthetic_runs(version: str, count: int, is_regression: bool):
    """Generates synthetic telemetry data with realistic tool sequences and scenarios."""
    now = datetime.utcnow()

    # Realistic tool palette for an AI agent
    TOOLS = {
        "query_database": 0.35,
        "search_documents": 0.25,
        "retrieve_context": 0.20,
        "web_search": 0.10,
        "send_email": 0.05,
        "create_ticket": 0.05,
        "escalate_to_human": 0.03,
        "calculate": 0.08,
        "format_response": 0.30,
        "validate_input": 0.15,
        "parse_json": 0.12,
        "fetch_api": 0.08,
        "summarize": 0.15,
        "translate": 0.03,
        "check_permissions": 0.10,
    }

    # Scenario templates with realistic tool sequences
    BASELINE_SCENARIOS = [
        # Happy path: direct query → format → done (70% of runs)
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
        # Moderate: query → retrieve context → query again → summarize (20%)
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
        # Document search path (15%)
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
        # Complex calculation path (10%)
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
        # Occasional escalation (5%)
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

    REGRESSION_SCENARIOS = [
        # Baseline path but with extra validation loops (40%)
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
        # Web search fallback (agent lost confidence) (25%)
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
        # Excessive API calls and retries (15%)
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
        # Permission issues leading to escalation (20%)
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
        # Critical: agent gets stuck in loop and errors out (10%)
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

    scenarios = BASELINE_SCENARIOS if not is_regression else REGRESSION_SCENARIOS

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
        error_count = random.randint(*error_count) if isinstance(error_count, tuple) else 0

        # Add some randomness: occasionally insert/remove a tool
        if random.random() < 0.15:
            tools.insert(random.randint(0, len(tools)), random.choice(list(TOOLS.keys())))
        if random.random() < 0.10 and len(tools) > 3:
            tools.pop(random.randint(0, len(tools) - 1))

        time_to_first_tool_ms = random.randint(15, 80) if is_regression else random.randint(5, 40)

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

        # Make regression outputs more verbose
        if is_regression and outcome == "resolved":
            output_text = (
                f"{output_text} Additionally, I searched multiple data sources to validate this information. "
                "Let me know if you need any further clarification or additional details."
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
            # New behavioral metrics
            "loop_count": loop_count,
            "tool_call_sequence": json.dumps(tools),
            "time_to_first_tool_ms": time_to_first_tool_ms,
            "verbosity_ratio": verbosity_ratio,
        }
        enqueue_run(payload)


@click.command("demo")
@click.option(
    "--runs",
    "-n",
    type=int,
    default=50,
    help="Number of runs per version (default: 50)",
)
@click.pass_context
def cmd_demo(ctx: click.Context, runs: int) -> None:
    """Inject synthetic runs to instantly see the drift engine in action.

    Generates realistic agent telemetry with varied tool sequences, outcomes,
    and behavioral patterns. v1.0 represents a healthy baseline, v2.0 shows
    a regression with increased latency, verbosity, and escalation rates.

    \b
    Example:
      driftbase demo              # Generate 50 runs per version
      driftbase demo --runs 100   # Generate 100 runs per version
    """
    console: Console = ctx.obj["console"]

    console.print("🧪 [bold cyan]Injecting realistic synthetic telemetry...[/]")
    console.print(
        "[dim]Each version includes varied tool sequences (3-8 tools/run), "
        "multiple outcome types, and realistic behavioral patterns.[/]\n"
    )

    # 1. Generate Baseline
    generate_synthetic_runs("v1.0", runs, is_regression=False)
    console.print(
        f"  ✓ Generated {runs} runs for [bold]v1.0[/] [dim](Baseline: efficient, low escalation)[/]"
    )

    # 2. Generate Regression
    generate_synthetic_runs("v2.0", runs, is_regression=True)
    console.print(
        f"  ✓ Generated {runs} runs for [bold]v2.0[/] [dim](Regression: verbose, slow, high escalation)[/]"
    )

    # Allow background SQLite thread to flush
    time.sleep(1.0)

    console.print("\n[bold green]✓ Success![/] Local database populated.\n")
    console.print("[bold]Try these commands:[/]")
    console.print("  👉 [cyan]driftbase diff v1.0 v2.0[/]")
    console.print("     [dim]See overall drift score, cost impact, and verdict[/]\n")
    console.print("  👉 [cyan]driftbase chart -v v1.0 -m tools[/]")
    console.print("     [dim]Visualize tool usage patterns[/]\n")
    console.print("  👉 [cyan]driftbase compare v1.0 v2.0 --matrix[/]")
    console.print("     [dim]Detailed component-by-component comparison[/]\n")
    console.print("  👉 [cyan]driftbase runs -v v2.0 --slow[/]")
    console.print("     [dim]Inspect slow runs in v2.0[/]\n")
