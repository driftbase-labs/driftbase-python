# Schema v2: Two-Table Storage (v0.11+)

## Overview

Starting in v0.11, Driftbase splits run storage into two tables:

1. **`runs_raw`** — Immutable trace data from ingestion
2. **`runs_features`** — Derived features computed from trace data

This separation enables:
- Schema evolution without reingestion
- Lazy feature derivation on read
- Clear audit trail of feature origins
- Backfilling features for old data

## Table Schemas

### runs_raw

Immutable trace data captured at ingestion time.

| Column | Type | Description |
|--------|------|-------------|
| `id` | TEXT PRIMARY KEY | Run UUID |
| `external_id` | TEXT | ID from external system (Langfuse, LangSmith) |
| `source` | TEXT | Origin system (langfuse, langsmith, decorator) |
| `ingestion_source` | TEXT | How ingested (connector, decorator) |
| `session_id` | TEXT | Session/thread identifier |
| `deployment_version` | TEXT | Semantic version or epoch-YYYY-MM-DD |
| `version_source` | TEXT | How version was determined (explicit, tag, env, epoch) |
| `environment` | TEXT | Environment name (production, staging, etc) |
| `timestamp` | TIMESTAMP | When run started |
| `input` | TEXT | Raw input/prompt text |
| `output` | TEXT | Raw output/completion text |
| `latency_ms` | INTEGER | End-to-end latency in milliseconds |
| `tokens_prompt` | INTEGER | Input token count (if available) |
| `tokens_completion` | INTEGER | Output token count (if available) |
| `tokens_total` | INTEGER | Total tokens (sum of above, if available) |
| `raw_status` | TEXT | Status from trace system (error, success, etc) |
| `raw_error_message` | TEXT | Error message if run failed |
| `observation_tree_json` | TEXT | Full LangFuse observation tree (Phase 4+) |
| `ingested_at` | TIMESTAMP | When row was written |
| `raw_schema_version` | INTEGER | Schema version for compatibility |

**Immutability contract:** Rows in `runs_raw` are never updated after insertion. If trace data changes, create a new row.

### runs_features

Derived features computed from trace data. Can be re-derived at any time.

| Column | Type | Description |
|--------|------|-------------|
| `id` | TEXT PRIMARY KEY | Feature row UUID |
| `run_id` | TEXT UNIQUE | Foreign key to runs_raw.id |
| `feature_schema_version` | INTEGER | Current: 1. -1 = derivation failed |
| `feature_source` | TEXT | Origin: "derived" or "migrated" |
| `derivation_error` | TEXT | Error message if derivation failed |
| `tool_sequence` | TEXT | JSON array of tool names |
| `tool_call_sequence` | TEXT | JSON array of tool call signatures |
| `tool_call_count` | INTEGER | Number of tool invocations |
| `semantic_cluster` | TEXT | Inferred outcome cluster |
| `loop_count` | INTEGER | Detected retry/loop iterations |
| `verbosity_ratio` | REAL | Output/input token ratio |
| `time_to_first_tool_ms` | INTEGER | Latency to first tool call |
| `fallback_rate` | REAL | Fallback invocation rate |
| `retry_count` | INTEGER | Explicit retry count |
| `retry_patterns` | TEXT | JSON dict of retry patterns |
| `error_classification` | TEXT | Error type (ok, trace_error, inferred_error) |
| `input_hash` | TEXT | Hash of input for deduplication |
| `output_hash` | TEXT | Hash of output structure |
| `input_length` | INTEGER | Character count of input |
| `output_length` | INTEGER | Character count of output |
| `computed_at` | TIMESTAMP | When features were derived |

**Re-derivation:** If `feature_schema_version` advances (e.g., 1 → 2), features are automatically re-derived on read.

## Migrated vs Derived Features

### feature_source Values

- **`"migrated"`**: Copied during v0.11 migration from `agent_runs_local`. These features were computed at ingestion time before the schema split.
- **`"derived"`**: Computed by `derive_features()` in this codebase. Includes:
  - New runs ingested after v0.11
  - Features re-derived during backfill
  - Features computed via lazy derivation

### Audit Trail

The `feature_source` column serves as an audit trail for enterprise compliance:

- Distinguish legacy computed features from newly derived ones
- Track which features came from migration vs lazy derivation
- Debug discrepancies between migrated and re-derived features
- Validate feature computation consistency across schema versions

### When Features Are Derived

1. **New Ingestion** (v0.11+): Connectors and `@track()` decorator compute features and insert into `runs_features` with `feature_source="derived"`
2. **Lazy Derivation**: On read, if `run_id` exists in `runs_raw` but not `runs_features`, features are derived and inserted
3. **Backfill**: `driftbase migrate --backfill` iterates missing/stale features and derives them
4. **Rebuild**: `driftbase migrate --rebuild --confirm` drops all features and re-derives from `runs_raw`

## Migration from v0.10

### Automatic Migration

On backend initialization, Driftbase detects if migration is needed (legacy `agent_runs_local` table exists but `runs_raw` does not) and prompts for migration.

Migration steps:
1. **Backup**: Create `{db_file}.pre-v0.11.backup` copy
2. **Create tables**: Create `runs_raw` and `runs_features` with indexes
3. **Copy data**: Insert all rows from `agent_runs_local` into `runs_raw`
4. **Copy features**: Insert computed features into `runs_features` with `feature_source="migrated"`
5. **Preserve legacy table**: Keep `agent_runs_local` as read-only safety net

### CLI Commands

```bash
# Show migration status
driftbase migrate --status

# Run migration (or use backend initialization)
python -c "from driftbase import get_backend; get_backend()"

# Backfill missing/stale features
driftbase migrate --backfill

# Re-derive all features (destructive)
driftbase migrate --rebuild --confirm
```

### Rollback

If migration causes issues:

1. Stop all processes using Driftbase
2. Replace DB file with backup:
   ```bash
   cp ~/.driftbase/runs.db.pre-v0.11.backup ~/.driftbase/runs.db
   ```
3. Downgrade to v0.10.x: `pip install driftbase==0.10.3`

## Phase 2a Limitations

### Observation Trees (Phase 4)

`observation_tree_json` is **not yet populated** in Phase 2a. This means:

- Tool-related features (tool_sequence, loop_count, etc.) cannot be re-derived for migrated data
- Migration copies these features from `agent_runs_local` to preserve values
- Phase 4 will backfill observation trees, enabling full re-derivation

### Feature Derivation Without Observation Trees

For migrated data, `derive_features()` computes limited features:

- ✅ `input_hash`, `output_hash`, `input_length`, `output_length`
- ✅ `semantic_cluster` (heuristic from output text)
- ✅ `verbosity_ratio` (token ratio)
- ✅ `error_classification` (from `raw_status`)
- ❌ `tool_sequence`, `tool_call_count`, `loop_count` (require observation tree)
- ❌ `time_to_first_tool_ms`, `retry_count` (require observation tree)

**Recommendation**: Do not run `--rebuild` on migrated databases until Phase 4 adds observation tree backfill.

## Schema Evolution

### Adding New Features

To add a new feature column:

1. Add field to `RunFeatures` model in `src/driftbase/backends/sqlite.py`
2. Increment `FEATURE_SCHEMA_VERSION`
3. Update `derive_features()` in `src/driftbase/local/feature_deriver.py` to compute new field
4. On next read, lazy derivation will automatically update stale features

### Removing Features

To remove a feature column:

1. Mark field as deprecated in code comments
2. Keep field in schema (SQLite ALTER TABLE limitations)
3. Stop populating field in new derivations
4. On major version bump, document deprecated fields in migration notes

### Changing Feature Logic

If feature computation logic changes:

1. Increment `FEATURE_SCHEMA_VERSION`
2. Update computation in `derive_features()`
3. Stale features are automatically re-derived on read

## Indexes

### Created by Migration

- `idx_runs_features_run_id` on `runs_features(run_id)` — Foreign key lookup
- Primary key indexes on `id` columns (implicit)

### Future Indexes

Consider adding for query performance:

- `runs_raw(deployment_version, timestamp)` — Version filtering
- `runs_raw(environment, timestamp)` — Environment filtering
- `runs_features(semantic_cluster)` — Cluster aggregation
- `runs_features(feature_schema_version)` — Stale feature detection

## Data Integrity

### Foreign Key Constraint

`runs_features.run_id` has a foreign key to `runs_raw.id`, but SQLite foreign key enforcement is **not enabled** by default for compatibility.

If strict referential integrity is needed:

```python
from sqlalchemy import event

@event.listens_for(engine, "connect")
def enable_foreign_keys(dbapi_conn, connection_record):
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()
```

### Orphaned Features

If `runs_raw` rows are deleted but `runs_features` rows remain, queries will fail. To clean up:

```sql
DELETE FROM runs_features
WHERE run_id NOT IN (SELECT id FROM runs_raw);
```

## Performance

### Lazy Derivation Overhead

- First read of a run without features: ~1-5ms derivation + SQLite insert
- Subsequent reads: Direct JOIN, no derivation
- Stale features: Re-derivation on read (amortized over time)

### Backfill Performance

`driftbase migrate --backfill` on 10,000 runs:
- Derivation: ~2-3 seconds
- SQLite batch insert: ~1 second
- Total: ~3-4 seconds

### Query Patterns

Efficient:
```sql
SELECT r.*, f.*
FROM runs_raw r
LEFT JOIN runs_features f ON r.id = f.run_id
WHERE r.deployment_version = 'v1.0'
ORDER BY r.timestamp DESC
LIMIT 1000;
```

Inefficient (avoid):
```sql
SELECT * FROM runs_features
WHERE tool_call_count > 5;  -- Missing deployment_version filter
```

## See Also

- [Migration Guide](migration-guide.md) — Step-by-step upgrade instructions
- [Version Resolution](version-resolution.md) — How deployment versions are determined
- [Fingerprint Schema](fingerprint-schema-debt.md) — Fingerprint field definitions
