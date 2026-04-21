# Determinism in Driftbase

Driftbase provides deterministic drift detection, ensuring that running the same analysis twice on identical data produces identical results.

## When Reports Are Identical

Two `driftbase diff` invocations produce byte-identical reports when:
1. **Same data**: Identical run sets for both baseline and current versions
2. **Same seed**: Same `DRIFTBASE_SEED` environment variable (default: 42)
3. **Same config**: Identical values for `DRIFTBASE_FINGERPRINT_LIMIT` and `DRIFTBASE_BOOTSTRAP_ITERS`

Example:
```bash
# First run
DRIFTBASE_SEED=42 driftbase diff v1.0 v2.0 > report1.txt

# Second run - identical result
DRIFTBASE_SEED=42 driftbase diff v1.0 v2.0 > report2.txt

# Verify
diff report1.txt report2.txt  # No output = identical
```

## When Reports May Differ

Reports will differ when:
1. **Different seed**: Different `DRIFTBASE_SEED` values produce different bootstrap confidence intervals
2. **Different sampling**: If runs exceed `DRIFTBASE_FINGERPRINT_LIMIT`, different random samples are drawn
3. **Different data**: New runs added between invocations
4. **Different config**: Changed sampling or bootstrap parameters

## Reproducing Another User's Report

To reproduce a drift report from another developer or CI run:

### 1. Match the Environment
```bash
# Use the same seed (check their env or CI config)
export DRIFTBASE_SEED=42

# Match sampling config (usually defaults are fine)
export DRIFTBASE_FINGERPRINT_LIMIT=5000
export DRIFTBASE_BOOTSTRAP_ITERS=500
```

### 2. Ensure Identical Data
```bash
# Option A: Import from the same Langfuse project at the same time
driftbase connect --project=prod --since=2024-01-01 --limit=10000

# Option B: Export and share the database file
# From original machine:
cp ~/.driftbase/runs.db /path/to/shared/runs.db

# On reproducing machine:
export DRIFTBASE_DB_PATH=/path/to/shared/runs.db
```

### 3. Run the Same Command
```bash
driftbase diff v1.0 v2.0
```

The drift score, confidence intervals, and verdict should match exactly.

## Technical Details

### Seeded Randomness

All random operations use `numpy.random.Generator` seeded with `DRIFTBASE_SEED`:
- **Bootstrap resampling**: For confidence interval calculation
- **Sampling**: When run count exceeds `DRIFTBASE_FINGERPRINT_LIMIT`
- **Anomaly detection**: IsolationForest random state

### Salt-Based Streams

Different operations use different random streams (via salt) to avoid correlation:
```python
# Different salts for different operations
bootstrap_rng = get_rng("bootstrap:v1-v2")
sampling_rng = get_rng("sampling:fingerprint")
```

This ensures:
- Reproducibility: Same seed → same results
- Independence: Different operations don't interfere

### Limitations

Determinism applies to:
- ✅ Drift scores and dimension scores
- ✅ Bootstrap confidence intervals
- ✅ Anomaly detection scores
- ✅ Verdict outcomes

Non-deterministic aspects:
- ⚠️ Timestamps of when analysis was run
- ⚠️ Database write order (doesn't affect analysis)
- ⚠️ Floating point rounding differences across platforms (rare, negligible impact)

## Best Practices

1. **CI/CD**: Pin `DRIFTBASE_SEED` in CI config for reproducible builds
2. **Debugging**: Use explicit seeds when investigating drift score changes
3. **Sharing**: Share both `runs.db` and environment config when asking for help
4. **Testing**: Use different seeds to verify stability across bootstrap samples

## See Also

- [Configuration](configuration.md) - Full list of configuration options
- [Version Resolution](version-resolution.md) - How Driftbase determines versions
