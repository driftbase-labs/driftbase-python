# Bigram Tool Sequence Detection

## Overview

Bigram-based tool sequence detection catches **order changes** that full-sequence comparison misses. Instead of comparing entire tool sequences, it compares the frequency distribution of **consecutive tool pairs** (bigrams).

## Problem Statement

Full-sequence JSD can miss important behavioral changes when:
- Tools are reordered but the set of tools stays the same
- Transition patterns change without changing the tool inventory
- Workflow logic changes order of operations

**Example:**
- Baseline: `[search, read, write]` → bigrams: `[(search, read), (read, write)]`
- Current: `[search, write, read]` → bigrams: `[(search, write), (write, read)]`

Full-sequence JSD shows high drift because sequences differ. But what if you want to detect **subtle reorderings**?

Bigrams capture this: same 3 tools, different **transitions** between them.

## How It Works

### 1. Bigram Extraction

For each tool sequence, extract consecutive pairs:
```python
tools = ["search", "read", "write"]
bigrams = [("search", "read"), ("read", "write")]
```

### 2. Distribution Computation

Aggregate bigrams across all runs to get frequency distribution:
```python
sequences = [
    ["search", "read", "write"],
    ["search", "read", "write"],
    ["search", "write", "read"],
]
# Bigram distribution:
# ("search", "read"): 0.4 (2/5)
# ("read", "write"): 0.2 (1/5)
# ("search", "write"): 0.2 (1/5)
# ("write", "read"): 0.2 (1/5)
```

### 3. Jensen-Shannon Divergence

Compare baseline vs current bigram distributions using JSD (Jensen-Shannon Divergence):
- 0.0 = identical transition patterns
- 1.0 = completely different transition patterns

## Implementation

### Module: `src/driftbase/stats/ngrams.py`

Functions:
- `compute_bigrams(tool_sequence: str) -> list[tuple[str, str]]`
- `compute_bigram_distribution(tool_sequences: list[str]) -> dict[str, float]`
- `compute_bigram_jsd(baseline_dist, current_dist) -> float`

### Fingerprint Field

`BehavioralFingerprint.bigram_distribution: str | None`
- JSON-encoded dict mapping bigram string repr to probability
- Example: `{"('search', 'read')": 0.4, "('read', 'write')": 0.6}`

### Drift Dimension

`DriftReport.tool_sequence_transitions_drift: float`
- Previously aliased to `decision_drift` (placeholder)
- Now computed via `compute_bigram_jsd()` on real bigram distributions

## Preset Weights

Use case preset weights for `tool_sequence_transitions`:
- GENERAL: 0.05
- CUSTOMER_SUPPORT: 0.06
- DATA_ANALYSIS: 0.04
- CONTENT_GENERATION: 0.08
- CODE_GENERATION: 0.08
- SEARCH_AND_RETRIEVAL: 0.02
- TASK_AUTOMATION: 0.06
- REASONING_AND_PLANNING: 0.05
- CONVERSATIONAL: 0.05
- RECOMMENDATION: 0.07
- SUMMARIZATION: 0.05
- TRANSLATION: 0.05
- MULTIMODAL: 0.08
- UNSTRUCTURED: 0.0

Higher weights for use cases where tool order is semantically important (code generation, multimodal).

## Backward Compatibility

Runs without `bigram_distribution` field (pre-Phase 5) gracefully degrade:
- Empty dict returned by `json.loads(None)` handling
- JSD returns 0.0 for empty distributions
- No false positives from missing data

## Detection Scenarios

### When Bigrams Catch What Full-Sequence Misses

**Scenario 1: Subtle reordering within same tool set**
- Baseline: `[A, B, C]` vs Current: `[A, C, B]`
- Full-sequence JSD: 100% different (no overlap)
- Bigram JSD: ~70% different (some transitions preserved)
- **Better**: Bigrams give more nuanced signal for reorderings

**Scenario 2: Workflow logic change**
- Baseline: 80% use `[search → read]`, 20% use `[search → write]`
- Current: 20% use `[search → read]`, 80% use `[search → write]`
- Full-sequence may not catch this if sequences vary
- Bigrams clearly show the transition probability shift

## Testing

Fixture: `tool_order_drift_pair(n=200, seed=10)`
- Baseline: `[tool_a, tool_b, tool_c]`
- Current: `[tool_a, tool_c, tool_b]`
- Expected: `tool_sequence_transitions_drift > 0.3`

Tests in `tests/test_signal_gains.py`:
- `test_compute_bigrams_basic()` - basic extraction
- `test_compute_bigram_distribution()` - frequency computation
- `test_compute_bigram_jsd()` - JSD on identical vs different distributions
- `test_tool_order_drift_detected_by_bigrams()` - integration test

## See Also

- [Fingerprint Schema Debt](fingerprint-schema-debt.md) - Historical context on `tool_sequence_transitions_drift` placeholder
- [CLAUDE.md](../CLAUDE.md) - 12-dimension drift schema contract
