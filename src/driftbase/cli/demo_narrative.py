"""
Narrative demo mode for driftbase.

This module provides an educational, narrative-driven demo experience that teaches
the Capture → Fingerprint → Diff → Report loop through its output.
"""

import json
import subprocess
import sys
import time
from typing import Any

import click

from driftbase.cli.demo_templates import ScenarioTemplate
from driftbase.local.local_store import enqueue_run

# ============================================================================
# HARDCODED DEMO SCENARIO DATA
# ============================================================================

SCENARIO_NAME = "Refund Request Agent"
SCENARIO_DESCRIPTION = """Scenario: An AI agent that handles customer refund requests.
  Version 1 (baseline): Empathetic, follows policy strictly.
  Version 2 (variant):  Prompt tweaked to be more assertive and concise."""

BASELINE_PROMPT = "Be empathetic and helpful. Always follow the refund policy."
VARIANT_PROMPT = "Be direct and efficient. Approve or deny quickly."

# Number of runs (minimum for statistical significance)
DEFAULT_RUNS = 50
QUICK_RUNS = 20


# ============================================================================
# REFUND AGENT SCENARIO TEMPLATES
# ============================================================================


def get_refund_agent_scenarios() -> tuple[
    list[ScenarioTemplate], list[ScenarioTemplate]
]:
    """
    Get baseline and variant scenarios for the Refund Request Agent.

    Baseline (empathetic): Longer responses, more validation steps, empathetic tone
    Variant (direct): Shorter responses, fewer steps, concise tone
    """

    # BASELINE: Empathetic agent - longer, more thorough
    baseline = [
        {
            "weight": 0.60,
            "tools": [
                "validate_request",
                "check_policy",
                "retrieve_order_history",
                "calculate_refund_amount",
                "send_confirmation_email",
            ],
            "outcome": "resolved",
            "p_tokens": (420, 480),
            "c_tokens": (160, 200),  # Longer, empathetic responses
            "latency": (400, 500),
            "loop_count": (1, 2),
            "retry_count": (0, 0),
        },
        {
            "weight": 0.20,
            "tools": [
                "validate_request",
                "check_policy",
                "retrieve_order_history",
                "check_exceptions",
                "escalate_to_supervisor",
            ],
            "outcome": "escalated",
            "p_tokens": (440, 500),
            "c_tokens": (140, 180),
            "latency": (450, 550),
            "loop_count": (2, 3),
            "retry_count": (0, 1),
        },
        {
            "weight": 0.15,
            "tools": [
                "validate_request",
                "check_policy",
                "retrieve_order_history",
                "verify_payment_method",
                "calculate_refund_amount",
                "send_confirmation_email",
            ],
            "outcome": "resolved",
            "p_tokens": (450, 520),
            "c_tokens": (170, 210),  # Extra thorough
            "latency": (480, 600),
            "loop_count": (2, 3),
            "retry_count": (0, 1),
        },
        {
            "weight": 0.05,
            "tools": [
                "validate_request",
                "check_policy",
                "retrieve_order_history",
            ],
            "outcome": "error",
            "p_tokens": (400, 460),
            "c_tokens": (80, 120),
            "latency": (350, 450),
            "loop_count": (1, 2),
            "retry_count": (1, 2),
            "error_count": (1, 1),
        },
    ]

    # VARIANT: Direct agent - shorter, more concise
    variant = [
        {
            "weight": 0.65,
            "tools": [
                "validate_request",
                "check_policy",
                "send_confirmation_email",  # Skips extra validation steps
            ],
            "outcome": "resolved",
            "p_tokens": (400, 450),
            "c_tokens": (95, 125),  # ~40% shorter responses
            "latency": (320, 420),  # Faster
            "loop_count": (1, 1),
            "retry_count": (0, 0),
        },
        {
            "weight": 0.18,
            "tools": [
                "validate_request",
                "check_policy",
                "escalate_to_supervisor",  # Quick escalation
            ],
            "outcome": "escalated",
            "p_tokens": (410, 460),
            "c_tokens": (85, 115),  # Brief escalation message
            "latency": (340, 440),
            "loop_count": (1, 2),
            "retry_count": (0, 0),
        },
        {
            "weight": 0.12,
            "tools": [
                "validate_request",
                "check_policy",
                "calculate_refund_amount",
                "send_confirmation_email",
            ],
            "outcome": "resolved",
            "p_tokens": (420, 470),
            "c_tokens": (100, 130),
            "latency": (350, 450),
            "loop_count": (1, 2),
            "retry_count": (0, 0),
        },
        {
            "weight": 0.05,
            "tools": [
                "validate_request",
                "check_policy",
            ],
            "outcome": "error",
            "p_tokens": (390, 440),
            "c_tokens": (70, 100),
            "latency": (300, 400),
            "loop_count": (1, 1),
            "retry_count": (1, 2),
            "error_count": (1, 1),
        },
    ]

    return baseline, variant


# ============================================================================
# SYNTHETIC DATA GENERATION (adapted from cli_demo.py)
# ============================================================================


def generate_refund_agent_runs(
    version: str,
    count: int,
    scenarios: list[ScenarioTemplate],
    show_progress: bool = True,
) -> None:
    """
    Generate synthetic refund request runs.

    Args:
        version: Version name (e.g., "v1.0", "v2.0")
        count: Number of runs to generate
        scenarios: Scenario templates to sample from
        show_progress: Whether to show progress dots
    """
    import random
    from datetime import datetime, timedelta

    now = datetime.utcnow()

    # Refund-specific prompts and outputs
    refund_prompts = [
        "Customer requesting refund for order #RF-4821 (item not received)",
        "Refund request for damaged item - order #RF-9234",
        "Customer wants to return product purchased 45 days ago",
        "Refund for cancelled subscription - auto-renewal issue",
        "Wrong item shipped - customer requesting full refund",
    ]

    empathetic_outputs = [
        "I sincerely apologize for the inconvenience. I've processed your full refund of $127.50, which should appear in your account within 3-5 business days. We truly value your business and hope to serve you better in the future.",
        "I completely understand your frustration. I've escalated this to our supervisor team who will review your case and contact you within 24 hours with a resolution. Thank you for your patience.",
        "I'm sorry to hear about this issue. I've verified your order and confirmed that a full refund of $89.99 has been initiated. You should receive an email confirmation shortly.",
    ]

    direct_outputs = [
        "Refund approved: $127.50. Processing time: 3-5 days.",
        "Case escalated to supervisor. Response within 24h.",
        "Refund confirmed: $89.99. Check email for confirmation.",
    ]

    for i in range(count):
        if show_progress and i % 10 == 0:
            click.echo(".", nl=False)
            sys.stdout.flush()

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

        # Occasionally vary tool sequence slightly (10% of runs)
        if random.random() < 0.10 and len(tools) > 3:
            # Swap two adjacent tools
            idx = random.randint(0, len(tools) - 2)
            tools[idx], tools[idx + 1] = tools[idx + 1], tools[idx]

        time_to_first_tool_ms = random.randint(20, 80)
        verbosity_ratio = c_tokens / p_tokens if p_tokens > 0 else 0.0

        # Choose appropriate outputs based on version
        outputs = empathetic_outputs if "v1" in version else direct_outputs

        prompt_text = random.choice(refund_prompts)
        output_text = random.choice(outputs)

        payload = {
            "session_id": f"refund_demo_{version}_{i}",
            "deployment_version": version,
            "environment": "production",
            "started_at": run_time,
            "completed_at": run_time + timedelta(milliseconds=latency),
            "task_input_hash": f"refund_hash_{random.randint(1000, 9999)}",
            "tool_sequence": json.dumps(tools),
            "tool_call_count": len(tools),
            "output_length": len(output_text),
            "output_structure_hash": f"struct_{random.randint(100, 999)}",
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


# ============================================================================
# NARRATIVE OUTPUT FUNCTIONS
# ============================================================================


# Color helpers using ANSI escape codes for exact hex colors
def _c(hex_color: str, text: str, bold: bool = False) -> str:
    """Apply hex color using ANSI escape codes."""
    hex_color = hex_color.lstrip("#")
    r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
    bold_code = "\033[1m" if bold else ""
    reset_code = "\033[0m"
    return f"{bold_code}\033[38;2;{r};{g};{b}m{text}{reset_code}"


def print_scenario_intro() -> None:
    """Print the scenario description."""
    click.echo()
    click.echo(_c("8B5CF6", f"🔍 Driftbase Demo — {SCENARIO_NAME}", bold=True))
    click.echo()
    click.echo(SCENARIO_DESCRIPTION)
    click.echo()


def print_prompt_diff() -> None:
    """Show baseline vs variant prompt (2-4 lines max)."""
    click.echo(_c("8B5CF6", "Prompt change:", bold=True))
    click.echo(_c("FF6B6B", f'  - baseline: "{BASELINE_PROMPT}"'))
    click.echo(_c("4ADE80", f'  + variant:  "{VARIANT_PROMPT}"'))
    click.echo()


def print_staged_steps(runs_per_version: int) -> None:
    """
    Stage the output in steps with visual feedback.

    Steps:
    1. Capturing baseline responses
    2. Capturing variant responses
    3. Fingerprinting both versions
    4. Computing drift
    """
    baseline_scenarios, variant_scenarios = get_refund_agent_scenarios()

    # Step 1: Baseline
    click.echo("Step 1/4 — Capturing baseline responses (v1.0)...", nl=False)
    sys.stdout.flush()
    time.sleep(0.2)
    click.echo(" ", nl=False)
    generate_refund_agent_runs(
        "v1.0", runs_per_version, baseline_scenarios, show_progress=True
    )
    click.echo(_c("4ADE80", f" ✓ {runs_per_version} runs recorded"))

    # Step 2: Variant
    click.echo("Step 2/4 — Capturing variant responses (v2.0)...", nl=False)
    sys.stdout.flush()
    time.sleep(0.2)
    click.echo(" ", nl=False)
    generate_refund_agent_runs(
        "v2.0", runs_per_version, variant_scenarios, show_progress=True
    )
    click.echo(_c("4ADE80", f" ✓ {runs_per_version} runs recorded"))

    # Step 3: Fingerprinting (simulated - happens automatically on query)
    click.echo("Step 3/4 — Fingerprinting both versions...", nl=False)
    time.sleep(0.3)
    click.echo(_c("4ADE80", " " * 20 + "✓ done"))

    # Step 4: Computing drift (simulated - happens on diff command)
    click.echo("Step 4/4 — Ready for drift analysis...", nl=False)
    time.sleep(0.2)
    click.echo(_c("4ADE80", " " * 24 + "✓ done"))
    click.echo()


def print_command_suggestions() -> None:
    """Show suggested commands to explore the loaded data."""
    click.echo(
        _c("8B5CF6", "── Explore the drift ─────────────────────────────", bold=True)
    )
    click.echo()
    click.echo("Now that synthetic data is loaded, run these commands:")
    click.echo()

    click.echo(_c("8B5CF6", "  1. driftbase diff v1.0 v2.0", bold=True))
    click.echo("     → See overall drift score, cost impact, and verdict")
    click.echo()

    click.echo(_c("8B5CF6", "  2. driftbase compare v1.0 v2.0 --matrix", bold=True))
    click.echo("     → Detailed component-by-component breakdown")
    click.echo()

    click.echo(_c("8B5CF6", "  3. driftbase diagnose v1.0 v2.0", bold=True))
    click.echo("     → Root cause analysis and investigation")
    click.echo()

    click.echo("Start with #1 to see the full drift analysis!")
    click.echo()


def print_next_steps() -> None:
    """Show bridge to real usage with @track decorator example."""
    click.echo(_c("8B5CF6", "── Use with your own agent ───────────────────────"))
    click.echo()
    click.echo("To detect drift in production:")
    click.echo()
    click.echo(_c("8B5CF6", "  from driftbase import track"))
    click.echo()
    click.echo(_c("8B5CF6", "  @track()  # version is optional"))
    click.echo(_c("8B5CF6", "  def run_agent(input):"))
    click.echo(_c("8B5CF6", "      return my_llm_call(input)"))
    click.echo()
    click.echo("Docs: https://driftbase.io/docs/quickstart")
    click.echo()


# ============================================================================
# INTERACTIVE MODE
# ============================================================================


def run_interactive_demo(runs_per_version: int) -> None:
    """
    Run interactive mode that auto-executes commands with pauses.

    Flow:
    1. Show scenario + generate data
    2. Auto-run: driftbase diff v1.0 v2.0
    3. Pause for user to read
    4. Auto-run: driftbase compare v1.0 v2.0 --matrix
    5. Show remaining command suggestions
    """
    # Step 1: Intro and data generation
    print_scenario_intro()
    print_prompt_diff()
    click.echo(f"Running {runs_per_version} synthetic interactions per version...")
    click.echo()
    print_staged_steps(runs_per_version)

    # Step 2: Auto-run diff command
    click.echo(_c("8B5CF6", "━" * 60))
    click.echo(
        _c("8B5CF6", "Interactive Mode: Auto-running analysis commands...", bold=True)
    )
    click.echo(_c("8B5CF6", "━" * 60))
    click.echo()

    time.sleep(1)

    click.echo(_c("8B5CF6", "Running: driftbase diff v1.0 v2.0", bold=True))
    click.echo()
    time.sleep(0.5)

    # Execute the diff command
    try:
        result = subprocess.run(
            ["driftbase", "diff", "v1.0", "v2.0"],
            capture_output=False,
            text=True,
        )
    except Exception as e:
        click.echo(_c("FF6B6B", f"Error running diff command: {e}"))

    click.echo()
    click.echo(_c("8B5CF6", "Press Enter to see detailed comparison..."))
    input()

    # Step 3: Auto-run compare command
    click.echo()
    click.echo(_c("8B5CF6", "Running: driftbase compare v1.0 v2.0 --matrix", bold=True))
    click.echo()
    time.sleep(0.5)

    try:
        result = subprocess.run(
            ["driftbase", "compare", "v1.0", "v2.0", "--matrix"],
            capture_output=False,
            text=True,
        )
    except Exception as e:
        click.echo(_c("FF6B6B", f"Error running compare command: {e}"))

    click.echo()
    click.echo(_c("8B5CF6", "━" * 60))
    click.echo()

    # Step 4: Show remaining commands
    click.echo(_c("8B5CF6", "Try these commands yourself:", bold=True))
    click.echo()
    click.echo(_c("8B5CF6", "  • driftbase diagnose v1.0 v2.0"))
    click.echo("    → Root cause investigation")
    click.echo()

    print_next_steps()


# ============================================================================
# MAIN ENTRY POINT
# ============================================================================


def run_narrative_demo(
    ctx: click.Context, quick: bool = False, interactive: bool = False
) -> None:
    """
    Run the narrative demo mode.

    This is the main entry point called from cli_demo.py when --verbose is NOT set.

    Args:
        ctx: Click context (not currently used, but passed for consistency)
        quick: If True, use 20 runs instead of 50
        interactive: If True, auto-run analysis commands
    """
    runs_per_version = QUICK_RUNS if quick else DEFAULT_RUNS

    if interactive:
        run_interactive_demo(runs_per_version)
    else:
        # Standard narrative mode
        print_scenario_intro()
        print_prompt_diff()
        click.echo(
            f"Running {runs_per_version} synthetic interactions per version (minimum for statistical significance)..."
        )
        click.echo()
        print_staged_steps(runs_per_version)
        print_command_suggestions()
        print_next_steps()
