"""
Run the drift experiment.

Usage:
    python run_experiment.py --version v1          # Sonnet 4 baseline
    python run_experiment.py --version v2          # Haiku 4.5 challenger
    python run_experiment.py --version v1 --limit 5  # quick test
"""

import argparse
import time

from agent import build_agent
from scenarios import get_scenarios

from driftbase.integrations import LangGraphTracer

# ---------------------------------------------------------------------------
# Version config — Anthropic models
# ---------------------------------------------------------------------------

VERSION_CONFIG = {
    "v1": {"model": "claude-sonnet-4-20250514", "label": "Claude Sonnet 4 (baseline)"},
    "v2": {
        "model": "claude-haiku-4-5-20251001",
        "label": "Claude Haiku 4.5 (challenger)",
    },
}


# ---------------------------------------------------------------------------
# Instrumented runner
# ---------------------------------------------------------------------------


def make_tracked_runner(version: str, model_name: str):
    """Create a LangGraphTracer-instrumented agent runner."""
    agent = build_agent(model_name)

    def run_agent(query: str) -> str:
        tracer = LangGraphTracer(version=version, agent_id="swiss-airlines-support")
        result = agent.invoke(
            {"messages": [("user", query)]},
            config={"callbacks": [tracer]},
        )

        # Extract final response
        for msg in reversed(result["messages"]):
            if (
                hasattr(msg, "type")
                and msg.type == "ai"
                and not getattr(msg, "tool_calls", None)
            ):
                content = msg.content
                return content if isinstance(content, str) else str(content)
        return ""

    return run_agent


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description="Run drift experiment")
    parser.add_argument("--version", required=True, choices=["v1", "v2"])
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    config = VERSION_CONFIG[args.version]
    scenarios = get_scenarios(args.limit)

    print(f"\n{'=' * 60}")
    print(f"  DRIFT EXPERIMENT — {args.version}")
    print(f"  Model: {config['model']}")
    print(f"  Scenarios: {len(scenarios)}")
    print("  Agent: Swiss Airlines Support (LangGraph tutorial)")
    print(f"{'=' * 60}\n")

    run_agent = make_tracked_runner(args.version, config["model"])

    results = []
    errors = []

    for i, scenario in enumerate(scenarios, 1):
        query = scenario["query"]
        category = scenario["category"]
        print(f"  [{i:2d}/{len(scenarios)}] [{category:12s}] {query[:55]}...")

        try:
            start = time.time()
            response = run_agent(query)
            elapsed = time.time() - start
            resp_len = len(response) if response else 0

            results.append(
                {
                    "index": i,
                    "category": category,
                    "elapsed": round(elapsed, 2),
                    "response_length": resp_len,
                }
            )
            print(f"           -> {elapsed:.1f}s | {resp_len} chars")

        except Exception as e:
            errors.append({"index": i, "query": query, "error": str(e)})
            print(f"           -> ERROR: {e}")

    # Summary
    print(f"\n{'=' * 60}")
    print(f"  COMPLETE — {args.version} ({config['label']})")
    print(f"  Successful: {len(results)} / {len(scenarios)}")
    print(f"  Errors: {len(errors)}")
    if results:
        avg_time = sum(r["elapsed"] for r in results) / len(results)
        avg_len = sum(r["response_length"] for r in results) / len(results)
        print(f"  Avg latency: {avg_time:.1f}s")
        print(f"  Avg response length: {avg_len:.0f} chars")
    print(f"{'=' * 60}")

    if errors:
        print("\n  Errors:")
        for e in errors:
            print(f"    [{e['index']}] {e['error'][:80]}")

    print("\n  Data recorded by Driftbase to local SQLite.")
    if args.version == "v1":
        print("  Next: python run_experiment.py --version v2")
    else:
        print("  Next: python analyze.py")
    print()


if __name__ == "__main__":
    main()
