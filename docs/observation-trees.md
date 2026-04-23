# Observation Trees (Phase 4)

**Status**: Shipped in v0.12.0

## Overview

Observation trees capture the full hierarchical structure of trace spans from Langfuse and LangSmith, preserving ALL observation types (generations, spans, events) instead of just tool calls. This provides richer context for debugging and enables more accurate tool extraction.

## Why Observation Trees?

**Problem**: The legacy trace mapping only extracted "generation" type observations, missing tools embedded in spans or events. This led to incomplete tool sequences and limited debugging visibility.

**Solution**: Phase 4 captures the full observation tree from trace sources and stores it as JSON in the `observation_tree_json` field of `runs_raw`. This enables:

1. **Complete tool coverage** - Find tools in spans, events, and generations
2. **Debugging context** - See the full execution hierarchy, not just final outputs
3. **Future extensibility** - Enable per-node latency tracking, error attribution, etc.

## Storage

Observation trees are stored in the `observation_tree_json` column (TEXT) in the `runs_raw` table.

**Format**:
```json
{
  "id": "obs_abc123",
  "type": "span",
  "name": "root_chain",
  "input": {...},
  "output": {...},
  "metadata": {...},
  "start_time": "2026-04-23T10:00:00Z",
  "end_time": "2026-04-23T10:00:02Z",
  "children": [
    {
      "id": "obs_def456",
      "type": "tool",
      "name": "search",
      "children": []
    },
    {
      "id": "obs_ghi789",
      "type": "generation",
      "name": "llm_call",
      "children": []
    }
  ]
}
```

## Tool Extraction (Additive)

Phase 4 introduces **additive tree-based tool extraction**:

1. **Legacy extraction** runs first (baseline: generation-type observations only)
2. **Tree extraction** walks the full tree and finds tools in ALL node types
3. **Merge** combines both, keeping all unique tools

**Key property**: Tree extraction finds **MORE** tools than legacy, never fewer.

This ensures backward compatibility - detection behavior remains unchanged for existing runs while capturing additional signal from new ingestion.

## Backward Compatibility

- **Runs without trees** continue to work - `observation_tree_json` is nullable
- **Legacy tool extraction** remains the baseline - tree extraction is additive
- **No schema version bump** - Phase 4 does not change `FEATURE_SCHEMA_VERSION`

## Viewing Observation Trees

Use `driftbase inspect <run_id>` to view the observation tree:

```bash
driftbase inspect abc123
```

Output includes:
- Hierarchical tree with indentation
- Node types color-coded (generation=cyan, tool=green, span=blue, etc.)
- Node IDs (first 8 chars) for cross-reference

## Configuration

Observation trees are always captured when available from the trace source. No configuration needed.

To disable tree-based tool extraction (use legacy only):
```bash
# Not yet implemented - tree extraction is always additive
```

## Implementation Notes

- **Langfuse trees**: Built from `observations` list using `parent_observation_id` relationships
- **LangSmith trees**: Built from root run + `child_runs` using `parent_run_id` relationships
- **Tree building failures**: Logged as warnings, fall back to None (legacy extraction continues)

## See Also

- [Blob Storage](blob-storage.md) - Full input/output storage for post-hoc analysis
- [Feature Schema](feature-schema.md) - How observation trees feed into feature derivation
