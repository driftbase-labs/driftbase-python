# Testing Skill

**Read this skill before writing tests or modifying test patterns.**

## Test Framework

Uses **pytest** with standard conventions:

```bash
# Run all tests
PYTHONPATH=src pytest tests/ --tb=short

# Run specific test
PYTHONPATH=src pytest tests/test_diff.py::test_compute_drift -v

# Run with coverage
PYTHONPATH=src pytest tests/ --cov=driftbase --cov-report=term-missing
```

**Always use `PYTHONPATH=src` to ensure imports work correctly.**

## Test File Organization

```
tests/
  test_anomaly_detector.py        — Anomaly detection logic
  test_baseline_calibrator.py     — Calibration pipeline
  test_budget.py                  — Budget breach detection
  test_confidence_tiers.py        — Tier classification
  test_diff_calibration_integration.py  — End-to-end diff with calibration
  test_e2e.py                     — Full SDK integration tests
  test_power_analysis.py          — Power analysis formulas
  test_rootcause.py               — Root cause analysis
  test_track.py                   — @track decorator
  test_use_case_inference.py      — Keyword + behavioral classifiers
  test_verdict.py                 — Verdict logic
  test_weight_learner.py          — Learned weights system
```

**No conftest.py currently exists.** Tests are self-contained.

## Fixture Pattern

Use `tmp_path` for isolated databases:

```python
def test_something(tmp_path):
    db_path = str(tmp_path / "test.db")
    backend = SQLiteBackend(db_path)
    # ... test logic
```

This ensures each test gets a clean database and no state leaks between tests.

## Testing the Calibration Pipeline

When testing use case inference, blending, or calibration:

```python
def test_weights_sum_to_one():
    """Weights must always sum to 1.0 after calibration."""
    # ... run calibration
    total = sum(result.calibrated_weights.values())
    assert abs(total - 1.0) < 0.01, f"Weights sum to {total}"
```

**This invariant test is critical.** Add it to every test that touches weights.

## Testing the "Never Raise" Constraint

Scoring functions must degrade gracefully:

```python
def test_infer_use_case_never_raises():
    """Use case inference must never raise, even on garbage input."""
    result = infer_use_case([])
    assert result["use_case"] == "GENERAL"

    result = infer_use_case(["", None, 123, {"invalid": "type"}])
    assert result["use_case"] == "GENERAL"
    assert result["confidence"] == 0.0
```

For every scoring function, write a test that passes invalid input and asserts no exception.

## Testing Power Analysis

```python
def test_min_runs_needed_increases_with_variance():
    """Higher variance dimensions should require more runs."""
    low_variance = [0.1] * 50
    high_variance = [0.0, 0.5] * 25  # Same mean, higher variance

    result_low = compute_min_runs_needed({"dim": low_variance}, "GENERAL")
    result_high = compute_min_runs_needed({"dim": high_variance}, "GENERAL")

    assert result_high["overall"] > result_low["overall"]
```

Validate the mathematical properties of the formula, not just "it returns a number."

## Testing Confidence Tiers

```python
def test_tier1_no_scores():
    """TIER1 should never return numeric scores or verdicts."""
    # ... compute drift with n < 15
    assert report.confidence_tier == "TIER1"
    assert report.drift_score == 0.0
    assert "indicative_signal" not in report

def test_tier2_directional_only():
    """TIER2 should return directional signals but no verdict."""
    # ... compute drift with 15 <= n < 50
    assert report.confidence_tier == "TIER2"
    assert report.indicative_signal is not None
    assert report.verdict is None

def test_tier3_full_report():
    """TIER3 should return full scores + verdict + CI."""
    # ... compute drift with n >= 50
    assert report.confidence_tier == "TIER3"
    assert report.drift_score > 0
    assert report.verdict in ["SHIP", "MONITOR", "REVIEW", "BLOCK"]
    assert report.drift_score_lower is not None
```

## Mocking Pattern

For integration tests, mock framework APIs:

```python
from unittest.mock import MagicMock, patch

def test_track_decorator_with_langchain():
    with patch("langchain.agents.AgentExecutor") as mock_executor:
        mock_executor.return_value.run.return_value = "output"

        @track(agent_id="test", version="v1.0")
        def agent_fn(input_text):
            return mock_executor().run(input_text)

        result = agent_fn("test input")

        # Verify tracking occurred
        backend = get_backend()
        runs = backend.get_runs(deployment_version="v1.0")
        assert len(runs) == 1
```

## Testing Bootstrap CI

```python
def test_bootstrap_ci_contains_point_estimate():
    """Bootstrap 95% CI must contain the point estimate."""
    # ... compute drift with baseline_runs and current_runs
    assert report.drift_score_lower <= report.drift_score
    assert report.drift_score <= report.drift_score_upper
```

## Testing Learned Weights

```python
def test_learned_weights_blend_preserves_sum():
    """Blending learned weights with calibrated weights must preserve sum=1.0."""
    # ... calibrate with learned weights available
    total = sum(calibration.calibrated_weights.values())
    assert abs(total - 1.0) < 0.01
```

## Testing Correlation Adjustment

```python
def test_correlation_adjustment_reduces_less_important():
    """Correlated dimensions should have less important one reduced."""
    # Create baseline with known correlation
    baseline_runs = [
        {"latency_ms": i * 100, "retry_count": i, ...} for i in range(50)
    ]
    # ... run calibration
    # Verify one of latency/retry_rate was reduced
```

## Assertion Patterns

### Numerical comparisons
```python
assert abs(actual - expected) < 0.01  # Floating point tolerance
```

### Weights
```python
assert abs(sum(weights.values()) - 1.0) < 0.01
```

### Scores in range
```python
assert 0.0 <= drift_score <= 1.0
```

### No exceptions
```python
try:
    result = function_that_should_not_raise(bad_input)
except Exception as e:
    pytest.fail(f"Function raised unexpectedly: {e}")
```

## Test Data Generation

Use simple, deterministic data:

```python
def make_runs(n: int, version: str, error_rate: float = 0.0) -> list[dict]:
    """Generate n synthetic runs with specified error rate."""
    runs = []
    for i in range(n):
        runs.append({
            "id": f"run_{i}",
            "deployment_version": version,
            "tool_sequence": json.dumps(["tool1", "tool2"]),
            "error_count": 1 if (i / n) < error_rate else 0,
            "latency_ms": 1000 + (i * 10),
            "started_at": datetime.utcnow(),
            # ... other required fields
        })
    return runs
```

**Keep test data simple and readable.** Don't use production data or complex fixtures.

## Parametrized Tests

For testing multiple inputs:

```python
@pytest.mark.parametrize("use_case,expected_weight", [
    ("FINANCIAL", 0.30),
    ("CUSTOMER_SUPPORT", 0.26),
    ("GENERAL", 0.22),
])
def test_decision_drift_weight_by_use_case(use_case, expected_weight):
    from driftbase.local.use_case_inference import USE_CASE_WEIGHTS
    actual = USE_CASE_WEIGHTS[use_case]["decision_drift"]
    assert abs(actual - expected_weight) < 0.01
```

## Testing CLI Commands

Use Click's `CliRunner`:

```python
from click.testing import CliRunner
from driftbase.cli.cli import cli

def test_diff_command(tmp_path):
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        # Setup test database
        # ...
        result = runner.invoke(cli, ["diff", "v1.0", "v2.0"])
        assert result.exit_code == 0
        assert "drift_score" in result.output
```

## Test Coverage Guidelines

Aim for:
- **90%+ coverage** on scoring pipeline (use_case_inference, baseline_calibrator, diff)
- **80%+ coverage** on storage backend
- **70%+ coverage** on CLI commands (harder to test, less critical)

Don't aim for 100% — diminishing returns.

## Common Test Mistakes

1. **Testing implementation, not behavior** — Test "weights sum to 1.0", not "loop ran 12 times"
2. **No isolation** — Always use `tmp_path` for databases
3. **Brittle assertions** — Use tolerances for floats, not exact equality
4. **Missing edge cases** — Test empty inputs, zero variance, conflicting use cases
5. **Forgetting never-raise constraint** — Every scoring function needs a "garbage input" test

## Running Tests in CI

Tests should pass with:
```bash
PYTHONPATH=src pytest tests/ --tb=short
```

No environment variables required (except `PYTHONPATH`). Tests must be hermetic.

## Summary

- Use pytest with `PYTHONPATH=src`
- Use `tmp_path` fixture for isolated databases
- Test the invariants: weights sum to 1.0, scores in [0, 1], never raise
- Keep test data simple and deterministic
- Use CliRunner for CLI tests, never shell out
- No async tests needed (synchronous storage only)
- Test behavior, not implementation
