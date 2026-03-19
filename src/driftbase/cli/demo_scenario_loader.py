"""
Custom scenario loader for YAML-defined agent patterns.
Allows teams to define their own baseline/regression scenarios.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from driftbase.cli.demo_templates import ScenarioTemplate


def load_yaml_scenario(yaml_path: str | Path) -> tuple[list[ScenarioTemplate], list[ScenarioTemplate]]:
    """Load baseline and regression scenarios from YAML file.

    Expected YAML format:
    ```yaml
    name: "My Custom Agent Pattern"
    description: "Description of what this agent does"

    baseline:
      - weight: 0.70
        tools: ["validate", "query", "format"]
        outcome: "resolved"
        p_tokens: [300, 500]
        c_tokens: [40, 80]
        latency: [200, 400]
        loop_count: [1, 2]
        retry_count: [0, 0]
        description: "Happy path"

    regression:
      - weight: 0.50
        tools: ["validate", "query", "query", "format", "format"]
        outcome: "resolved"
        p_tokens: [800, 1200]
        c_tokens: [150, 250]
        latency: [900, 1500]
        loop_count: [4, 6]
        retry_count: [2, 4]
        description: "Stuck in loops"
    ```
    """
    try:
        import yaml
    except ImportError:
        raise ImportError(
            "PyYAML is required for YAML scenario loading. "
            "Install with: pip install pyyaml"
        )

    yaml_path = Path(yaml_path)
    if not yaml_path.exists():
        raise FileNotFoundError(f"Scenario file not found: {yaml_path}")

    with open(yaml_path) as f:
        data = yaml.safe_load(f)

    # Validate structure
    if "baseline" not in data or "regression" not in data:
        raise ValueError(
            "YAML must contain 'baseline' and 'regression' sections"
        )

    def _parse_scenarios(scenarios_data: list[dict[str, Any]]) -> list[ScenarioTemplate]:
        """Convert YAML scenario data to ScenarioTemplate format."""
        templates: list[ScenarioTemplate] = []

        for scenario in scenarios_data:
            template: ScenarioTemplate = {
                "weight": float(scenario.get("weight", 1.0)),
                "tools": scenario["tools"],
                "outcome": scenario.get("outcome", "resolved"),
                "p_tokens": tuple(scenario["p_tokens"]),  # type: ignore
                "c_tokens": tuple(scenario["c_tokens"]),  # type: ignore
                "latency": tuple(scenario["latency"]),  # type: ignore
                "loop_count": tuple(scenario.get("loop_count", [1, 2])),  # type: ignore
                "retry_count": tuple(scenario.get("retry_count", [0, 1])),  # type: ignore
            }

            if "error_count" in scenario:
                template["error_count"] = tuple(scenario["error_count"])  # type: ignore

            if "description" in scenario:
                template["description"] = scenario["description"]

            templates.append(template)

        return templates

    baseline = _parse_scenarios(data["baseline"])
    regression = _parse_scenarios(data["regression"])

    return baseline, regression


def generate_template_yaml(output_path: str | Path) -> None:
    """Generate a template YAML file for users to customize."""
    template_content = """# Driftbase Custom Scenario Template
# Define your own baseline and regression patterns here

name: "My Custom Agent Pattern"
description: "Describe what your agent does and what regression this demonstrates"

# Baseline: how your agent should behave normally
baseline:
  # Scenario 1: Happy path (70% of runs)
  - weight: 0.70
    tools: ["validate_input", "query_database", "format_response"]
    outcome: "resolved"
    p_tokens: [300, 500]    # Range for prompt tokens
    c_tokens: [40, 80]       # Range for completion tokens
    latency: [200, 400]      # Range for latency in ms
    loop_count: [1, 2]       # Range for reasoning iterations
    retry_count: [0, 0]      # Range for retry attempts
    description: "Standard successful query"

  # Scenario 2: More complex path (20% of runs)
  - weight: 0.20
    tools: ["validate_input", "query_database", "retrieve_context", "summarize", "format_response"]
    outcome: "resolved"
    p_tokens: [500, 700]
    c_tokens: [60, 120]
    latency: [400, 700]
    loop_count: [2, 3]
    retry_count: [0, 1]
    description: "Query requiring additional context"

  # Scenario 3: Escalation (10% of runs)
  - weight: 0.10
    tools: ["validate_input", "query_database", "escalate_to_human"]
    outcome: "escalated"
    p_tokens: [400, 600]
    c_tokens: [30, 60]
    latency: [350, 600]
    loop_count: [2, 3]
    retry_count: [0, 1]
    description: "Edge case requiring human intervention"

# Regression: problematic behavior after code changes
regression:
  # Scenario 1: Excessive loops (50% of runs)
  - weight: 0.50
    tools: ["validate_input", "query_database", "query_database", "query_database", "format_response"]
    outcome: "resolved"
    p_tokens: [800, 1200]
    c_tokens: [100, 180]
    latency: [1000, 1800]
    loop_count: [4, 7]
    retry_count: [2, 4]
    description: "Agent stuck repeating database queries"

  # Scenario 2: Tool dropout (30% of runs)
  - weight: 0.30
    tools: ["validate_input", "query_database", "format_response"]
    outcome: "resolved"
    p_tokens: [400, 650]
    c_tokens: [50, 100]
    latency: [350, 650]
    loop_count: [1, 2]
    retry_count: [0, 1]
    description: "Skipped context retrieval - missing critical step"

  # Scenario 3: Increased escalation rate (20% of runs)
  - weight: 0.20
    tools: ["validate_input", "query_database", "escalate_to_human"]
    outcome: "escalated"
    p_tokens: [700, 1000]
    c_tokens: [80, 140]
    latency: [800, 1400]
    loop_count: [3, 5]
    retry_count: [1, 3]
    description: "Agent gives up too easily"
"""

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(template_content)


def analyze_agent_code(agent_file_path: str | Path) -> dict[str, Any]:
    """Analyze agent code to extract tool definitions and patterns (Shadow Mode).

    This is a simple AST-based analysis. For production use, consider more
    sophisticated code analysis tools.
    """
    import ast
    import re

    agent_file_path = Path(agent_file_path)
    if not agent_file_path.exists():
        raise FileNotFoundError(f"Agent file not found: {agent_file_path}")

    with open(agent_file_path) as f:
        content = f.read()

    # Extract tool names from common patterns
    tools = set()

    # Pattern 1: LangChain tool decorators
    tool_decorator_pattern = r'@tool\s*\n\s*def\s+(\w+)'
    tools.update(re.findall(tool_decorator_pattern, content))

    # Pattern 2: Tool class definitions
    tool_class_pattern = r'class\s+(\w+Tool)\s*\('
    tools.update(re.findall(tool_class_pattern, content))

    # Pattern 3: Function definitions that look like tools
    function_pattern = r'def\s+(query_|search_|retrieve_|check_|validate_|format_|send_|create_)(\w+)'
    function_matches = re.findall(function_pattern, content)
    tools.update([f"{prefix}{name}" for prefix, name in function_matches])

    # Try AST parsing for more accurate analysis
    try:
        tree = ast.parse(content)
        for node in ast.walk(tree):
            # Find function definitions with docstrings mentioning "tool"
            if isinstance(node, ast.FunctionDef):
                docstring = ast.get_docstring(node)
                if docstring and ("tool" in docstring.lower() or "agent" in docstring.lower()):
                    tools.add(node.name)
    except SyntaxError:
        pass  # Fall back to regex-only parsing

    # Analyze imports to detect framework
    frameworks = []
    if "from langchain" in content or "import langchain" in content:
        frameworks.append("langchain")
    if "from langgraph" in content or "import langgraph" in content:
        frameworks.append("langgraph")
    if "from autogen" in content or "import autogen" in content:
        frameworks.append("autogen")
    if "from crewai" in content or "import crewai" in content:
        frameworks.append("crewai")

    return {
        "tools": sorted(list(tools)),
        "tool_count": len(tools),
        "frameworks": frameworks,
        "file_path": str(agent_file_path),
        "analysis_note": "Automated code analysis - verify tool names are correct",
    }


def generate_scenarios_from_code_analysis(
    analysis: dict[str, Any],
    baseline_config: dict[str, Any] | None = None,
) -> tuple[list[ScenarioTemplate], list[ScenarioTemplate]]:
    """Generate baseline/regression scenarios from code analysis.

    Uses detected tools and applies heuristics for realistic patterns.
    """
    tools = analysis["tools"]

    if not tools:
        raise ValueError("No tools detected in agent code. Ensure functions are named conventionally.")

    # Default configuration
    config = baseline_config or {}
    avg_tools_per_run = config.get("avg_tools_per_run", min(4, len(tools)))
    baseline_latency = config.get("baseline_latency", [300, 600])
    baseline_tokens = config.get("baseline_tokens", {"prompt": [400, 700], "completion": [50, 120]})

    # Generate baseline scenarios
    baseline: list[ScenarioTemplate] = [
        {
            "weight": 0.70,
            "tools": tools[:avg_tools_per_run],
            "outcome": "resolved",
            "p_tokens": tuple(baseline_tokens["prompt"]),  # type: ignore
            "c_tokens": tuple(baseline_tokens["completion"]),  # type: ignore
            "latency": tuple(baseline_latency),  # type: ignore
            "loop_count": (1, 2),
            "retry_count": (0, 0),
            "description": "Standard execution path",
        },
        {
            "weight": 0.20,
            "tools": tools[:avg_tools_per_run + 2] if len(tools) >= avg_tools_per_run + 2 else tools,
            "outcome": "resolved",
            "p_tokens": (baseline_tokens["prompt"][0] + 200, baseline_tokens["prompt"][1] + 300),
            "c_tokens": (baseline_tokens["completion"][0] + 20, baseline_tokens["completion"][1] + 40),
            "latency": (baseline_latency[0] + 150, baseline_latency[1] + 250),
            "loop_count": (2, 3),
            "retry_count": (0, 1),
            "description": "Complex path requiring more tools",
        },
        {
            "weight": 0.10,
            "tools": tools[:max(2, avg_tools_per_run - 1)],
            "outcome": "escalated",
            "p_tokens": tuple(baseline_tokens["prompt"]),  # type: ignore
            "c_tokens": (baseline_tokens["completion"][0] - 20, baseline_tokens["completion"][1] - 40),
            "latency": tuple(baseline_latency),  # type: ignore
            "loop_count": (1, 2),
            "retry_count": (0, 1),
            "description": "Escalation scenario",
        },
    ]

    # Generate regression scenarios (problematic patterns)
    regression: list[ScenarioTemplate] = [
        {
            "weight": 0.50,
            "tools": tools[:avg_tools_per_run] * 2,  # Repeat tools (loop behavior)
            "outcome": "resolved",
            "p_tokens": (baseline_tokens["prompt"][0] * 2, baseline_tokens["prompt"][1] * 3),
            "c_tokens": (baseline_tokens["completion"][0] * 2, baseline_tokens["completion"][1] * 3),
            "latency": (baseline_latency[0] * 3, baseline_latency[1] * 4),
            "loop_count": (5, 9),
            "retry_count": (3, 6),
            "description": "Excessive looping - tools called multiple times",
        },
        {
            "weight": 0.30,
            "tools": tools[:max(1, avg_tools_per_run - 2)],  # Drop tools
            "outcome": "resolved",
            "p_tokens": tuple(baseline_tokens["prompt"]),  # type: ignore
            "c_tokens": (baseline_tokens["completion"][0] * 2, baseline_tokens["completion"][1] * 3),
            "latency": tuple(baseline_latency),  # type: ignore
            "loop_count": (1, 2),
            "retry_count": (0, 1),
            "description": "Tool dropout - missing critical steps, verbose compensation",
        },
        {
            "weight": 0.20,
            "tools": tools[:max(2, avg_tools_per_run - 1)],
            "outcome": "escalated",
            "p_tokens": (baseline_tokens["prompt"][0] + 300, baseline_tokens["prompt"][1] + 500),
            "c_tokens": (baseline_tokens["completion"][0] + 50, baseline_tokens["completion"][1] + 100),
            "latency": (baseline_latency[0] * 2, baseline_latency[1] * 3),
            "loop_count": (3, 5),
            "retry_count": (2, 4),
            "description": "Increased escalation rate after struggling",
        },
    ]

    return baseline, regression
