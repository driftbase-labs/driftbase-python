"""
Analyze drift between v1 and v2.

Usage:
    python analyze.py
    python analyze.py --json    # JSON output only
"""

import subprocess
import sys


def main():
    json_only = "--json" in sys.argv

    if json_only:
        subprocess.run(
            ["driftbase", "diff", "v1", "v2", "--json"],
        )
        return

    print(f"\n{'=' * 60}")
    print("  DRIFTBASE DRIFT ANALYSIS")
    print("  Agent: Swiss Airlines Support (LangGraph tutorial)")
    print("  Comparing: v1 (Sonnet 4) -> v2 (Haiku 4.5)")
    print(f"{'=' * 60}\n")

    # Standard report
    subprocess.run(
        ["driftbase", "diff", "v1", "v2"],
    )

    print(f"\n{'─' * 60}")
    print("  DETAILED BREAKDOWN")
    print(f"{'─' * 60}\n")

    # Detailed stats
    subprocess.run(
        ["driftbase", "diff", "v1", "v2", "--show-stats"],
    )

    print(f"\n{'─' * 60}")
    print("  JSON (for charts / blog post)")
    print(f"{'─' * 60}\n")

    subprocess.run(
        ["driftbase", "diff", "v1", "v2", "--json"],
    )

    print(f"""
{"=" * 60}
  NEXT STEPS
{"=" * 60}

  1. Screenshot the drift report above
  2. Write the blog post:

     Title: "Same Prompt, Same Tools, Different Model:
             We Detected Silent Behavioral Drift
             in LangChain's Official Customer Support Bot"

     Structure:
     - The problem (agents drift silently)
     - The experiment (what we tested)
     - The results (drift score + top dimensions)
     - Why this matters (production implications)
     - How to catch it (pip install driftbase)

  3. Post to:
     - LinkedIn (personal + company page)
     - LangChain Discord
     - r/LangChain
     - Twitter/X

  4. Link to: github.com/driftbase-labs/driftbase-python

{"=" * 60}
""")


if __name__ == "__main__":
    main()
