# Troubleshooting Guide

**Common error messages and how to fix them.**

## Installation Issues

### "No module named 'driftbase'"

**Symptom:**
```bash
ImportError: No module named 'driftbase'
```

**Cause:** Package not installed or wrong Python environment.

**Fix:**
```bash
pip install driftbase
# Or for development
pip install -e .
```

**Verify:**
```bash
python -c "import driftbase; print(driftbase.__version__)"
```

---

### "No module named 'light_embed'"

**Symptom:**
```bash
ModuleNotFoundError: No module named 'light_embed'
```

**Cause:** Semantic features require optional dependency.

**Fix:**
```bash
pip install driftbase[semantic]
```

Or disable semantic features:
```python
@track(agent_id="test", semantic=False)  # Default is False
```

---

## Runtime Errors

### "InvalidRequestError: Attribute name 'metadata' is reserved"

**Symptom:**
```
sqlalchemy.exc.InvalidRequestError: Attribute name 'metadata' is reserved
```

**Cause:** SQLModel field named `metadata` (reserved by SQLAlchemy).

**Fix:** Rename field to `weights_metadata`, `meta`, or any other name.

**In code:**
```python
# Wrong
class MyModel(SQLModel, table=True):
    metadata: str = "{}"

# Right
class MyModel(SQLModel, table=True):
    weights_metadata: str = "{}"
```

---

### "MarkupError: Tag not closed properly"

**Symptom:**
```
rich.errors.MarkupError: Tag 'v1' in 'Running [v1.0]' is not closed properly
```

**Cause:** Rich interprets `[v1.0]` as markup tag.

**Fix:** Escape brackets or disable markup:
```python
from rich.markup import escape
console.print(f"Running {escape(version)}")

# Or
console.print(f"Running {version}", markup=False)
```

---

### "AssertionError: Weights sum to 0.98"

**Symptom:**
```
AssertionError: Blended weights sum to 0.982, expected 1.0
```

**Cause:** Weights not renormalized after transformation.

**Fix:** Always renormalize after weight operations:
```python
weights = apply_transformation(weights)
total = sum(weights.values())
weights = {k: v / total for k, v in weights.items()}
```

---

## Database Errors

### "OperationalError: no such table: agent_runs_local"

**Symptom:**
```
sqlite3.OperationalError: no such table: agent_runs_local
```

**Cause:** Database schema not initialized or corrupted.

**Fix:**
```bash
# Delete old database and let it reinitialize
rm ~/.driftbase/driftbase.db

# Or set custom path
export DRIFTBASE_DB_PATH=/tmp/driftbase.db
```

Schema will be created automatically on first run.

---

### "IntegrityError: UNIQUE constraint failed"

**Symptom:**
```
sqlite3.IntegrityError: UNIQUE constraint failed: calibration_cache.cache_key
```

**Cause:** Attempting to write duplicate calibration cache entry.

**Fix:** Clear cache and recompute:
```python
backend = get_backend()
backend.set_calibration_cache(cache_key, data)  # Overwrites existing
```

Or use SQL:
```bash
sqlite3 ~/.driftbase/driftbase.db "DELETE FROM calibration_cache WHERE cache_key = '...'"
```

---

## Tracking Issues

### "@track decorator not capturing runs"

**Symptom:** `driftbase diff` shows "No runs found for version v1.0"

**Cause:** Decorator not persisting runs (exception during tracking, or session not drained).

**Debug:**
```python
from driftbase.backends.factory import get_backend
backend = get_backend()
runs = backend.get_runs()
print(f"Total runs in DB: {len(runs)}")
```

**Common causes:**
1. Exception during agent execution (run not persisted)
2. Database path misconfigured
3. Budget persistence failure

**Fix:**
```python
# Ensure decorator is applied correctly
@track(agent_id="my-agent", version="v1.0")
def agent_fn(input):
    return result

# Force flush after running
from driftbase.local.local_store import drain_local_store
drain_local_store(timeout=5.0)
```

---

### "Budget breaches not detected"

**Symptom:** Agent exceeds budget but no breach recorded.

**Cause:** Budget config not persisted before first run.

**Fix:** Budget config must be saved at decorator call time (not in success path). See hard_learned_lessons.md.

**Verify budget saved:**
```python
backend = get_backend()
# Check if budget config exists for agent+version
```

---

## Scoring Issues

### "Drift score always 0.0"

**Symptom:** All diffs show drift_score=0.0 regardless of changes.

**Cause:** Insufficient data (n < 15) or all runs identical.

**Fix:**
1. Check sample size: `driftbase diff --verbose`
2. Verify runs are different:
   ```python
   runs = backend.get_runs(deployment_version="v1.0")
   print(runs[0]["tool_sequence"])
   print(runs[1]["tool_sequence"])
   ```

---

### "Drift score > 1.0"

**Symptom:** Drift score exceeds 1.0 (should be clamped to [0, 1]).

**Cause:** Weights don't sum to 1.0 (bug in calibration).

**Fix:** Verify weights:
```python
calibration = calibrate(...)
total = sum(calibration.calibrated_weights.values())
assert abs(total - 1.0) < 0.01, f"Weights sum to {total}"
```

---

### "Verdict is BLOCK but drift_score is low"

**Symptom:** drift_score=0.12 but verdict=BLOCK

**Cause:** Anomaly override (multivariate detection escalated verdict).

**Check:**
```python
print(report.anomaly_override)  # True if anomaly escalated
print(report.anomaly_override_reason)
```

Anomaly detector uses Isolation Forest on all 12 dimensions. It can detect outliers missed by composite score.

---

## CLI Issues

### "No such command 'watch'"

**Symptom:**
```bash
$ driftbase watch
Error: No such command 'watch'
```

**Cause:** Monitoring commands removed from free SDK.

**Fix:** Use pre-production analysis commands:
```bash
driftbase diff v1.0 v2.0   # Compare versions
driftbase diagnose         # Check agent health
```

`watch`, `tail`, `status`, `push` are Pro tier only.

---

### "Permission denied" when writing database

**Symptom:**
```
PermissionError: [Errno 13] Permission denied: '/Users/.../.driftbase/driftbase.db'
```

**Cause:** Database directory not writable.

**Fix:**
```bash
# Fix permissions
chmod 755 ~/.driftbase

# Or use custom path
export DRIFTBASE_DB_PATH=~/Documents/driftbase.db
```

---

## Power Analysis Issues

### "min_runs_needed is 200 (too high)"

**Symptom:** Power analysis returns min_runs_needed=200 (capped value).

**Cause:** High baseline variance (sigma > 0.3) for some dimension.

**Fix:**
1. Identify noisy dimension:
   ```python
   result = compute_min_runs_needed(dimension_scores, "GENERAL")
   print(result["limiting_dimension"])
   ```
2. If dimension is consistently noisy (high CV), consider if it's measuring signal or noise.

**Not fixable:** Some agents genuinely have high variance. 200 is the cap.

---

### "Power analysis used=False despite n=60"

**Symptom:** Report shows `power_analysis_used=False` even with sufficient data.

**Cause:** Power analysis requires baseline_runs to be passed to compute_drift().

**Fix:**
```python
# Wrong
report = compute_drift(baseline_fp, current_fp)

# Right
report = compute_drift(
    baseline_fp,
    current_fp,
    baseline_runs=baseline_runs,
    current_runs=current_runs,
)
```

---

## Bootstrap CI Issues

### "Bootstrap CI is [0.05, 0.95] (too wide)"

**Symptom:** Bootstrap confidence interval spans most of [0, 1] range.

**Cause:** High variance + small sample size (n < 30).

**Fix:** Collect more data. Bootstrap CI width is correct—it reflects uncertainty.

**Not a bug:** Wide CI means "we're not sure." This is honest.

---

### "drift_score outside CI bounds"

**Symptom:** drift_score=0.22 but CI is [0.18, 0.21]

**Cause:** Point estimate can exceed CI bounds when distribution is skewed.

**Fix:** Code forces point estimate into CI:
```python
report.drift_score_lower = min(report.drift_score_lower, report.drift_score)
report.drift_score_upper = max(report.drift_score_upper, report.drift_score)
```

If still happening, file a bug.

---

## Release Issues

### "twine upload fails with 400 Bad Request"

**Symptom:**
```
HTTPError: 400 Bad Request
```

**Cause:** Version string is dirty (e.g., `0.8.0.dev0+g1234567`).

**Fix:**
```bash
# Verify working tree is clean
git status

# Verify no uncommitted files
git diff-index --quiet HEAD

# Re-tag
git tag -d v0.8.0  # Delete old tag
git tag -a v0.8.0 -m "Release v0.8.0"
```

Rebuild and upload.

---

### "Backup file in wheel"

**Symptom:** User reports `.backup` file in site-packages.

**Cause:** Backup files in src/ get packaged.

**Fix:**
```bash
find . -name "*.backup" -delete
git status  # Ensure clean
rm -rf dist/ build/ *.egg-info
python -m build
```

---

## Summary

**Most common issues:**
1. Weights not summing to 1.0 (renormalize after transforms)
2. Rich markup crashes (escape brackets)
3. Database permissions (use custom path)
4. Tracking not persisting (budget config timing)
5. Power analysis not running (pass baseline_runs)

**When stuck:**
1. Check `driftbase doctor` output
2. Enable verbose logging: `import logging; logging.basicConfig(level=logging.DEBUG)`
3. Inspect database: `sqlite3 ~/.driftbase/driftbase.db ".tables"`
4. Verify weights sum to 1.0
5. Check git status before release
