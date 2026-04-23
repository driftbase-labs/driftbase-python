# Fingerprint Schema Debt

This document tracks known divergences between the 12-dimension drift schema field names and their current implementations. The 12-field schema is a **public contract** — field names are stable and will not change. However, implementations may evolve over time.

This file documents where current behavior differs from what field names suggest, why each divergence exists, and when each is scheduled for resolution.

---

## 1. `output_drift` vs `output_length_drift` (Duplicate Fields)

### Current Behavior
- Both fields exist in `DriftReport`
- Both are computed from `avg_output_length` delta
- `output_drift` uses raw delta: `abs(current - baseline) / baseline`
- `output_length_drift` uses same calculation
- Both contribute to composite score with separate weights

### What Should Happen
- One canonical field for output length changes
- One of the fields deprecated with backward-compat shim
- Clear semantic distinction if both are retained

### Why This Exists
- Historical artifact from schema evolution
- `output_drift` predates addition of new behavioral dimensions
- `output_length_drift` added in Phase 1 without consolidation

### Resolution Target
- **Phase**: Future major version (not before Phase 6)
- **Action**: Canonicalize to `output_length_drift`, deprecate `output_drift`
- **Migration**: Add shim that aliases `output_drift` → `output_length_drift` for one major version
- **Breaking Change**: Remove `output_drift` in next major version after deprecation

---

## 2. `tool_distribution` Weight (No Dedicated Computation)

### Current Behavior
- `tool_distribution` has a weight in calibrated weights dict
- Weight is applied to `decision_drift` as a **proxy**
- No separate JSD computation on tool frequency distributions
- Composite score calculation: `w_tool_dist * decision_drift`

### What Should Happen
- Separate JSD computation on tool call frequency distributions
- Example: baseline uses `search:60%, write:30%, read:10%` vs current uses `search:40%, write:40%, read:20%`
- Would detect shifts in tool usage patterns independent of sequencing

### Why This Exists
- `tool_sequence_distribution` already captures tool ordering patterns via JSD
- Separate tool frequency distribution requires additional fingerprint aggregation
- Current proxy captures most tool-related drift via sequencing changes

### Resolution Target
- **Phase**: Phase 2 or Phase 5 (paired with bigram work)
- **Action**: Add `tool_frequency_distribution` to `BehavioralFingerprint`
- **Action**: Compute separate JSD for tool frequency in `diff.py`
- **Migration**: Existing diffs continue using proxy; new fingerprints gain real computation

---

## Process for Adding New Debt

When adding a new divergence to this file:

1. **Current Behavior**: Describe exactly what the code does today
2. **What Should Happen**: Define the ideal implementation
3. **Why This Exists**: Explain the design decision or constraint
4. **Resolution Target**: Specify phase and migration strategy

## Process for Resolving Debt

When closing out a debt item:

1. Implement the ideal behavior
2. Add migration notes to CHANGELOG
3. Update this file to mark the item as **RESOLVED** with version number
4. Move resolved items to a "Historical Debt (Resolved)" section at bottom of file

---

## Historical Debt (Resolved)

### ✅ `tool_sequence_transitions_drift` (Aliased to `decision_drift`) — RESOLVED in Phase 5

**Resolution**: Implemented bigram-based transition detection in Phase 5.
- Added `bigram_distribution` field to `BehavioralFingerprint` (stores JSON-encoded bigram frequency distribution)
- Added `compute_bigram_jsd()` to `stats/ngrams.py` (computes Jensen-Shannon divergence on bigram distributions)
- Updated `diff.py` to compute real bigram JSD instead of aliasing to `decision_drift`
- Preset weights in `use_case_inference.py` already defined (0.02-0.08 depending on use case)

**What Changed**:
- Baseline behavior: `tool_sequence_transitions_drift = decision_drift` (proxy)
- New behavior: `tool_sequence_transitions_drift = compute_bigram_jsd(baseline_bigram_dist, current_bigram_dist)` (real computation)
- Detects tool order changes that full-sequence comparison misses (e.g., `[A,B,C]` vs `[A,C,B]` — same tools, different transitions)

**Migration**: Existing fingerprints without `bigram_distribution` return empty dict → JSD returns 0.0 (graceful degradation). New fingerprints gain real signal.

---

## See Also

- [CLAUDE.md](../CLAUDE.md) - Repo rules and architecture overview
- [ARCHITECTURE.md](../ARCHITECTURE.md) - Detailed implementation notes
- [12-dimension rationale](.claude/decisions/015-12-dimensions-rationale.md) - Why 12 dimensions were chosen
