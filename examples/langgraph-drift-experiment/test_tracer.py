"""
Quick test to verify LangGraphTracer captures tools correctly.
This tests the tracer logic without requiring API calls.
"""

import logging
import sys
import time
from datetime import datetime
from unittest.mock import Mock
from uuid import uuid4

sys.path.insert(0, "/Users/work_air/projects/driftbase-python/src")

# Enable debug logging
logging.basicConfig(level=logging.DEBUG, format="%(message)s")

from driftbase.integrations.langgraph import LangGraphTracer


def simulate_langgraph_execution():
    """Simulate LangGraph callback sequence."""
    tracer = LangGraphTracer(version="v1", agent_id="test-agent")

    # Simulate IDs
    root_id = str(uuid4())
    toolnode_id = str(uuid4())
    tool1_id = str(uuid4())
    tool2_id = str(uuid4())
    tool3_id = str(uuid4())

    # 1. Root graph starts
    print("1. Root graph starts")
    tracer.on_chain_start(
        serialized={},
        inputs={"messages": [{"role": "user", "content": "test query"}]},
        run_id=root_id,
        parent_run_id=None,
    )
    assert root_id in tracer.active_runs
    assert tracer._run_to_root[root_id] == root_id
    print("   ✓ Root run created")

    # 2. ToolNode starts (child of root)
    print("2. ToolNode starts")
    tracer.on_chain_start(
        serialized={},
        inputs={},
        run_id=toolnode_id,
        parent_run_id=root_id,
    )
    assert tracer._run_to_root[toolnode_id] == root_id
    print("   ✓ ToolNode linked to root")

    # 3. First tool starts (child of ToolNode)
    print("3. Tool 1: fetch_user_flight_information starts")
    tracer.on_tool_start(
        serialized={"name": "fetch_user_flight_information"},
        input_str="{}",
        run_id=tool1_id,
        parent_run_id=toolnode_id,
    )
    assert tool1_id in tracer._run_to_root
    assert tracer._run_to_root[tool1_id] == root_id
    state = tracer.active_runs[root_id]
    assert "fetch_user_flight_information" in state["tool_run_id_to_name"].values()
    print("   ✓ Tool 1 linked to root")

    # 4. First tool ends
    print("4. Tool 1 ends")
    tracer.on_tool_end(
        output="flight info",
        run_id=tool1_id,
        parent_run_id=toolnode_id,
    )
    assert "fetch_user_flight_information" in state["tool_sequence"]
    print(f"   ✓ Tool sequence now: {state['tool_sequence']}")

    # 5. Second tool starts
    print("5. Tool 2: search_flights starts")
    tracer.on_tool_start(
        serialized={"name": "search_flights"},
        input_str='{"departure": "ZRH"}',
        run_id=tool2_id,
        parent_run_id=toolnode_id,
    )
    assert tool2_id in tracer._run_to_root
    print("   ✓ Tool 2 linked to root")

    # 6. Second tool ends
    print("6. Tool 2 ends")
    tracer.on_tool_end(
        output="flight results",
        run_id=tool2_id,
        parent_run_id=toolnode_id,
    )
    assert "search_flights" in state["tool_sequence"]
    print(f"   ✓ Tool sequence now: {state['tool_sequence']}")

    # 7. Third tool starts
    print("7. Tool 3: lookup_policy starts")
    tracer.on_tool_start(
        serialized={"name": "lookup_policy"},
        input_str='{"query": "baggage"}',
        run_id=tool3_id,
        parent_run_id=toolnode_id,
    )
    assert tool3_id in tracer._run_to_root
    print("   ✓ Tool 3 linked to root")

    # 8. Third tool ends
    print("8. Tool 3 ends")
    tracer.on_tool_end(
        output="policy info",
        run_id=tool3_id,
        parent_run_id=toolnode_id,
    )
    assert "lookup_policy" in state["tool_sequence"]
    print(f"   ✓ Tool sequence now: {state['tool_sequence']}")

    # 9. ToolNode ends (intermediate - should NOT save)
    print("9. ToolNode ends (should NOT save)")
    initial_save_called = hasattr(tracer, "_save_called")
    tracer.on_chain_end(
        outputs={"messages": [{"role": "ai", "content": "interim"}]},
        run_id=toolnode_id,
        parent_run_id=root_id,
    )
    assert root_id in tracer.active_runs  # Should still be active
    print("   ✓ ToolNode end did not save (correct)")

    # 10. Root graph ends (should save)
    print("10. Root graph ends (should save)")

    # Mock enqueue_run to verify save is called
    # Must mock at the import location in langgraph.py
    from driftbase.integrations import langgraph

    original_enqueue = langgraph.enqueue_run
    save_called = []

    def mock_enqueue(payload):
        save_called.append(payload)
        print(f"   ✓ enqueue_run called with {payload['tool_call_count']} tools")

    langgraph.enqueue_run = mock_enqueue

    try:
        # Debug: check state before on_chain_end
        print(f"   Debug: root_id={root_id}")
        print(f"   Debug: root_id in active_runs? {root_id in tracer.active_runs}")
        print(f"   Debug: _run_to_root[root_id]={tracer._run_to_root.get(root_id)}")
        print(
            f"   Debug: maps to itself? {tracer._run_to_root.get(root_id) == root_id}"
        )

        print(f"   Calling on_chain_end with run_id={root_id}")
        tracer.on_chain_end(
            outputs={"messages": [{"role": "ai", "content": "final response"}]},
            run_id=root_id,
            parent_run_id=None,
        )
        print("   on_chain_end returned")

        assert len(save_called) == 1, f"Expected 1 save, got {len(save_called)}"
        payload = save_called[0]
        assert payload["tool_call_count"] == 3
        assert payload["deployment_version"] == "v1"
        print(f"   ✓ Saved with tool sequence: {payload['tool_sequence']}")

        # Verify cleanup
        assert root_id not in tracer.active_runs
        assert root_id not in tracer._run_to_root
        assert toolnode_id not in tracer._run_to_root
        assert tool1_id not in tracer._run_to_root
        assert tool2_id not in tracer._run_to_root
        assert tool3_id not in tracer._run_to_root
        print("   ✓ All mappings cleaned up")

    finally:
        langgraph.enqueue_run = original_enqueue

    return True


if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("  TESTING LangGraphTracer FIX")
    print("=" * 60 + "\n")

    try:
        success = simulate_langgraph_execution()
        print("\n" + "=" * 60)
        print("  ✓ ALL TESTS PASSED")
        print("  The tracer correctly:")
        print("    - Links tool run_ids to root")
        print("    - Captures all 3 tools in sequence")
        print("    - Only saves on root graph end")
        print("    - Cleans up all mappings")
        print("=" * 60 + "\n")
    except AssertionError as e:
        print(f"\n✗ TEST FAILED: {e}\n")
        sys.exit(1)
    except Exception as e:
        print(f"\n✗ UNEXPECTED ERROR: {e}\n")
        import traceback

        traceback.print_exc()
        sys.exit(1)
