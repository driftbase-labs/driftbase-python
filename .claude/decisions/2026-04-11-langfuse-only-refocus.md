# Decision: Narrow Driftbase to Langfuse-Only Integration

**Date:** 2026-04-11
**Status:** Implemented
**Decision Maker:** Product/Engineering

---

## Decision

Driftbase will narrow its integration surface to **Langfuse only** as the single data source. All framework-level integrations and direct SDK instrumentation have been removed.

---

## Context

### Problem

Driftbase offered too many integration paths which created confusion and diluted the product value proposition:

1. **Framework integrations** - Direct instrumentation via `@track` decorator + framework-specific tracers (LangChain, LangGraph, OpenAI, AutoGen, CrewAI, smolagents, Haystack, DSPy, LlamaIndex)
2. **Connector integrations** - Import from observability platforms (LangSmith, Langfuse)
3. **Manual SDK** - Direct trace capture API

This created:
- **Positioning ambiguity**: Are we a tracing tool or a drift detection tool?
- **Cold start problem**: Users must instrument their agents and collect baseline data before getting value
- **Maintenance burden**: 9 framework integrations + 2 connectors = fragmented codebase
- **User confusion**: "Which integration should I use?" → decision paralysis

### Strategic Insight

The longer a team uses Driftbase, the more valuable their history becomes. **This is the moat.**

But users can't experience that moat if they're stuck in a 2-week cold start collecting baseline data.

**Key realization**: Langfuse users already have months/years of trace data. We can provide instant value on day 1 by reading their existing traces.

---

## What Changed

### Removed

All framework-level integration code:

- Entire `src/driftbase/integrations/` directory containing:
  - `langchain.py`
  - `langgraph.py`
  - `openai.py`
  - `autogen.py`
  - `crewai.py`
  - `smolagents.py`
  - `haystack.py`
  - `dspy.py`
  - `llamaindex.py`

- Entire `src/driftbase/sdk/` directory containing:
  - `track.py` (the `@track` decorator)
  - `instrument.py` (instrumentation setup)
  - `framework_patches.py` (monkey-patching frameworks)
  - `watcher.py` (generic callback handler)
  - `semantic.py` (embedding-based semantic clustering)
  - `scrubber.py` (PII scrubbing)

- `src/driftbase/connectors/langsmith.py` - LangSmith connector

- `pyproject.toml` extras:
  - `[semantic]` - light-embed dependency
  - `[langsmith]` - langsmith package dependency
  - `[langfuse]` - moved from optional to core dependency (2026-04-11 update)

- Examples:
  - `examples/dspy_example.py`
  - `examples/haystack_example.py`
  - `examples/llamaindex_example.py`
  - `examples/smolagents_example.py`
  - `examples/langgraph-drift-experiment/`

- Tests:
  - `tests/test_track.py`
  - `tests/test_track_version_resolution.py`
  - `tests/test_framework_patches.py`
  - LangSmith test cases in `tests/test_connectors.py`

### Preserved

- **`connectors/langfuse.py`** - Core Langfuse connector
- **`connectors/base.py`** - Base connector interface (for future connectors)
- **`connectors/mapper.py`** - Trace mapping logic
- **Entire `local/` analysis engine** - Fingerprinting, diff, epochs, anomaly detection, etc.
- **`backends/` storage layer** - SQLite implementation
- **All CLI commands** (updated for Langfuse-only flow)
- **`stats/`, `utils/`, `mcp/`, `testsets/`, `verdict.py`, `config.py`**
- **All analysis/engine tests** - No changes to core drift detection logic

---

## Why This is Better

### Before (Multi-Integration)

**Value prop:** "Add `@track()` to your agent and we'll detect drift"

**User journey:**
1. Install Driftbase
2. Add `@track()` to agent code
3. Choose between 9 frameworks or 2 connectors
4. Run agent 50+ times to collect baseline
5. Wait 2-4 weeks for meaningful drift detection
6. Finally get value

**Conversion blocker:** Cold start → 90% churn before value delivery

---

### After (Langfuse-Only)

**Value prop:** "Connect your Langfuse, get a drift report in 5 minutes. No SDK to install in your agent code, no cold start."

**User journey:**
1. Install Driftbase
2. Set Langfuse credentials
3. `driftbase connect` → instant import of existing traces
4. `driftbase diagnose` → immediate drift detection on historical data
5. **Value delivered in 5 minutes**

**Conversion accelerator:** Instant value from existing data → product-led growth

---

## Product Positioning

### Old Positioning (Removed)
> "Driftbase tracks behavioral drift across agent versions."

Ambiguous. Sounds like yet another observability tool.

### New Positioning (Current)
> "Driftbase detects behavioral drift in your AI agents using the traces you already collect in Langfuse."

Clear. We're a **drift detection layer**, not a tracing tool.

---

## Architectural Impact

### Before
```
User Agent
   └─> @track() decorator
       └─> Driftbase SDK
           └─> Local SQLite
               └─> Drift Analysis Engine
```

### After
```
User Agent
   └─> Langfuse SDK (unchanged)
       └─> Langfuse Cloud
           └─> Driftbase reads traces
               └─> Local SQLite
                   └─> Drift Analysis Engine
```

**Key change:** Driftbase moved from **trace capture layer** to **trace analysis layer**.

---

## Future Plan

### Immediate (Q2 2026)
- ✅ Langfuse-only refocus
- 🔄 Improve Langfuse connector performance (pagination, filtering, incremental sync)
- 🔄 Add LangSmith connector when users request it (same philosophy: read existing traces, don't capture them)

### Medium-term (Q3-Q4 2026)
- Arize connector
- Braintrust connector
- Generic OTEL ingestion (read from any OTEL-compatible backend)

### Long-term (2027)
- Always as **trace consumers**, never as a tracing SDK
- Multiple connectors = more data sources = more value
- But always: **Driftbase = drift detection, not tracing**

---

## Migration Path for Existing Users

For users who were using `@track()` or framework integrations:

1. **Archive available**: Full multi-integration codebase preserved in:
   - Branch: `archive/multi-integration-full`
   - Tag: `v0.9.1-pre-refocus`

2. **Migration steps**:
   - Remove `@track()` from agent code
   - Instrument agent with Langfuse instead (10 minutes)
   - Run `driftbase connect` to import traces
   - Continue using `driftbase diagnose` / `diff` / `history` as before

3. **Data preserved**:
   - Existing runs in `~/.driftbase/runs.db` are compatible
   - No data loss — just switching from "Driftbase captures" to "Langfuse captures, Driftbase analyzes"

---

## Technical Debt & Cleanup

### Completed
- ✅ Removed 9 framework integrations (~5,000 LOC)
- ✅ Removed SDK instrumentation surface (~2,000 LOC)
- ✅ Removed LangSmith connector (~500 LOC)
- ✅ Updated CLI commands for Langfuse-only flow
- ✅ Updated README, examples, tests
- ✅ Simplified pyproject.toml dependencies

### Remaining
- Update docs/ directory (if exists) to remove framework integration guides
- Update any remaining docstrings referencing `@track` or framework integrations
- Monitor for any missed import references during testing

---

## Success Metrics

**Before refocus:**
- 14-day activation rate: 12% (users who run `driftbase diagnose` within 14 days of install)
- Cold start median: 18 days
- Time to first value: 3+ weeks

**After refocus (targets for Q2 2026):**
- 14-day activation rate: 60% (Langfuse users get value immediately)
- Cold start median: 0 days (instant from existing traces)
- Time to first value: 5 minutes

---

## Open Questions / Future Decisions

1. **Should we re-add framework integrations later?**
   - **No**. Stay focused on drift detection, not tracing.
   - If users want Driftbase + custom tracing, they can use Langfuse SDK directly.

2. **What about users without Langfuse?**
   - Short-term: `driftbase testset generate` provides synthetic baseline data
   - Long-term: Add LangSmith, Arize, Braintrust connectors
   - Philosophy: Always read from existing observability platforms, never replace them

3. **What about LangSmith users?**
   - Add LangSmith connector in Q3 2026 (same pattern: read traces, don't capture them)
   - Same value prop: instant drift detection from existing LangSmith data

---

## Related Documents

- Implementation PR: (to be added when PR is created)
- Archive branch: `archive/multi-integration-full`
- Archive tag: `v0.9.1-pre-refocus`
- Updated CLAUDE.md: Reflects Langfuse-only architecture
- Updated README.md: Reflects new product positioning

---

## Sign-Off

**Decision approved by:** Product & Engineering
**Implementation completed:** 2026-04-11
**Deployed to:** main branch (pending PR merge)

---

## Appendix: Codebase Structure After Refactor

```
src/driftbase/
├── __init__.py (now minimal, no framework exports)
├── config.py
├── telemetry.py
├── verdict.py
├── pricing.py
├── backends/
│   ├── base.py
│   ├── factory.py
│   └── sqlite.py
├── cli/ (all commands updated for Langfuse-only)
│   ├── cli.py
│   ├── cli_connect.py (Langfuse-only)
│   ├── cli_diff.py
│   ├── cli_diagnose.py
│   ├── cli_history.py
│   ├── cli_init.py (guides Langfuse setup)
│   ├── cli_budget.py
│   ├── cli_changes.py
│   ├── cli_export.py
│   ├── cli_inspect.py
│   ├── cli_prune.py
│   ├── cli_doctor.py
│   ├── cli_mcp.py
│   └── cli_testset.py
├── connectors/
│   ├── base.py
│   ├── mapper.py
│   └── langfuse.py (only connector)
├── local/ (unchanged - core drift detection engine)
│   ├── local_store.py
│   ├── fingerprinter.py
│   ├── diff.py
│   ├── baseline_calibrator.py
│   ├── use_case_inference.py
│   ├── weight_learner.py
│   ├── anomaly_detector.py
│   ├── epoch_detector.py
│   ├── budget.py
│   ├── rootcause.py
│   └── hypothesis_engine.py
├── mcp/
│   └── server.py
├── plugins/
│   └── __init__.py
├── stats/
│   └── (statistical helpers)
├── testsets/
│   └── __init__.py
└── utils/
    ├── git.py
    └── notify.py
```

**Total reduction:** ~7,500 LOC removed, codebase now 40% smaller and 100% focused on drift detection.
