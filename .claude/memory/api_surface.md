# API Surface

**Public API contract. Breaking changes require major version bump.**

## @track decorator

**Signature:**
```python
def track(
    agent_id: str | None = None,
    version: str | None = None,
    environment: str = "production",
    budgets: dict[str, Any] | None = None,
    semantic: bool = False,
) -> Callable:
```

**Parameters:**
- `agent_id` (str | None): Unique agent identifier. Auto-detected from function name if None.
- `version` (str | None): Deployment version. Auto-detected from git tag if None.
- `environment` (str): Deployment environment. Default "production".
- `budgets` (dict | None): Budget limits for gating. See BudgetConfig schema.
- `semantic` (bool): Enable semantic clustering (requires [semantic] extra).

**Returns:** Decorated function with identical signature to original.

**Breaking change policy:** Parameter names and types are stable. Adding new optional parameters is non-breaking.

---

## BudgetConfig schema

**Structure:**
```python
{
    "latency_p95_ms": int,           # Max P95 latency
    "error_rate_pct": float,          # Max error rate (0-100)
    "cost_per_run_usd": float,        # Max cost per run
    "avg_token_count": int,           # Max tokens per run
    # Any dimension from DIMENSION_KEYS
}
```

**Validation:** Keys must be from `DIMENSION_KEYS` or special budget keys (latency_p95_ms, etc.). Values must be numeric.

**Breaking change policy:** Adding new dimension keys is non-breaking. Removing or renaming keys is breaking.

---

## DriftReport fields

**Stable fields (never remove):**
```python
drift_score: float                     # [0, 1]
severity: str                          # "none" | "low" | "moderate" | "significant" | "critical"
verdict: str                           # "SHIP" | "MONITOR" | "REVIEW" | "BLOCK"
exit_code: int                         # 0 | 10 | 20 | 30

# Per-dimension scores [0, 1]
decision_drift: float
tool_sequence_drift: float
latency_drift: float
tool_distribution_drift: float
error_drift: float
loop_depth_drift: float
verbosity_drift: float
retry_drift: float
output_length_drift: float
planning_latency_drift: float
semantic_drift: float
tool_sequence_transitions_drift: float

# Context values (before → after)
baseline_p95_latency_ms: int
current_p95_latency_ms: int
baseline_error_rate: float
current_error_rate: float
baseline_escalation_rate: float
current_escalation_rate: float
escalation_rate_delta: float

# Calibration metadata
inferred_use_case: str
use_case_confidence: float
calibration_method: str                # "preset_only" | "statistical" | "learned"
calibrated_weights: dict[str, float]   # Dimension → weight
composite_thresholds: dict[str, float] # "MONITOR" | "REVIEW" | "BLOCK" → threshold

# Confidence tier
confidence_tier: str                   # "TIER1" | "TIER2" | "TIER3"
baseline_n: int
eval_n: int
min_runs_needed: int
runs_needed: int                       # Runs until next tier

# Bootstrap CI (TIER3 only)
drift_score_lower: float | None
drift_score_upper: float | None
confidence_interval_pct: int
bootstrap_iterations: int
```

**Optional fields (may be None):**
- `indicative_signal` (TIER2 only): dict[str, str] — Directional signals (↑↓→)
- `anomaly_signal` (TIER3 only): AnomalySignal object
- `rollback_suggestion` (TIER3 only): RollbackSuggestion object

**Breaking change policy:**
- Never remove or rename stable fields
- Adding new optional fields is non-breaking
- Changing field types is breaking (e.g., str → int)
- Changing verdict values is breaking

---

## CalibrationResult fields

**Stable fields:**
```python
calibrated_weights: dict[str, float]                # Sum to 1.0
thresholds: dict[str, dict[str, float]]            # Per-dimension thresholds
composite_thresholds: dict[str, float]             # Composite thresholds
calibration_method: str                            # "preset_only" | "statistical" | "learned"
baseline_n: int
reliability_multipliers: dict[str, float]
inferred_use_case: str
confidence: float
```

**Optional fields:**
```python
keyword_use_case: str
keyword_confidence: float
behavioral_use_case: str
behavioral_confidence: float
blend_method: str
behavioral_signals: dict[str, float] | None
learned_weights_available: bool
learned_weights_n: int
top_predictors: list[str] | None
correlated_pairs: list[tuple[str, str, float]]
correlation_adjusted: bool
```

**Breaking change policy:** Same as DriftReport.

---

## USE_CASE_WEIGHTS tables

**Structure:**
```python
USE_CASE_WEIGHTS: dict[str, dict[str, float]] = {
    "FINANCIAL": {
        "decision_drift": 0.30,
        "tool_sequence": 0.15,
        # ... 12 dimensions, sum to 1.0
    },
    # ... 14 use cases
}
```

**Invariants:**
- All use case dicts have exactly 12 dimension keys
- All weights sum to 1.0 (within 0.01 tolerance)
- All weights are in [0, 1]

**Breaking change policy:**
- Adding new use cases is non-breaking
- Changing existing weights is non-breaking (user can pin version)
- Adding new dimensions is breaking (requires schema migration)

---

## DIMENSION_KEYS list

**Stable order (v0.5+):**
```python
DIMENSION_KEYS = [
    "decision_drift",
    "tool_sequence",
    "latency",
    "tool_distribution",
    "error_rate",
    "loop_depth",
    "verbosity_ratio",
    "retry_rate",
    "output_length",
    "time_to_first_tool",
    "semantic_drift",
    "tool_sequence_transitions",
]
```

**Breaking change policy:**
- Adding dimensions is breaking (requires schema migration + weight rebalancing)
- Removing dimensions is breaking
- Reordering is non-breaking (but discouraged)

---

## CLI command structure

**Stable commands:**
```bash
driftbase diff <baseline> <current>
driftbase diagnose
driftbase compare <version1> <version2> ...
driftbase demo
driftbase inspect [version]
driftbase chart <dimension>
driftbase cost
driftbase doctor

# Groups
driftbase baseline set <version>
driftbase baseline show
driftbase baseline clear
```

**Breaking change policy:**
- Removing commands is breaking
- Changing required arguments is breaking
- Adding optional flags is non-breaking
- Changing output format is non-breaking (CLI output is not a stable API)

---

## Exit codes

**Stable mapping:**
```python
SHIP = 0         # No significant drift
MONITOR = 10     # Minor drift, watch closely
REVIEW = 20      # Moderate drift, manual review
BLOCK = 30       # Critical drift, do not deploy
```

**Breaking change policy:** Never change these values. Scripts depend on them.

---

## Environment variables

**Stable configuration:**
```bash
DRIFTBASE_DB_PATH                  # Database location
DRIFTBASE_SENSITIVITY              # "strict" | "standard" | "relaxed"
DRIFTBASE_DEFAULT_ENVIRONMENT      # Default environment
DRIFTBASE_TIER1_MIN_RUNS           # TIER1 threshold (default 15)
DRIFTBASE_PRODUCTION_MIN_SAMPLES   # Legacy, prefer power analysis
```

**Breaking change policy:**
- Removing env vars is breaking
- Renaming env vars is breaking
- Changing default values is non-breaking (user can set explicitly)

---

## Database schema (SQLModel)

**Stable tables:**
- `agent_runs_local` — Core run records
- `calibration_cache` — Calibration results
- `budget_configs` — Budget definitions
- `budget_breaches` — Breach events
- `change_events` — Change tracking
- `deploy_outcomes` — Deploy labels for learning
- `learned_weights_cache` — Learned weights
- `significance_thresholds` — Power analysis thresholds

**Breaking change policy:**
- Adding tables is non-breaking
- Adding columns is non-breaking (requires migration)
- Removing/renaming columns is breaking (requires migration)
- Dropping tables is breaking

**Migration strategy:** Use `ALTER TABLE ADD COLUMN` with defaults in `_migrate_schema()`.

---

## Python version support

**Current:** Python 3.9+

**Breaking change policy:**
- Dropping Python 3.9 support is breaking (requires major version bump)
- Adding support for newer Python is non-breaking

---

## Summary

**Absolutely stable (never breaking):**
- @track decorator signature
- DriftReport stable fields
- Exit codes (0/10/20/30)
- CLI command names
- Database table names

**Semi-stable (breaking with migration):**
- Database columns (add via ALTER TABLE)
- DIMENSION_KEYS (requires rebalancing)
- USE_CASE_WEIGHTS values

**Unstable (can change in minor versions):**
- CLI output format
- Weight values (preset tables)
- Threshold computation formulas
- Internal module structure
