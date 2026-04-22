# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

# driftbase-python (OSS SDK)

## Product positioning

Driftbase = institutional memory for AI agent behavior.

Core value: "Always know exactly when your agent changed and why."

**CRITICAL: Driftbase is a drift detection layer, NOT a tracing tool.**
We read traces from Langfuse. We don't capture them.

Primary user journey:
  Connect Langfuse → driftbase connect → when something feels wrong →
  driftbase diagnose → immediate answer with root cause attribution.

Secondary user journey:
  driftbase history → full behavioral arc over time.

Tertiary user journey:
  Pre-deploy check → driftbase diff v1 v2 → verdict + CI gate.

Free SDK positioning:
- Langfuse connector — zero config, instant import of existing traces
- diagnose — reach for it when something feels wrong (no prior setup needed, works on historical data)
- history — longitudinal arc of agent behavior over its recorded lifetime
- diff — explicit version comparison with statistical verdict
- Monitoring, real-time alerting = Pro tier only

Key insight: the longer a team uses Driftbase, the more valuable their
history becomes. This is the moat. Langfuse users get instant value from
existing traces on day 1 → zero cold start.

## Role
Senior Python backend engineer. Focus on correctness, signal quality, and
zero-friction developer experience. Local-first, open-source library.
No cloud dependencies in core logic. No hand-holding.

## Response rules
- Answer directly. No preamble or postamble.
- No unsolicited suggestions or refactors.
- Show only changed/relevant code. Never reprint unchanged functions.
- Use diffs or clearly marked snippets when editing existing files.
- No comments unless logic is genuinely non-obvious.
- If ambiguous, ask ONE question before proceeding.
- Prefer code over prose.

---

## Repo hygiene

These rules apply to every task, every session. No exceptions.

### File creation
- Do NOT create markdown files to document changes, summarize work, or explain implementations.
- Allowed markdown files: README.md, CHANGELOG.md, CONTRIBUTING.md, CLAUDE.md, and files inside docs/.
- Do NOT create one-off scripts, debug scripts, or helper files outside of scripts/ or tests/.
- Do NOT create .py files prefixed with test_, debug_, check_, verify_, tmp_, or scratch_ unless they are permanent, committed test files.
- All explanations of what was done go in commit messages, not in files.
- If a new file doesn't have a permanent home in the repo structure, don't create it.

### Test files
- Temporary test files, experiments, and one-off debug scripts must be deleted after the task is complete.
- Test files live in tests/ only. No test files in root, src/, examples/, or scripts/.
- After any larger task or experiment: audit and delete any test_*.py, debug_*.py, check_*.py, verify_*.py files that are not part of the permanent test suite.
- Every file in tests/ must be intentional, named clearly, and have a clear scope.

### Examples
- Example files in examples/ must be self-contained, documented, and useful to an external developer.
- No throwaway experiment folders in examples/. If it's an experiment, use a branch.
- Each example must have its own README.md explaining what it does and how to run it.

### Repo structure
Always maintain this structure. Do not create top-level folders without explicit approval:

src/          # All SDK source code
tests/        # All permanent tests
examples/     # Self-contained, documented examples
scripts/      # Utility scripts (release, benchmarks, etc.)
docs/         # Documentation only
.claude/      # Claude Code context, memory, decisions, skills

### Code quality
- No commented-out code blocks left in committed files.
- No print() debug statements in src/. Use the logger.
- No hardcoded paths, tokens, or credentials anywhere.
- Public functions and classes must have docstrings.
- Follow existing naming conventions. Do not introduce new patterns without discussion.

### After every major task
Run this cleanup checklist before committing:
1. Delete any temporary or one-off .py files created during the task.
2. Delete any process-note .md files.
3. Ensure no debug output, print statements, or hardcoded credentials are left in code.
4. Ensure imports are clean — no unused imports left behind.
5. Run linter and test suite. Do not commit if either fails.
6. Commit message must clearly describe what changed and why.

### General principle
After every session, the repo should look like a senior engineer reviewed it
and approved it for open source release.

---

## Stack
- Language: Python 3.10+ (tested on 3.10–3.12)
- Storage: SQLite only (via SQLModel). No PostgreSQL, no cloud storage in this repo.
- Config: pydantic-settings (DRIFTBASE_* env vars) + layered config
  (env → .driftbase/config → pyproject.toml → defaults)
- Math: numpy, scipy, scikit-learn — core dependencies, always available
- CLI: Click + Rich
- Packaging: setuptools_scm (version from git tags), pyproject.toml
- Extras: [mcp] MCP server · [dev] pre-commit/pytest/ruff
- Entry point: driftbase.cli.main:cli registered as driftbase command

## Skills
Read the relevant skill BEFORE writing any code:
- Editing diff.py, baseline_calibrator.py, use_case_inference.py,
  anomaly_detector.py, weight_learner.py → .claude/skills/scoring.md
- Adding or modifying SQLite tables, backend methods → .claude/skills/storage.md
- Adding or modifying CLI commands, registering command groups → .claude/skills/cli.md
- Writing or updating tests → .claude/skills/testing.md
- Cutting a release, tagging, building, uploading to PyPI → .claude/skills/release.md

## Architecture mental model
Import → Store → Fingerprint → Diff → Report / Gate / Alert

Data flow:
1. Import: driftbase connect → Langfuse connector → map traces → SQLite
2. Analysis: CLI diagnose → epoch_detector → detect shifts → attribute cause
3. Analysis: CLI diff → load runs → fingerprint → calibrate → compute drift → verdict

Key modules:
- connectors/langfuse.py — Langfuse trace import, trace-to-run mapping
- connectors/mapper.py — Generic trace mapping logic (heuristics for decision outcomes, tool extraction, semantic clustering)
- local/local_store.py — SQLite schema, batched writes
- local/epoch_detector.py — automatic behavioral epoch detection using sliding window JSD, TTL-cached in SQLite
- local/fingerprinter.py — aggregates runs into BehavioralFingerprint per version
- local/diff.py — compute_drift(), JSD-based scoring, weighted composite
- local/use_case_inference.py — keyword + behavioral inference, 14 use cases, blended confidence weighting, conflict detection, preset weight tables
- local/baseline_calibrator.py — reliability multipliers, t-distribution thresholds, correlation adjustment, power analysis, calibration cache
- local/weight_learner.py — point-biserial correlation on deploy outcomes → learned weights
- local/anomaly_detector.py — isolation forest multivariate anomaly detection
- local/budget.py — BudgetConfig, BudgetBreach, rolling window breach detection
- local/rootcause.py — RootCauseReport, RollbackSuggestion, change event correlation
- local/hypothesis_engine.py — YAML rules → observations + recommendations
- verdict.py — DriftReport → SHIP / MONITOR / REVIEW / BLOCK + exit codes
- backends/ — abstract StorageBackend + SQLite implementation, factory pattern
- cli/ — Click commands. Primary: connect, diagnose, history. Secondary: diff, init, inspect, doctor, budgets, changes, export, prune, testset, mcp

## Never do
- Don't use async DB calls — all storage in this repo is synchronous SQLite
- Don't change fingerprint schema without a migration note
- Don't add dependencies outside pyproject.toml extras
- Don't hardcode drift weights or thresholds — all scoring parameters flow through baseline_calibrator.py
- Don't add cloud API calls, external HTTP requests, or network dependencies to any module outside sdk/push.py
- Don't touch web/ under any circumstances
- Don't raise from budget, calibration, inference, anomaly detection, or epoch_detector at runtime — degrade silently and log
- Don't suggest rollback unless verdict is BLOCK or REVIEW and a stable prior version exists with 30+ runs
- Don't use metadata as a field name in SQLModel — reserved by SQLAlchemy, causes InvalidRequestError at import time
- Don't escape Rich markup by wrapping strings manually — use from rich.markup import escape on any dynamic value
- Don't build dist/ with uncommitted changes — setuptools_scm will produce a .dev0 version string that cannot be published
- Don't put two tags on the same commit — setuptools_scm picks the lower one, producing the wrong version
- Don't tag before committing linting fixes — pre-commit will block the commit but the tag already exists, causing version mismatch on rebuild
- Never write nested `with` statements in tests or source code.
  Always use a single `with` statement with multiple contexts.
  Ruff rule SIM117 flags this and it blocks commits.

  WRONG:
      with patch.dict(os.environ, {"KEY": "val"}):
          with patch("some.module.Class") as mock:
              result = do_something()

  CORRECT:
      with patch.dict(os.environ, {"KEY": "val"}), \
           patch("some.module.Class") as mock:
          result = do_something()

  This applies to all nested with combinations:
  - patch + patch
  - patch.dict + patch
  - patch.object + patch.object
  - Any other combination
- Never run bare `twine upload dist/*` — always use
  `twine upload dist/* --skip-existing`
  PyPI returns a 400 "File already exists" error even on successful
  uploads. --skip-existing treats this as success instead of failure.
  Always verify with `pip index versions driftbase` after uploading.

## Version resolution

Versions are extracted from Langfuse traces using these sources (in order of precedence):
1. `release` field in Langfuse trace (if present)
2. `version:X.Y.Z` tag in Langfuse trace
3. `DRIFTBASE_VERSION` environment variable (fallback if trace has no version info)
4. Time-based epoch: epoch-YYYY-MM-DD (Monday of current week, fallback for unversioned traces)

Never hardcode versions in analysis code. Always use what's in the trace.

## Scoring system
Weights and thresholds are never hardcoded. Full pipeline:

1. use_case_inference.py — infers use case from tool names (keyword scoring + behavioral signals), blends two classifiers with conflict detection, returns preset weights
2. baseline_calibrator.py — applies reliability multipliers (CV-based), correlation adjustment (Spearman), t-distribution thresholds from baseline variance, volume scaling, sensitivity multiplier, power analysis for minimum runs needed
3. weight_learner.py — if 10+ labeled deploy outcomes exist, blends learned weights from point-biserial correlation into calibrated weights
4. diff.py — consumes calibrated weights + thresholds, computes 12-dimension composite score, calls anomaly detector as supplementary signal
5. verdict.py — maps composite + anomaly signal → SHIP/MONITOR/REVIEW/BLOCK, only fires at TIER3 (n ≥ power-analysis-derived minimum, default 50)

Do not bypass this pipeline. Do not reintroduce hardcoded values anywhere.

## Confidence tiers
- TIER1 (n < 15 either version): no analysis shown
- TIER2 (15 ≤ n < min_runs_needed): directional signal only, no verdict
- TIER3 (n ≥ min_runs_needed both versions): full analysis + verdict
- min_runs_needed computed via power analysis from baseline variance × use case effect size. Default 50 when insufficient baseline data.

## Database tables
### Run storage (v0.11+ two-table design)
- runs_raw — immutable trace data from ingestion (replaces agent_runs_local)
- runs_features — derived features computed from trace data (lazy derivation on read)
  - Includes run_quality score (0.0-1.0) - see docs/run-quality.md
- agent_runs_local — legacy table (kept as read-only safety net after migration)

### Analysis and state
- calibration_cache — calibrated weights + thresholds per agent+version
- budget_configs — persisted budget definitions per agent+version
- budget_breaches — breach events with rolling average values
- change_events — recorded change events per agent+version
- deploy_outcomes — good/bad labels per version for weight learning
- learned_weights_cache — cached learned weights per agent
- significance_thresholds — power analysis results per agent+version
- detected_epochs — cached epoch detection results, 1-hour TTL
- deploy_events — schema-only, deferred UX

Location: ~/.driftbase/runs.db (configurable via DRIFTBASE_DB_PATH)

See: docs/schema-v2.md for two-table design details

## Fingerprint schema
Stable contract — do not alter field names without explicit instruction.

12 drift dimensions:
- decision_drift (JSD on outcome distribution: resolved/escalated/error)
- tool_sequence (Levenshtein on tool call patterns)
- tool_distribution (JSD on tool frequency)
- latency (t-test on p95 latency_ms)
- error_rate (proportion test)
- retry_rate (proportion test)
- loop_depth (t-test on loop_count)
- verbosity_ratio (t-test on output_length / prompt_tokens)
- output_length (t-test on completion_tokens)
- time_to_first_tool (t-test on time_to_first_tool_ms)
- semantic_drift (JSD on heuristic semantic cluster distribution: resolved/escalated/error/unknown)
- tool_sequence_transitions (JSD on bigram transition probabilities)

## Development commands

# Run all tests
PYTHONPATH=src pytest tests/

# Run specific test file
PYTHONPATH=src pytest tests/test_diff.py

# Linting
ruff check .
ruff format .

# Pre-commit hooks
pre-commit run --all-files

# Build package (requires clean git tree)
python -m build

# Install in editable mode
pip install -e .
pip install -e '.[dev]'  # For development with pre-commit, pytest, ruff

## Tests
- pytest + pytest-asyncio
- Fixtures in conftest.py
- No async tests needed — SDK storage is synchronous
- Always use PYTHONPATH=src when running tests locally
- Test files mirror src/ structure

## Core product constraint
False positive rate is everything. A drift score that moves on cosmetic
changes is worthless and destroys developer trust. When touching
fingerprinter.py, diff.py, baseline_calibrator.py, use_case_inference.py,
or epoch_detector.py, always reason about false positive rate first.
When in doubt, be conservative.

## Tone
Direct. Technical. Peer-level.
