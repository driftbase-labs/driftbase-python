# Hard Learned Lessons

**These are bugs that cost hours. Never repeat them.**

## SQLModel field naming collision

**Never use `metadata` as a field name in any SQLModel class.**

SQLAlchemy's Declarative API reserves this name globally. You'll get:
```
InvalidRequestError: Attribute name 'metadata' is reserved
```

**Fix:** Use `weights_metadata`, `weights_meta`, or any other name.

Affected: Any new table with metadata fields. Already hit in `LearnedWeightsCache`.

---

## setuptools_scm dirty builds

**Always commit everything before tagging a release.**

Any uncommitted file causes setuptools_scm to produce:
```
0.5.1.dev0+g11e6014c2.d20260329
```
instead of `0.5.1`.

This version string **cannot be uploaded to PyPI** as a clean release. The `400 Bad Request` from twine is confusing—the real cause is the dirty working tree.

**Fix:** `git status` must be clean before `git tag`.

**Pre-flight checklist:**
```bash
git status  # Must show "nothing to commit, working tree clean"
find . -name "*.backup" -delete
find . -name "*.bak" -delete
git tag -a v0.8.0 -m "Release"
```

---

## Backup files in wheel distribution

**Never leave `.backup` files in `src/` — they get packaged into the wheel.**

`setuptools` includes **all files** matching `package-data` patterns. A single `cli_compare.py.backup` file in `src/driftbase/cli/` gets shipped to users.

**Error symptom:** Users report "weird files in site-packages" or import collisions.

**Fix:** Always `git rm` backup files before building, or add to `.gitignore`:
```bash
git rm src/driftbase/cli/*.backup
```

Add to `.gitignore`:
```
*.backup
*.bak
*.orig
```

Affected: Release 0.5.0 (backup file shipped to PyPI).

---

## Rich markup in f-strings crashes on user input

**Never embed dynamic values directly in Rich markup strings.**

```python
# WRONG - crashes if user_value contains brackets
console.print(f"[green]{user_value}[/green]")
```

If `user_value = "[v1.0]"`, Rich interprets `[v1.0]` as markup and crashes.

**Fix:** Use `rich.markup.escape()`:
```python
from rich.markup import escape
console.print(f"[green]{escape(user_value)}[/green]")
```

Or disable markup entirely:
```python
console.print(user_value, markup=False)
```

**Common crash locations:** Version strings, file paths, tool names (all can contain brackets).

---

## @track budget persistence timing

**Budget config must be persisted at the START of the wrapper function, not in the success path only.**

If the agent raises an exception before the success handler runs, the budget config is never saved. Breach detection **silently fails** for all subsequent runs (no breach records, no warnings).

**Wrong:**
```python
def track_wrapper(*args, **kwargs):
    result = agent_fn(*args, **kwargs)
    # Save budget config here — TOO LATE if agent_fn raised
    backend.save_budget_config(...)
    return result
```

**Right:**
```python
def track_wrapper(*args, **kwargs):
    # Save budget config BEFORE running agent
    backend.save_budget_config(...)
    try:
        result = agent_fn(*args, **kwargs)
        return result
    finally:
        # Breach detection runs here
```

Affected: Budget feature (breaches not detected until config fixed manually).

---

## Weights not renormalized after transformation

**Every weight transformation must renormalize to sum=1.0.**

After applying reliability multipliers, correlation adjustments, or redistribution, weights may sum to 0.98 or 1.03 due to floating point errors.

**Symptom:** Drift scores drift upward over time, false positives increase.

**Fix:** Always renormalize after every weight operation:
```python
weights = {k: v * multiplier[k] for k, v in weights.items()}
total = sum(weights.values())
weights = {k: v / total for k, v in weights.items()}  # Renormalize
assert abs(sum(weights.values()) - 1.0) < 0.01
```

**Where this happens:**
- `_compute_correlation_adjustments` (line 647 in baseline_calibrator.py)
- `_redistribute_weights` (line 289 in baseline_calibrator.py)
- `blend_inferences` (line 1358 in use_case_inference.py)

---

## Calibration cache invalidation bug

**Cache key must include run count or timestamp to invalidate on baseline growth.**

If baseline grows from 50→100 runs, calibration should recompute (better statistics). But if cache key is just `{version}:{use_case}`, the stale result persists.

**Fix:** Cache key includes run count check:
```python
cached_total_n = cached.get("run_count_at_calibration", 0)
current_total_n = baseline_n + eval_n
if current_total_n < cached_total_n * 1.20:  # <20% growth, use cache
    return cached
```

Added in calibrate() at line 538.

---

## JSD returns NaN on empty distributions

**Jensen-Shannon divergence is undefined when both distributions are empty.**

```python
base_dist = {}
curr_dist = {}
jsd = _jensen_shannon_divergence(base_dist, curr_dist)
# Returns NaN, crashes downstream
```

**Fix:** Check for empty before computing:
```python
def _jensen_shannon_divergence(p: dict, q: dict) -> float:
    if not p and not q:
        return 0.0  # No drift if both empty
    if not p or not q:
        return 1.0  # Total drift if one empty
    # ... rest of computation
```

Added at diff.py:35.

---

## Power analysis floor=30 prevents differentiation

**Original floor of 50 masked differences between consistent and noisy agents.**

With sigma < 0.12, the formula produces n < 30, which was clamped to 50. All agents looked the same.

**Fix:** Lower floor to 30 for overall, 10 for per-dimension:
```python
overall = max(30, overall)  # Was 50
per_dimension[dim] = max(10, min(200, int(np.ceil(n))))  # Was 50
```

Now differentiation appears for agents with sigma > 0.15.

---

## TIER3 partial logic missing

**Agent with 8/12 reliable dimensions at n=45 (90% of min=50) was stuck in TIER2.**

The power analysis showed 8 dimensions reliable, but tier logic only checked overall n.

**Fix:** Add partial TIER3 override:
```python
if reliable_dimension_count >= 8 and min_n >= 0.8 * min_runs_needed:
    tier = "TIER3"  # Override to TIER3
```

Added at diff.py:511.

---

## LangGraph test flakiness

**`test_langgraph_invoke_captures_tool_sequence` fails intermittently.**

Cause: LangGraph is not a declared dependency. Test works when installed separately, fails in CI.

**Not fixed yet.** Known issue. Do not add langgraph to dependencies (huge transitive deps).

**Workaround:** Skip test in CI or mark as `xfail` until langgraph-core is separated.

---

## Summary

Most expensive bugs:
1. **Dirty git tree → release blocked** (setuptools_scm)
2. **Backup files in wheel** (user-facing breakage)
3. **Budget config not persisted** (feature silently broken)
4. **Weights drift from 1.0** (scoring corruption)
5. **Cache invalidation** (stale calibration)

Pre-flight checks before any release:
```bash
git status  # Clean?
find . -name "*.backup" -delete
PYTHONPATH=src pytest tests/ --tb=short  # All pass?
git tag -a v0.X.0 -m "Release"
```
