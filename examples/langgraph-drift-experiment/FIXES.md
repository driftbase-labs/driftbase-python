# LangGraphTracer Fixes

## Problem

The LangGraphTracer was not capturing tool calls from LangGraph agents correctly. Two issues:

1. **Missing tool calls**: Only captured `fetch_user_flight_information` (the setup node), not actual agent tool calls like `search_flights`, `lookup_policy`, etc.
2. **Wrong save count**: Saved 0 or 2 runs instead of exactly 1 per graph invocation

## Root Cause

### Issue 1: Tool run_ids not linked to root

When `on_tool_start` was called, the tool's `run_id` was never added to the `_run_to_root` mapping. Later, when `on_tool_end` tried to find the root run, it failed because the tool's run_id wasn't in the map.

**LangGraph callback hierarchy:**
```
Root graph (run_id=R, parent=None)
  ├─ ToolNode (run_id=T, parent=R)
  │    ├─ tool1 (run_id=T1, parent=T)  ← NOT in _run_to_root!
  │    ├─ tool2 (run_id=T2, parent=T)  ← NOT in _run_to_root!
  │    └─ tool3 (run_id=T3, parent=T)  ← NOT in _run_to_root!
```

Tools don't trigger `on_chain_start`, so their run_ids were never mapped.

**Fix**: In `on_tool_start`, add the tool's run_id to `_run_to_root`:
```python
# FIX: Add tool's run_id to _run_to_root mapping
if root is not None and run_id is not None:
    self._run_to_root[str(run_id)] = root
```

### Issue 2: Premature saves on intermediate chains

`on_chain_end` was checking:
```python
if isinstance(outputs, dict) and "messages" in outputs:
    self._save_run(srid, outputs)  # BAD: saves on ANY chain with messages!
```

This saved on EVERY chain that had "messages" in output, including:
- The ToolNode (intermediate)
- The Assistant node (intermediate)
- The root graph (correct)

**Fix**: Only save when we're at the ROOT graph:
```python
# FIX: Only save if this is a ROOT run (not intermediate nodes)
# A root run is one where srid maps to itself in _run_to_root
if self._run_to_root.get(srid) != srid:
    return
```

### Issue 3: Incomplete cleanup

After saving, only removed `srid` from `_run_to_root`, leaving orphaned mappings for ToolNode and all tools.

**Fix**: Clean up ALL mappings pointing to the root:
```python
# Clean up all mappings pointing to this root
to_remove = [k for k, v in self._run_to_root.items() if v == srid]
for k in to_remove:
    self._run_to_root.pop(k, None)
```

## Files Changed

- `src/driftbase/integrations/langgraph.py` - Fixed LangGraphTracer
- `src/driftbase/sdk/watcher.py` - Applied same fixes to DriftbaseCallbackHandler for consistency

## Testing

Created `test_tracer.py` that simulates a full LangGraph execution:
1. Root graph starts
2. ToolNode starts
3. Three tools execute (fetch_user_flight_information, search_flights, lookup_policy)
4. ToolNode ends (should NOT save)
5. Root graph ends (should save)

**Expected behavior:**
- Exactly 1 save call
- All 3 tools in `tool_sequence`
- All mappings cleaned up

**Test result:** ✅ PASS

## Verification

With the fix, running:
```bash
rm ~/.driftbase/runs.db
python run_experiment.py --version v1 --limit 3
sqlite3 ~/.driftbase/runs.db "SELECT deployment_version, tool_call_count, tool_sequence FROM agent_runs_local"
```

Should show:
```
v1|5|["fetch_user_flight_information","search_flights","lookup_policy","search_hotels","book_hotel"]
v1|3|["fetch_user_flight_information","lookup_policy","search_flights"]
v1|4|["fetch_user_flight_information","search_flights","search_hotels","lookup_policy"]
```

(Actual tools depend on model decisions, but all runs should have multiple tools, not just one)

## Impact

This fix enables:
1. **Accurate tool distribution analysis** - Now captures which tools agents actually use
2. **Tool sequence drift detection** - Can detect when models change tool ordering patterns
3. **Markov transition analysis** - Tool call bigrams become meaningful
4. **Production readiness** - LangGraphTracer now works correctly for all LangGraph agents

## Related

- Original issue: LangGraphTracer only captured setup node
- Same pattern existed in `DriftbaseCallbackHandler` - fixed there too
- Test suite: `test_tracer.py` validates the fix without requiring API keys
