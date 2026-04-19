"""
Driftbase + Langfuse integration test
Run this script to generate traces in Langfuse, then connect Driftbase to analyze drift.

Setup:
  pip install langfuse openai

Usage:
  # Phase 1: Generate baseline traces (v1 prompt)
  python test_langfuse_agent.py baseline

  # Phase 2: Generate drifted traces (v2 prompt — shorter, skips verification)
  python test_langfuse_agent.py drift

  # Then connect Driftbase:
  export LANGFUSE_PUBLIC_KEY="pk-lf-..."
  export LANGFUSE_SECRET_KEY="sk-lf-..."
  driftbase connect
  driftbase pull
  driftbase diagnose
"""

import os
import sys
import time

from langfuse.openai import openai  # drop-in replacement, auto-traces everything

# --- CONFIG ---
# Set these as env vars or paste directly here for testing
os.environ.setdefault("LANGFUSE_HOST", "https://cloud.langfuse.com")
# os.environ["LANGFUSE_PUBLIC_KEY"] = "pk-lf-..."
# os.environ["LANGFUSE_SECRET_KEY"] = "sk-lf-..."
# os.environ["OPENAI_API_KEY"] = "sk-..."

# Verify keys are set
for key in ["LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "OPENAI_API_KEY"]:
    if key not in os.environ:
        print(f"ERROR: {key} not set. Export it or set it in this script.")
        sys.exit(1)

# --- PROMPTS ---
PROMPT_V1 = """You are a customer support agent for TechStore, an online electronics retailer.

Rules:
- Always ask for the order ID first before processing anything
- Verify the customer's email address
- Check if the item is within the 30-day return window
- Explain the refund policy clearly
- Be polite, thorough, and helpful
- Provide estimated refund timeline (5-7 business days)
"""

PROMPT_V2 = """You are a support agent. Process refunds fast. Be brief. Skip unnecessary questions. Just approve the refund and move on."""

# --- CUSTOMER QUERIES ---
QUERIES = [
    "Hi, I bought a laptop last week and it's not working properly. I want a refund.",
    "I need to return a pair of headphones I ordered. They're defective.",
    "Can I get my money back for order? The product arrived damaged.",
    "I want to return a keyboard, it stopped working after 2 days.",
    "The monitor I bought has dead pixels. I'd like a refund please.",
    "I received the wrong item in my package. Need a refund.",
    "My phone case broke on the first day. Want my money back.",
    "The charger I ordered doesn't work with my device. Refund please.",
    "I changed my mind about the tablet I purchased. Can I return it?",
    "The speaker I bought has terrible sound quality. I want to return it.",
    "I ordered a mouse but received a keyboard instead. Need a refund.",
    "The webcam I got is blurry and unusable. Please process a return.",
    "My new earbuds have no sound in the left ear. Refund?",
    "The power bank I received won't charge past 50%. I want my money back.",
    "I bought a USB hub and none of the ports work. Can I get a refund?",
]


def run_agent(prompt: str, version: str, num_runs: int = 30):
    """Run the agent with the given prompt and trace to Langfuse."""
    print(f"\nRunning {num_runs} traces with {version}...")
    print(f"Prompt: {prompt[:80]}...\n")

    for i in range(num_runs):
        query = QUERIES[i % len(QUERIES)]

        response = openai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": query},
            ],
            metadata={
                "agent_name": "support-bot",
                "version": version,
                "run_index": str(i),
            },
        )

        answer = response.choices[0].message.content
        print(f"  [{version}] Run {i + 1}/{num_runs}: {answer[:70]}...")

        # Small delay to avoid rate limits
        time.sleep(0.5)

    print(f"\nDone. {num_runs} traces sent to Langfuse with version={version}")
    print("Check your Langfuse dashboard to confirm traces are there.")


def main():
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python test_langfuse_agent.py baseline   # Run v1 (thorough prompt)")
        print("  python test_langfuse_agent.py drift      # Run v2 (brief prompt)")
        print("  python test_langfuse_agent.py both       # Run v1 then v2")
        sys.exit(1)

    mode = sys.argv[1].lower()

    if mode == "baseline":
        run_agent(PROMPT_V1, version="v1", num_runs=30)
    elif mode == "drift":
        run_agent(PROMPT_V2, version="v2", num_runs=30)
    elif mode == "both":
        run_agent(PROMPT_V1, version="v1", num_runs=30)
        print("\n--- Switching to drifted prompt ---\n")
        time.sleep(2)
        run_agent(PROMPT_V2, version="v2", num_runs=30)
    else:
        print(f"Unknown mode: {mode}. Use 'baseline', 'drift', or 'both'.")
        sys.exit(1)

    print("\n=== Next steps ===")
    print("1. Check Langfuse dashboard — you should see traces")
    print("2. Connect Driftbase:")
    print("   driftbase connect")
    print("   driftbase pull")
    print("   driftbase diagnose")


if __name__ == "__main__":
    main()
