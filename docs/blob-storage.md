# Blob Storage (Phase 4)

**Status**: Shipped in v0.12.0

## Overview

Blob storage preserves the full, untruncated input and output text from agent runs in a separate `runs_blobs` table. This enables post-hoc analysis, debugging, and evidence generation without losing data to the legacy 5000-character truncation limit.

## Why Blob Storage?

**Problem**: The legacy `agent_runs_local` table truncates `raw_prompt` and `raw_output` to 5000 characters, losing critical context for long interactions. This makes debugging difficult and evidence strings incomplete.

**Solution**: Phase 4 stores the full input/output in a separate `runs_blobs` table BEFORE truncation, while keeping the truncated versions in `runs_raw` for backward compatibility.

## Storage Schema

Blob storage uses the `runs_blobs` table:

```sql
CREATE TABLE runs_blobs (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,  -- Foreign key to runs_raw.id
    field_name TEXT NOT NULL,  -- "input" or "output"
    content TEXT NOT NULL,  -- Full text (may be truncated at size cap)
    content_length INTEGER NOT NULL,  -- Original length in bytes
    content_hash TEXT NOT NULL,  -- SHA-256 hash
    truncated BOOLEAN NOT NULL,  -- True if exceeded size cap
    created_at TIMESTAMP NOT NULL
);
```

**Indexes**:
- `run_id` (for fast lookup by run)
- Composite index on `(run_id, field_name)` (for get_blob queries)

## Size Limits

Blob storage has a configurable size cap to prevent disk bloat:

```bash
# Default: 100KB per blob (102400 bytes)
export DRIFTBASE_BLOB_SIZE_LIMIT=102400

# Increase for long-running agents
export DRIFTBASE_BLOB_SIZE_LIMIT=1048576  # 1MB
```

When content exceeds the limit:
- Content is truncated to the limit
- `truncated` flag is set to True
- `content_length` preserves the original size

## Configuration

Enable/disable blob storage:

```bash
# Default: enabled
export DRIFTBASE_BLOB_STORAGE=true

# Disable to save disk space (blobs won't be saved)
export DRIFTBASE_BLOB_STORAGE=false
```

When disabled:
- `save_blob()` returns empty string immediately
- No disk I/O overhead
- Runs still ingest normally (backward compatible)

## Viewing Blob Content

Use `driftbase inspect <run_id>` to view blob content:

```bash
driftbase inspect abc123
```

Output includes:
- Full input (from blob if available, otherwise legacy raw_prompt)
- Full output (from blob if available, otherwise legacy raw_output)
- Size indicator (KB) and truncation flag

## Storage Management

### Check Blob Usage

```bash
driftbase migrate --status
```

Output includes:
- Total blob count
- Total storage size (MB)
- Breakdown by field_name (input vs output)
- Truncated blob count

### Prune Blobs

Delete all blobs (reclaim disk space):

```bash
# Preview
driftbase prune --blobs --dry-run

# Execute
driftbase prune --blobs --yes
```

Delete orphaned blobs (blobs for deleted runs):

```bash
driftbase prune --orphan-blobs --yes
```

## Best Practices

1. **Disk space monitoring**: Check blob usage periodically with `migrate --status`
2. **Prune old blobs**: Run `prune --orphan-blobs` after run pruning to reclaim space
3. **Adjust size limit**: Increase `DRIFTBASE_BLOB_SIZE_LIMIT` if truncation is frequent
4. **Disable if unused**: Set `DRIFTBASE_BLOB_STORAGE=false` if you don't need post-hoc analysis

## Performance Impact

- **Write overhead**: ~5-10ms per run (2 blob inserts)
- **Read overhead**: None (blobs only fetched on `inspect`, not during analysis)
- **Disk usage**: ~100-200KB per run (input + output blobs)

Blob saves are **best-effort** - if save fails, ingestion continues normally. This ensures blob storage never blocks the critical path.

## Backward Compatibility

- **Runs without blobs** continue to work - blob queries return empty list
- **Inspect command** falls back to legacy `raw_prompt`/`raw_output` if no blobs
- **No schema version bump** - Phase 4 does not change `FEATURE_SCHEMA_VERSION`

## Implementation Notes

- **Hash algorithm**: SHA-256 (64-character hex digest)
- **Truncation**: Applied to `content` field only, `content_length` preserves original
- **Error handling**: Blob save failures logged as debug warnings, never raise
- **Migration**: Existing runs are not backfilled with blobs (forward-only)

## See Also

- [Observation Trees](observation-trees.md) - Full trace hierarchy capture
- [Schema v0.11](schema-v2.md) - Two-table design (runs_raw + runs_features)
