# Run Quality Scoring

## Overview

Every run in Driftbase is assigned a **quality score** (0.0-1.0) that measures how reliable and complete the trace data is for drift analysis. This score is computed automatically during feature derivation and stored in the `runs_features.run_quality` column.

**Current status (v0.11.1):** Quality scores are computed and stored but **not yet used** in fingerprint weighting or drift detection. Phase 2c will add optional quality-weighted fingerprinting.

## Why Quality Matters

Not all traces are equally valuable for drift detection:

- A trace with explicit version tags (`release` field) is more trustworthy than one with a time-bucketed fallback version (`epoch-2026-01-15`)
- A trace with complete input/output data and token counts provides richer signal than one with missing fields
- A trace where feature derivation succeeded is more reliable than one that failed
- A trace with tool usage data and semantic clustering is more informative than one without

Quality scoring makes these differences explicit and measurable.

## Scoring Rubric

The quality score is a **weighted average of four components** (each weighted 0.25):

### 1. Version Clarity (25%)

**How was the deployment version resolved?**

| Version Source | Score | Meaning |
|----------------|-------|---------|
| `release` or `tag` | 1.0 | Explicit version from trace or tag |
| `env` | 0.7 | Environment variable fallback (DRIFTBASE_VERSION) |
| `epoch` | 0.3 | Time-bucketed fallback (Monday of week) |
| `unknown` or `none` | 0.0 | No version information available |

**Why it matters:** Epoch-based versions bucket unrelated runs together, increasing false positive rate in drift detection. Explicit versions enable precise version-to-version comparison.

### 2. Data Completeness (25%)

**How much raw trace data was captured?**

| Field Present | Points |
|---------------|--------|
| Non-empty `input` | +0.25 |
| Non-empty `output` | +0.25 |
| `latency_ms > 0` | +0.20 |
| Token counts (any of prompt/completion/total > 0) | +0.15 |
| Non-empty `session_id` | +0.15 |

**Capped at 1.0.** Missing input/output fields mean fingerprint features like verbosity ratio and semantic clustering are unreliable.

### 3. Feature Derivability (25%)

**Did feature derivation succeed?**

| Schema Version | Score | Meaning |
|----------------|-------|---------|
| `feature_schema_version > 0` | 1.0 | Successful derivation |
| `feature_schema_version == -1` | 0.0 | Failed derivation (error logged in `derivation_error`) |

**Why it matters:** Failed derivations produce sentinel values (-1, empty strings) that skew fingerprints.

### 4. Observation Richness (25%)

**How much behavioral signal is available?**

| Signal Present | Points |
|----------------|--------|
| `tool_sequence` with ≥ 1 tool | +0.4 |
| `tool_call_count > 0` | +0.2 |
| `semantic_cluster != "unknown"` | +0.2 |
| `retry_count > 0` or `loop_count > 0` | +0.2 |

**Capped at 1.0.** Tool-related features are critical for decision drift detection.

## Final Score Calculation

```python
score = (
    0.25 * version_clarity
    + 0.25 * data_completeness
    + 0.25 * feature_derivability
    + 0.25 * observation_richness
)
```

Rounded to 4 decimal places. On any exception during computation, returns `0.0` (never raises).

## Examples

### Perfect Quality Run (score ≈ 1.0)

```python
RunRaw(
    version_source="release",          # +1.0 × 0.25 = 0.25
    input="What's the weather?",       # +0.25
    output="Sunny, 72°F",              # +0.25
    latency_ms=150,                    # +0.20
    tokens_prompt=10,                  # +0.15
    tokens_completion=20,              # (already counted)
    session_id="sess-123"              # +0.15
)                                      # Data completeness: 1.0 × 0.25 = 0.25

RunFeatures(
    feature_schema_version=1,          # +1.0 × 0.25 = 0.25
    tool_sequence='["get_weather"]',   # +0.4
    tool_call_count=1,                 # +0.2
    semantic_cluster="resolved",       # +0.2
    loop_count=0                       # +0.0
)                                      # Observation richness: 0.8 × 0.25 = 0.2

# Total: 0.25 + 0.25 + 0.25 + 0.2 = 0.95
```

### Minimal Quality Run (score = 0.0)

```python
RunRaw(
    version_source="unknown",          # +0.0 × 0.25 = 0.0
    input="",                          # +0.0
    output="",                         # +0.0
    latency_ms=0,                      # +0.0
    tokens_prompt=None,                # +0.0
    session_id=""                      # +0.0
)                                      # Data completeness: 0.0 × 0.25 = 0.0

RunFeatures(
    feature_schema_version=-1,         # +0.0 × 0.25 = 0.0 (failed derivation)
    tool_sequence="[]",                # +0.0
    tool_call_count=0,                 # +0.0
    semantic_cluster="unknown"         # +0.0
)                                      # Observation richness: 0.0 × 0.25 = 0.0

# Total: 0.0 + 0.0 + 0.0 + 0.0 = 0.0
```

## Inspecting Quality Scores

### View distribution

```bash
driftbase migrate --status
```

Output includes:

```
Quality scored runs     1,245 / 1,500    83.0%
Quality distribution                     min=0.42, median=0.78, max=0.95
```

Runs with `run_quality=0.0` are either:
- Migrated rows from v0.10 (not yet backfilled)
- New runs where derivation failed

### Backfill migrated rows

Migrated rows from `agent_runs_local` have `feature_source="migrated"` and `run_quality=0.0` by default. To compute quality for these rows:

```bash
driftbase migrate --backfill
```

This re-derives features (including quality scores) for all migrated rows.

### Query directly

```sql
SELECT
    deployment_version,
    AVG(run_quality) as avg_quality,
    MIN(run_quality) as min_quality,
    MAX(run_quality) as max_quality
FROM runs_raw r
JOIN runs_features f ON r.id = f.run_id
WHERE f.run_quality > 0.0
GROUP BY deployment_version
ORDER BY avg_quality DESC;
```

## Future: Quality-Weighted Fingerprinting (Phase 2c)

Currently, quality scores are **stored but not used**. Phase 2c will add:

1. **Optional quality weighting** in `build_fingerprint_from_runs()`:
   ```python
   fingerprint = build_fingerprint_from_runs(
       runs, ..., weight_by_quality=True
   )
   ```

2. **Low-quality run filtering**:
   - Exclude runs with `run_quality < 0.3` from fingerprints (configurable threshold)
   - Reduces noise from incomplete/failed traces

3. **Quality distribution in reports**:
   - DriftReport includes `baseline_quality_dist` and `current_quality_dist`
   - Warnings if quality significantly degrades between versions

## Design Rationale

### Why four equal-weighted components?

The four components capture orthogonal dimensions of trace quality:
- **Version clarity** → affects comparison validity
- **Data completeness** → affects feature accuracy
- **Feature derivability** → affects analysis reliability
- **Observation richness** → affects behavioral signal strength

Equal weighting (0.25 each) avoids premature optimization. Phase 2c user feedback will inform refinement.

### Why not use quality scores now?

False positive risk. Introducing quality weighting changes fingerprint computation, which changes drift scores. We need:
1. Baseline quality distributions from real-world data (Phase 2c collection)
2. A/B tests showing quality weighting reduces false positives without hiding true drift
3. User feedback on thresholds (what quality level is "too low"?)

Storing quality now enables Phase 2c experiments without schema changes.

## Implementation

- **Computation:** `src/driftbase/local/run_quality.py:compute_run_quality()`
- **Storage:** `runs_features.run_quality` column (REAL, default 0.0)
- **Derivation:** Called automatically in `feature_deriver.py:derive_features()`
- **Migration:** Added in v0.11.1 (idempotent ALTER TABLE)

Never raises exceptions — returns `0.0` on any error.
