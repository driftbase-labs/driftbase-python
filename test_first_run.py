"""Test first-run experience with minimal runs."""
import time
from driftbase import track

@track(version="v0.1")
def test_agent(prompt: str):
    """Minimal test agent."""
    time.sleep(0.1)
    return {"outcome": "resolved", "response": f"Handled: {prompt}"}

if __name__ == "__main__":
    print("Simulating first-time user with only 5 runs...")
    for i in range(5):
        test_agent(f"test_{i}")

    # Wait for async writes
    from driftbase.local.local_store import drain_local_store
    drain_local_store(timeout=2.0)

    print("\n✅ 5 runs tracked. Now trying to diff against empty baseline...")
