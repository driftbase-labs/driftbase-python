"""
Run the drift experiment.

Usage:
    python run_experiment.py --version v1                  # Sonnet 4 baseline
    python run_experiment.py --version v2                  # Haiku 4.5 challenger
    python run_experiment.py --version v1 --limit 5        # quick test
    python run_experiment.py --version v1 --repeat 3       # 3 repeats per scenario
"""

import argparse
import json
import time

from agent import build_agent
from scenarios import get_scenarios

from driftbase import track

# ---------------------------------------------------------------------------
# Version config — Same-tier comparison (Sonnet vs Haiku)
# ---------------------------------------------------------------------------

VERSION_CONFIG = {
    "v1": {"model": "claude-sonnet-4-20250514", "label": "Claude Sonnet 4"},
    "v2": {"model": "claude-haiku-4-5-20251001", "label": "Claude Haiku 4.5"},
}


# ---------------------------------------------------------------------------
# Instrumented runner — @track auto-detects LangGraph
# ---------------------------------------------------------------------------


def make_tracked_runner(version: str, model_name: str):
    """Create a @track-instrumented agent runner. LangGraph auto-detected."""
    agent = build_agent(model_name)

    @track(version=version)
    def run_agent(query: str) -> dict:
        """Run agent and return the full result."""
        result = agent.invoke({"messages": [("user", query)]})
        return result

    def run_and_extract(query: str) -> tuple[str, list[str]]:
        """Run the tracked agent and extract response + tool calls."""
        result = run_agent(query)

        # Extract tool calls from messages
        tool_calls = []
        for msg in result["messages"]:
            if hasattr(msg, "tool_calls") and msg.tool_calls:
                for tc in msg.tool_calls:
                    tool_calls.append(tc["name"])

        # Extract final response
        final_response = ""
        for msg in reversed(result["messages"]):
            if (
                hasattr(msg, "type")
                and msg.type == "ai"
                and not getattr(msg, "tool_calls", None)
            ):
                content = msg.content
                final_response = content if isinstance(content, str) else str(content)
                break

        return final_response, tool_calls

    return run_and_extract


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description="Run drift experiment")
    parser.add_argument("--version", required=True, choices=["v1", "v2"])
    parser.add_argument(
        "--limit", type=int, default=None, help="Limit number of scenarios"
    )
    parser.add_argument(
        "--repeat",
        type=int,
        default=2,
        help="Number of times to repeat each scenario (default: 2)",
    )
    args = parser.parse_args()

    config = VERSION_CONFIG[args.version]
    scenarios = get_scenarios(args.limit)

    print(f"\n{'=' * 60}")
    print(f"  DRIFT EXPERIMENT — {args.version}")
    print(f"  Model: {config['model']}")
    print(f"  Scenarios: {len(scenarios)}")
    print(f"  Repeats per scenario: {args.repeat}")
    print(f"  Total runs: {len(scenarios) * args.repeat}")
    print("  Agent: Swiss Airlines Support (LangGraph tutorial)")
    print(f"{'=' * 60}\n")

    run_agent = make_tracked_runner(args.version, config["model"])

    results = []
    errors = []
    correct_count = 0
    total_count = 0
    consistency_data = {}

    for i, scenario in enumerate(scenarios, 1):
        query = scenario["query"]
        category = scenario["category"]
        expected_tools = set(scenario.get("expected_tools", []))

        print(f"  [{i:2d}/{len(scenarios)}] [{category:12s}] {query[:55]}...")

        scenario_tool_sequences = []

        for repeat_idx in range(args.repeat):
            try:
                start = time.time()
                response, tool_calls = run_agent(query)
                elapsed = time.time() - start
                resp_len = len(response) if response else 0

                # Check correctness
                actual_tools = set(tool_calls)
                is_correct = expected_tools.issubset(actual_tools)
                if is_correct:
                    correct_count += 1
                total_count += 1

                scenario_tool_sequences.append(json.dumps(tool_calls))

                results.append(
                    {
                        "index": i,
                        "repeat": repeat_idx + 1,
                        "category": category,
                        "elapsed": round(elapsed, 2),
                        "response_length": resp_len,
                        "tool_count": len(tool_calls),
                        "correct": is_correct,
                    }
                )

                status = "✓" if is_correct else "✗"
                print(
                    f"           [{repeat_idx + 1}] {status} {elapsed:.1f}s | {len(tool_calls)} tools | {resp_len} chars"
                )

            except Exception as e:
                errors.append(
                    {
                        "index": i,
                        "repeat": repeat_idx + 1,
                        "query": query,
                        "error": str(e),
                    }
                )
                print(f"           [{repeat_idx + 1}] ERROR: {e}")
                total_count += 1

        consistency_data[i] = scenario_tool_sequences

    # Calculate intra-version consistency
    consistent_count = sum(
        1 for sequences in consistency_data.values() if len(set(sequences)) == 1
    )
    consistency_rate = (consistent_count / len(scenarios) * 100) if scenarios else 0

    # Summary
    print(f"\n{'=' * 60}")
    print(f"  COMPLETE — {args.version} ({config['label']})")
    print(f"  Successful: {len(results)} / {total_count}")
    print(f"  Errors: {len(errors)}")

    if results:
        avg_time = sum(r["elapsed"] for r in results) / len(results)
        avg_len = sum(r["response_length"] for r in results) / len(results)
        avg_tools = sum(r["tool_count"] for r in results) / len(results)
        accuracy = (correct_count / total_count * 100) if total_count > 0 else 0

        print("\n  Performance:")
        print(f"    Avg latency: {avg_time:.1f}s")
        print(f"    Avg response length: {avg_len:.0f} chars")
        print(f"    Avg tools per run: {avg_tools:.1f}")

        print("\n  Correctness:")
        print(f"    Correct: {correct_count}/{total_count} ({accuracy:.1f}%)")
        print("    (Expected tools are subset of actual tools)")

        print("\n  Intra-version consistency:")
        print(
            f"    Identical tool sequences: {consistent_count}/{len(scenarios)} ({consistency_rate:.1f}%)"
        )
        print(f"    (Same query → same tools across {args.repeat} repeats)")

    print(f"{'=' * 60}")

    if errors:
        print("\n  Errors:")
        for e in errors:
            print(f"    [{e['index']}:{e['repeat']}] {e['error'][:80]}")

    print("\n  Data recorded by Driftbase to local SQLite.")
    if args.version == "v1":
        print("  Next: python run_experiment.py --version v2")
    else:
        print("  Next: python analyze.py")
    print()


if __name__ == "__main__":
    main()
