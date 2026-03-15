"""
Example: Using SmolagentsTracer for EU AI Act compliance.

This demonstrates how to track smolagents executions with full code auditability.
"""

from driftbase.integrations import SmolagentsTracer

# Example with smolagents (requires: pip install smolagents)
try:
    from smolagents import ToolCallingAgent, DuckDuckGoSearchTool, tool
    from smolagents.models import HfApiModel

    # Define a custom tool
    @tool
    def calculator(expression: str) -> float:
        """
        Evaluate a mathematical expression.

        Args:
            expression: A valid Python mathematical expression (e.g., "15 * 1240 / 100")
        """
        try:
            # Note: In production, use ast.literal_eval or a proper math parser
            # This is simplified for demonstration
            return float(eval(expression))
        except Exception as e:
            return f"Error: {e}"

    # Initialize the tracer
    tracer = SmolagentsTracer(
        version="v1.0",
        agent_id="demo-research-agent"
    )

    # Create an agent with the tracer attached
    agent = ToolCallingAgent(
        model=HfApiModel(),
        tools=[DuckDuckGoSearchTool(), calculator],
        step_callbacks=[tracer]  # <-- Attach the tracer here
    )

    # Run a task - the tracer will automatically capture:
    # - Planning steps (model reasoning)
    # - Generated code blocks (full text)
    # - Sandbox execution outputs
    # - Errors and observations
    # - Final answer
    result = agent.run("What is 15% of 1240?")

    print(f"Agent result: {result}")
    print(f"\nTracking summary:")
    print(f"  - Code blocks executed: {len(tracer.code_blocks)}")
    print(f"  - Planning steps: {len(tracer.planning_steps)}")
    print(f"  - Errors encountered: {tracer.error_count}")
    print(f"  - Tool sequence: {tracer.tool_sequence}")

    # The run data is automatically saved to ~/.driftbase/runs.db
    # View it with: driftbase diff v1.0 v1.1

except ImportError as e:
    print(f"Error: {e}")
    print("\nTo run this example, install smolagents:")
    print("  pip install smolagents")
