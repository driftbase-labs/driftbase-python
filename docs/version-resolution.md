# Version Resolution in Driftbase

Driftbase needs to know which version each run belongs to in order to detect drift between versions. This document explains how versions are resolved and what to do when version resolution is ambiguous.

## Resolution Precedence

Driftbase resolves versions using a 4-level precedence system (highest to lowest):

### 1. Release Field (Highest Priority)
- **Source**: Langfuse `release` field
- **When to use**: Explicit deployment tagging in your tracing system
- **Example**:
  ```python
  # In your Langfuse-instrumented code
  langfuse.trace(release="v2.1.0", ...)
  ```
- **version_source**: `"release"`

### 2. Version Tags
- **Source**:
  - Langfuse `version` field
  - `version:X.Y.Z` tags in trace metadata
  - LangSmith run name or metadata version fields
- **When to use**: Version metadata in your traces
- **Example**:
  ```python
  # In metadata
  metadata={"version": "v2.1.0"}
  ```
- **version_source**: `"tag"`

### 3. Environment Variable
- **Source**: `DRIFTBASE_VERSION` environment variable
- **When to use**: Static version for all runs in a deployment
- **Example**:
  ```bash
  export DRIFTBASE_VERSION=v2.1.0
  driftbase connect --project=prod
  ```
- **version_source**: `"env"`

### 4. Epoch Fallback (Lowest Priority)
- **Source**: Time-bucketed label from trace timestamp (Monday of the week)
- **Format**: `epoch-YYYY-MM-DD`
- **When to use**: Automatic fallback when no explicit version is available
- **Example**: Trace from 2024-03-15 → `epoch-2024-03-11` (that Monday)
- **version_source**: `"epoch"`

## What is `version_source`?

Every run in Driftbase has a `version_source` field indicating how its version was resolved. This provides transparency into version resolution quality.

Inspect with:
```bash
sqlite3 ~/.driftbase/runs.db "SELECT deployment_version, version_source, COUNT(*) FROM agent_runs_local GROUP BY version_source"
```

Example output:
```
v1.0|release|250
v2.0|release|300
epoch-2024-03-11|epoch|50
```

## Epoch-Resolved Versions: Warnings and Behavior

### Why Epoch Resolution Happens
- No `release` field in Langfuse traces
- No `version` tag in trace metadata
- No `DRIFTBASE_VERSION` environment variable set
- Common in early exploration or local development

### What Happens
When >50% of runs in either version are epoch-resolved, Driftbase:

1. **Adds a warning** to the drift report
2. **Downgrades confidence tier** by one level:
   - TIER3 (full analysis) → TIER2 (indicative signals only)
   - TIER2 (indicative) → TIER1 (insufficient data)
3. **Logs at WARNING level**

### Why This Matters
Epoch-bucketed versions reflect **time**, not **deployment**:
- A single "version" may contain multiple actual deployments
- Drift detected might be due to gradual changes over time, not a specific deployment
- Comparisons are less actionable ("something changed this week" vs "v2.0 introduced a bug")

### Example Warning
```
⚠ Comparing time-bucketed versions

Versions were resolved from timestamps, not explicit tags. Results may not
reflect real deployment drift. Tag your deployments with Langfuse release
field or DRIFTBASE_VERSION for accurate diffs.

Baseline: epoch-2024-03-04 (80% epoch-resolved)
Current:  epoch-2024-03-11 (75% epoch-resolved)
```

### When Epoch Resolution is OK
Epoch resolution is **intentionally supported** for:
- `driftbase diagnose`: Analyzing behavioral shifts over time (epochs are the signal)
- `driftbase history`: Longitudinal behavior tracking
- Early exploration before implementing version tagging

Epoch resolution is **problematic** for:
- `driftbase diff`: Comparing specific deployment versions
- CI/CD gates: Need to know exact version that caused drift
- Root cause attribution: "v2.1.3 broke latency" vs "something changed this week"

## Best Practices

### For Production Deployments
Always tag versions explicitly:

**Option A: Langfuse Release Field (Recommended)**
```python
from langfuse import Langfuse

langfuse = Langfuse()
langfuse.trace(
    name="agent-run",
    release="v2.1.0",  # ← This
    ...
)
```

**Option B: Environment Variable**
```bash
# In your deployment script
export DRIFTBASE_VERSION=v2.1.0
./start-agent.sh
```

**Option C: Metadata Version Tag**
```python
langfuse.trace(
    name="agent-run",
    metadata={"version": "v2.1.0"},  # ← This
    ...
)
```

### For Local Development
Epoch resolution is fine:
```bash
# No version tagging needed for exploration
driftbase connect --project=dev
driftbase diagnose  # Epochs work great here
```

### Checking Version Quality
```bash
# Count runs by version_source
sqlite3 ~/.driftbase/runs.db \
  "SELECT version_source, COUNT(*) FROM agent_runs_local GROUP BY version_source"

# If you see many "epoch" rows, consider adding explicit version tags
```

### Migrating from Epoch to Tagged Versions
```bash
# Before: Epoch-bucketed
$ driftbase diff epoch-2024-03-04 epoch-2024-03-11
⚠ Comparing time-bucketed versions...

# After: Tagged versions
$ export DRIFTBASE_VERSION=v2.1.0
$ driftbase connect --project=prod
$ driftbase diff v2.0.0 v2.1.0
✅ Comparing release-tagged versions (100% confidence)
```

## Troubleshooting

### "Comparing time-bucketed versions" warning
**Problem**: Versions are being resolved from timestamps instead of explicit tags.

**Solution**: Add version tagging (see Best Practices above).

### Mixed version sources in one diff
**Problem**: Some runs have release tags, others are epoch-bucketed.

**Behavior**: If >50% are epoch-bucketed, warning is shown and tier is downgraded.

**Solution**: Ensure all runs in the comparison period have explicit version tags.

### "version_source = none"
**Problem**: Even epoch resolution failed (very rare).

**Solution**: Check that traces have valid timestamps. Contact support if persistent.

## See Also

- [Determinism](determinism.md) - Reproducible drift reports
- [Configuration](configuration.md) - Full configuration options
- [ARCHITECTURE.md](../ARCHITECTURE.md) - Version resolution implementation details
