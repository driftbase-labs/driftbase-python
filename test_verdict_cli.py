"""Test script to generate sample data and view the new verdict-based CLI output."""

import random
import time
from driftbase import track

# Simulate v1.0 - baseline behavior
@track(version="v1.0")
def agent_v1(prompt: str):
    """Baseline agent with stable behavior."""
    # Simulates consistent tool usage and outcomes
    time.sleep(0.05 + random.uniform(0, 0.02))  # Low latency

    # Stable outcome distribution - mostly "resolved"
    outcome = random.choices(
        ["resolved", "escalated", "error"],
        weights=[0.85, 0.10, 0.05],
    )[0]

    if outcome == "error":
        raise ValueError("Simulated error")

    return {"outcome": outcome, "response": f"v1.0 handled: {prompt}"}


# Simulate v2.0 - changed behavior with higher escalation
@track(version="v2.0")
def agent_v2(prompt: str):
    """Changed agent with higher escalation rate."""
    # Slower due to more processing
    time.sleep(0.05 + random.uniform(0, 0.05))  # Increased latency

    # Changed outcome distribution - much more escalation
    outcome = random.choices(
        ["resolved", "escalated", "error"],
        weights=[0.65, 0.30, 0.05],  # 3× more escalation!
    )[0]

    if outcome == "error":
        raise ValueError("Simulated error")

    return {"outcome": outcome, "response": f"v2.0 handled: {prompt}"}


# Simulate v3.0 - minor changes
@track(version="v3.0")
def agent_v3(prompt: str):
    """Agent with minor drift - should get MONITOR verdict."""
    time.sleep(0.05 + random.uniform(0, 0.025))  # Slightly higher latency

    # Slight outcome change
    outcome = random.choices(
        ["resolved", "escalated", "error"],
        weights=[0.82, 0.12, 0.06],
    )[0]

    if outcome == "error":
        raise ValueError("Simulated error")

    return {"outcome": outcome, "response": f"v3.0 handled: {prompt}"}


if __name__ == "__main__":
    import sys

    print("🧪 Generating test data for verdict CLI demo...\n")

    # Generate baseline v1.0 data (127 runs)
    print("Generating v1.0 baseline (127 runs)...")
    for i in range(127):
        try:
            agent_v1(f"test_prompt_{i}")
        except ValueError:
            pass

    # Generate v2.0 with significant drift (89 runs)
    print("Generating v2.0 with significant drift (89 runs)...")
    for i in range(89):
        try:
            agent_v2(f"test_prompt_{i}")
        except ValueError:
            pass

    # Generate v3.0 with minor drift (50 runs)
    print("Generating v3.0 with minor drift (50 runs)...")
    for i in range(50):
        try:
            agent_v3(f"test_prompt_{i}")
        except ValueError:
            pass

    # Wait for async writes to complete
    from driftbase.local.local_store import drain_local_store
    drain_local_store(timeout=3.0)

    print("\n✅ Test data generated!")
    print("\nNow run:")
    print("  driftbase diff v1.0 v2.0   # Should show REVIEW verdict")
    print("  driftbase diff v1.0 v3.0   # Should show MONITOR verdict")
