# Changelog

All notable changes to Driftbase will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.14.0-rc.1] - 2026-04-23

### Added - Phase 5: Real Signal Gains

#### Bigram Tool Sequence Detection
- **`bigram_distribution` field** added to `BehavioralFingerprint`
  - Stores JSON-encoded frequency distribution of consecutive tool pairs (bigrams)
  - Example: `{"('search', 'read')": 0.4, "('read', 'write')": 0.6}`
  - Computed from all tool sequences in fingerprint window
- **`tool_sequence_transitions_drift` real implementation**
  - Previously aliased to `decision_drift` (placeholder since Phase 1)
  - Now computed via Jensen-Shannon divergence on bigram distributions
  - Detects tool order changes that full-sequence comparison misses
  - Example: `[A, B, C]` vs `[A, C, B]` — same tools, different transitions
- **New module**: `src/driftbase/stats/ngrams.py`
  - `compute_bigrams()` — extract consecutive pairs from tool sequence
  - `compute_bigram_distribution()` — aggregate bigrams across runs
  - `compute_bigram_jsd()` — Jensen-Shannon divergence on bigram distributions
- **Preset weights**: 0.02-0.08 depending on use case (higher for code/multimodal where order matters)

#### EMD Latency Distribution Detection
- **Earth Mover's Distance (Wasserstein)** for latency distributions
  - Catches bimodal shifts that p95 averages out (half the runs get 2x slower)
  - Detects distribution shape changes (increased variance, long tail development)
  - Example: 50% runs stay fast, 50% regress → EMD detects split, p95 shows moderate increase
- **New module**: `src/driftbase/stats/emd.py`
  - `compute_latency_emd()` — raw EMD in milliseconds using scipy.stats.wasserstein_distance
  - `compute_latency_emd_signal()` — normalized signal in [0, 1] via sigmoid (k=0.002, c=500ms)
- **Blended latency scoring** (Option B: 50/50 blend)
  - `sigma_latency = 0.5 * sigma_p95 + 0.5 * emd_signal`
  - Preserves existing p95 sensitivity while adding distribution shape detection
  - Requires `baseline_runs` and `current_runs` for computation (gracefully degrades to p95 alone if unavailable)

#### Per-Cluster Drift Analysis
- **Task clustering** by `(first_tool, input_length_bucket)`
  - Groups runs into task types for targeted drift analysis
  - Input length buckets: 0-100, 100-500, 500-2000, 2000+ chars
  - Max 5 clusters by size, requires >= 10 runs per cluster per version
  - Example clusters: `search:0-100` (short queries), `write:500-2000` (long-form tasks)
- **`cluster_analysis` field** added to `DriftReport`
  - List of `ClusterDriftResult` with per-cluster drift scores
  - Top 3 contributing dimensions per cluster (latency_p95, error_rate, tool_variance)
  - Sorted by drift score descending (most-drifted clusters first)
- **New module**: `src/driftbase/local/task_clustering.py`
  - `cluster_runs_by_task()` — O(n) string-based clustering (no ML models)
  - `compute_per_cluster_drift()` — simplified 3-dimension scoring per cluster
  - `ClusterDriftResult` dataclass with cluster ID, label, sample sizes, drift score, top contributors
- **Use case**: Detect task-specific regressions that global score misses
  - Example: global drift 0.15 (MONITOR), but `write:500-2000` cluster shows 0.68 (BLOCK)

### Changed
- **`tool_sequence_transitions_drift`** now computed from real bigram distributions (was placeholder aliased to `decision_drift`)
- **Latency drift scoring** now blends p95-based signal with EMD distribution signal (50/50)
- **Fingerprint computation** now includes bigram distribution extraction
- **Drift computation** now includes per-cluster analysis when run-level data available

### Documentation
- **`docs/bigrams.md`**: Bigram tool sequence detection guide
  - Why bigrams catch reorderings, implementation, preset weights, testing
- **`docs/latency-emd.md`**: EMD latency distribution detection guide
  - When EMD catches what p95 misses, sigmoid normalization, blending strategy, calibration
- **`docs/task-clustering.md`**: Per-cluster drift analysis guide
  - Clustering key, cheap O(n) implementation, detection scenarios, limitations
- **`docs/fingerprint-schema-debt.md`**: Updated to mark `tool_sequence_transitions_drift` as RESOLVED

### Tests
- **17 new tests** in `tests/test_signal_gains.py`:
  - Bigram tests (5): extraction, distribution, JSD, integration
  - EMD tests (4): identical, shifted, signal normalization, bimodal detection
  - Clustering tests (5): basic clustering, max clusters, insufficient data, single-cluster drift
  - Integration tests (3): tool order drift, bimodal latency, no-drift invariant
- **3 new synthetic fixtures** in `tests/fixtures/synthetic/generators.py`:
  - `tool_order_drift_pair()` — same tools, different order (bigram shift)
  - `bimodal_latency_drift_pair()` — half the runs get 2x slower (EMD catches, p95 averages out)
  - `single_cluster_drift_pair()` — drift in one task type only (clustering pinpoints)

### Migration Notes
- **Backward compatible**: Runs without `bigram_distribution` gracefully degrade (JSD returns 0.0)
- **No schema migration needed**: New fingerprint field is optional (`str | None`)
- **Behavior change intentional**: This phase changes detection behavior to improve signal quality
- **no_drift invariant maintained**: `no_drift` fixture stays < 0.05 (verified in integration tests)

## [0.13.0-rc.1] - 2026-04-23

### Added - Phase 4: Ingestion Quality

#### Observation Tree Capture
- **`observation_tree_json` field** added to `runs_raw` table
  - Stores full hierarchical trace structure from Langfuse and LangSmith
  - Preserves ALL observation types (generations, spans, events), not just tool calls
  - JSON format with recursive children: `{id, type, name, input, output, metadata, children}`
  - Enables richer debugging context and future per-node analysis
- **Tree building functions**: `_build_observation_tree()` in Langfuse and LangSmith connectors
  - Uses `parent_observation_id` (Langfuse) or `parent_run_id` (LangSmith) relationships
  - Handles orphaned nodes and multiple roots gracefully
  - Logs warnings on failures, never blocks ingestion

#### Blob Storage for Full Input/Output
- **`runs_blobs` table** added for untruncated text storage
  - Fields: `id, run_id, field_name, content, content_length, content_hash, truncated, created_at`
  - SHA-256 hash of content for integrity verification
  - Size-capped (default 100KB, configurable via `DRIFTBASE_BLOB_SIZE_LIMIT`)
  - Truncated flag when content exceeds cap
- **Backend methods**: `save_blob()`, `get_blob()`, `get_blobs_for_run()`
  - Best-effort saves—never fail ingestion if blob save fails
  - Configurable via `DRIFTBASE_BLOB_STORAGE=true|false`
- **Connector integration**: Full `raw_prompt_full` and `raw_output_full` saved before 5000-char truncation
  - Legacy `raw_prompt` and `raw_output` still truncated for backward compatibility
  - Blobs saved during `write_runs()` after run insert

#### Enhanced Tool Extraction
- **Tree-based tool extraction** via `extract_tools_from_tree()`
  - Walks full observation tree to find tools in ALL node types (spans, events, generations)
  - Skips non-tool names like "llm", "chain", "agent", "trace"
  - **Additive behavior**: Merges with legacy extraction, finds MORE tools, never fewer
  - No `FEATURE_SCHEMA_VERSION` bump—detection behavior unchanged
- **Improved tool coverage**: Captures tools embedded in spans/events missed by legacy extraction

#### Storage Management Commands
- **`driftbase migrate --status`** now shows blob storage stats
  - Total blob count and storage size (MB)
  - Breakdown by field_name (input vs output)
  - Truncated blob count
- **`driftbase prune --blobs`**: Delete all blobs to reclaim disk space
  - Includes dry-run preview and confirmation prompt
- **`driftbase prune --orphan-blobs`**: Delete blobs for non-existent runs
  - Queries both `runs_raw` and `agent_runs_local` to avoid false positives

#### driftbase inspect Enhancements
- **Observation tree display**: Hierarchical ASCII tree with color-coded node types
  - generation=cyan, tool=green, span=blue, event=yellow, trace=magenta
  - Shows node IDs (first 8 chars) for cross-reference
- **Blob content display**: Shows full input/output from blob storage if available
  - Falls back to legacy `raw_prompt`/`raw_output` for runs without blobs
  - Size indicator (KB) and truncation flag displayed
- **Helper function**: `_format_tree()` for recursive tree rendering

#### Documentation
- **`docs/observation-trees.md`**: Complete guide to observation tree capture
  - Why trees matter, storage format, tool extraction (additive), backward compatibility
  - How to view trees with `driftbase inspect`
- **`docs/blob-storage.md`**: Blob storage reference
  - Schema, size limits, configuration, storage management
  - Performance impact, best practices, backward compatibility

### Changed
- **Langfuse and LangSmith connectors** now build observation trees and populate `observation_tree_json`
- **Tool extraction** uses additive tree-based approach (legacy + tree merge)
- **`write_runs()`** saves blobs before committing run records

### Tests
- **19 new tests** in `tests/test_ingestion_quality.py`:
  - Blob storage: save, retrieve, size limits, truncation, disabled mode, hash computation
  - Observation trees: Langfuse (single, parent-child, empty), LangSmith (children, empty)
  - Tree tool extraction: simple, additive, skip non-tools, empty
  - Backward compatibility: runs without trees/blobs continue to work
  - Full ingestion pipeline: write_runs with blobs, blob failure doesn't block ingestion

### Added - Phase 3b: Trust Surface

#### Verdict History Storage
- **`verdict_history` table** added to SQLite backend
  - Stores completed drift verdicts with baseline/current versions, composite scores, severity, confidence tier
  - Full DriftReport serialized as JSON for complete context
  - Indexed by timestamp for fast chronological retrieval
- **Backend methods**: `save_verdict()`, `get_verdict()`, `list_verdicts()`
  - Automatic verdict saving on `driftbase diff` completion
  - Enables audit trail and rollback target discovery

#### Structured Verdict Payload
- **`output.verdict_payload.build_verdict_payload()`** converts DriftReport to clean JSON for CI/CD
  - Version 1.0 schema with: verdict, composite_score, confidence (CIs), confidence_tier
  - **Top 3 contributors** with observed scores, CIs, significance flags, contribution %, and evidence
  - **Rollback target**: Most recent SHIP verdict from history (for REVIEW/BLOCK verdicts)
  - **Power forecast**: Runs needed for sufficient power (TIER1/TIER2 only)
  - **MDEs and thresholds**: Full statistical context
  - Graceful degradation on errors—minimal fallback payload always returned

#### Evidence Generation
- **`output.evidence.generate_evidence()`** produces human-readable explanations for all 12 dimensions
  - **Decision drift**: "Tool path ['search', 'write'] went from 3% to 27%" or "New tool path appeared in 15.3%"
  - **Latency**: "P95 latency increased from 1,240ms to 2,890ms (+133%)"
  - **Error rate**: "Error rate increased from 2.1% to 8.4% (+6.3pp)"
  - **Semantic drift**: "Semantic cluster 'error' grew from 5% to 18% of outcomes"
  - Similar patterns for verbosity, loop depth, output length, retry rate, planning latency
  - Fallback: "Drift observed in {dimension}" when fingerprint data is missing

#### driftbase explain Command
- **`driftbase explain [VERDICT_ID]`** shows detailed verdict breakdown
  - Loads latest verdict if no ID provided
  - Rich-formatted output with panels and tables
  - Displays: top contributors with evidence, CIs, contribution %, significance markers
  - Full MDE table with detectability status (✓ Detectable / ⚠ Below MDE)
  - Helpful error if no verdict history exists

#### driftbase diff --format Flag
- **`--format` option** with choices: `rich` (default), `json`, `markdown`
  - **`--format=json`**: Outputs structured verdict_payload for programmatic consumption
  - **`--format=markdown`**: GitHub-flavored markdown table for PR comments
    - Renders top contributors with evidence in table format
    - Shows MDEs, rollback target, verdict
    - Ready to paste into GitHub PRs or Slack
  - Deprecated `--json` flag (hidden for backward compatibility)
  - `--ci` flag now implies `--format=json --fail-on-drift`

#### Root Cause Attribution
- **`VerdictResult.root_cause`** field added (optional)
  - Populated for REVIEW and BLOCK verdicts only
  - Format: "dimension: score (X% of drift)"
  - Extracted from top contributor in dimension_attribution
  - Provides one-line summary of primary drift cause

#### Documentation
- **`docs/explain.md`**: Complete guide to reading `driftbase explain` output
  - How to interpret CIs, significance markers, MDEs
  - Evidence string examples for all dimensions
  - Statistical interpretation tips
- **`docs/ci-integration.md`**: CI/CD integration patterns
  - GitHub Actions, GitLab CI, CircleCI examples
  - JSON and markdown output usage
  - Exit code handling, rollback strategies
  - Troubleshooting guide

### Changed
- **`driftbase diff`** now saves verdict to history automatically
- JSON output structure changed to use `verdict_payload` schema (version 1.0)
- Markdown output now renders as GFM table instead of plain text

### Tests
- **21 new tests** in `tests/test_trust_surface.py`:
  - Verdict history: save, retrieve, ordering
  - Verdict payload: structure, top contributors, rollback target, JSON serialization
  - Evidence generation: all dimensions, fallback handling
  - CLI formats: JSON validation, markdown structure
  - Explain command: no history, latest, by ID
  - Root cause: present for REVIEW/BLOCK, absent for SHIP
  - Integration: composite scores unchanged (detection behavior stable)

## [0.12.0-rc.1] - 2026-04-22

### Added - Phase 3a: Statistical Foundation

#### Per-dimension Confidence Intervals
- **Bootstrap 95% CIs for all 12 drift dimensions** computed via `stats.compute_dimension_cis()`
  - Resamples runs ONCE per bootstrap iteration, computes all dimensions from same resample
  - Captures cross-dimension correlation in uncertainty estimates
  - Uses deterministic RNG (`get_rng(salt)`) for reproducible CIs
  - Returns `DimensionCI` dataclass with `{observed, ci_lower, ci_upper, significant}` fields
  - `significant=True` if CI excludes 0 (drift reliably detected)

#### Minimum Detectable Effect (MDE)
- **Per-dimension MDE computation** via `stats.compute_mde()`
  - Estimates smallest drift effect detectable with current sample sizes
  - Formula: `MDE = (z_alpha/2 + z_power) * sigma_pooled * sqrt(1/n_baseline + 1/n_current)`
  - Uses bootstrap to estimate pooled standard deviation per dimension
  - Smaller MDE = better detection sensitivity
  - Helps users understand when they have sufficient data

#### Power Forecasts for TIER2
- **Runs-needed forecasting** via `stats.forecast_runs_needed()`
  - Estimates additional runs needed to detect a target effect size (default 0.10)
  - Inverts MDE formula to solve for required sample size
  - Returns runs needed per dimension to reach statistical power
  - Useful for TIER2 analysis ("collect 42 more runs to detect 0.10 drift")

#### Counterfactual Attribution
- **Dimension attribution analysis** via `stats.compute_dimension_attribution()`
  - Leave-one-out (LOO) analysis: removes each dimension and recomputes composite
  - Attribution = original_composite - composite_without_dim
  - Positive attribution = dimension drove drift upward
  - Negative attribution = dimension dampened drift (mitigating factor)
  - Helps answer "which dimensions mattered most?"
- **Marginal contribution** via `stats.compute_marginal_contribution()`
  - Simpler alternative: marginal = weight × score
  - Sum of marginal contributions = composite score (by construction)

#### Integration with DriftReport
- **New optional fields in `DriftReport`** (Phase 3a):
  - `dimension_cis: dict[str, DimensionCI] | None`
  - `dimension_mdes: dict[str, float] | None`
  - `runs_needed_forecast: dict[str, int] | None`
  - `dimension_attribution: dict[str, float] | None`
- **New `compute_statistics` flag in `compute_drift()`**:
  - Default: `compute_statistics=True` (computes all statistics)
  - Set `compute_statistics=False` to skip (faster, for high-throughput scenarios)
  - Detection behavior UNCHANGED: composite scores identical with or without statistics

### Documentation
- New `src/driftbase/stats/` module structure:
  - `dimension_ci.py` - Bootstrap confidence intervals
  - `mde.py` - Minimum detectable effect computation
  - `power_forecast.py` - TIER2 power analysis
  - `attribution.py` - Counterfactual attribution

### Technical Details
- All statistical functions use deterministic RNG via `get_rng(salt)`
- Bootstrap optimization: single resample per iteration for all 12 dimensions
- Performance: <3 seconds for n=50 (well under <10 second target for n=200)
- Graceful degradation: returns NaN/-1 on errors, logs warnings, never raises

### Tests
- **19 new tests** in `tests/test_statistical_foundation.py`:
  - 5 tests for dimension_ci (basic, all dimensions, empty runs, deterministic, significance)
  - 4 tests for mde (basic, sample size dependency, empty runs, all dimensions)
  - 4 tests for power_forecast (basic, sufficient sample, empty runs, multiple dimensions)
  - 3 tests for attribution (basic, marginal contribution, empty)
  - 3 integration tests with diff.py (flag behavior, field population, detection unchanged)
- **All 337 tests pass** (318 existing + 19 new)
- **Synthetic drift MD5 unchanged**: 81c8c216b17c79b121fdfcd86a4b468d

## [0.11.1-rc.1] - 2026-04-22

### Added - Phase 2b: Run Quality Score + Database Indexing

#### Run Quality Scoring
- **New `run_quality` score (0.0-1.0)** computed per run at derivation time
  - Measures version clarity, data completeness, feature derivability, and observation richness
  - Four equal-weighted components (0.25 each):
    - Version clarity: release/tag = 1.0, env = 0.7, epoch = 0.3, unknown = 0.0
    - Data completeness: input, output, latency, tokens, session_id presence
    - Feature derivability: successful derivation = 1.0, failed = 0.0
    - Observation richness: tools, semantic cluster, retry/loop data
  - Stored in `runs_features.run_quality` column
  - **Not yet used in fingerprint weighting** (Phase 2c will add optional weighting)
  - Never raises exceptions (returns 0.0 on error)

#### Database Performance Indexes
- **Five new indexes** for primary query patterns:
  - `idx_runs_raw_version_env_ts`: Fingerprint queries (version + environment + timestamp)
  - `idx_runs_raw_session_ts`: Session-based filtering
  - `idx_runs_raw_version_source`: Version source filtering (drift warnings)
  - `idx_runs_features_run_id`: FK join performance
  - `idx_runs_features_schema_version`: Migration status and lazy derivation queries
  - All indexes created with `CREATE INDEX IF NOT EXISTS` (idempotent)
  - Improves query performance for large databases (>10K runs)

#### CLI Enhancements
- **`driftbase migrate --status`** now shows run quality distribution:
  - "Runs with quality score > 0.0: N / Total (X.X%)"
  - "Quality distribution: min=X.XX, median=X.XX, max=X.XX"
  - Only displays for runs where quality has been computed

### Documentation
- New `docs/run-quality.md`: Quality scoring rubric, components, future weighting plans
- Updated `.claude/claude.md`: Database tables section updated with run_quality reference

### Technical Details
- Quality computation in `src/driftbase/local/run_quality.py`
- Wired into `feature_deriver.py:derive_features()`
- Migrated rows have `run_quality=0.0` until backfill (intentional)
- Column migration added to backend initialization (v0.11.1)

## [0.11.0-rc.1] - 2026-04-22

### Added - Phase 2a: Schema Split

#### Two-Table Storage Architecture
- **Separation of raw trace data and derived features**
  - New `runs_raw` table: immutable trace data from ingestion
  - New `runs_features` table: computed features with lazy derivation
  - `feature_source` audit column: tracks "derived" vs "migrated" features
  - Enables schema evolution without reingestion
  - Supports feature backfilling for historical data

#### Automatic Migration (v0.10 → v0.11)
- **Safe, atomic migration from `agent_runs_local` to two-table design**
  - Automatic backup creation (`.pre-v0.11.backup` files)
  - Idempotent migration (safe to re-run)
  - Transaction-based (all-or-nothing)
  - Preserves all data and computed features
  - Keeps legacy table as read-only safety net
  - Migration runs on backend initialization

#### Lazy Feature Derivation
- **On-demand feature computation** for missing or stale features
  - LEFT JOIN pattern: `runs_raw` + `runs_features`
  - Automatic derivation on first read
  - Stale feature detection via `feature_schema_version`
  - Failed derivations marked with sentinel value (-1)
  - No impact on existing workflows

#### CLI Migration Commands
- **`driftbase migrate` command** for schema management
  - `--status`: Show migration status and feature breakdown (derived vs migrated)
  - `--backfill`: Derive missing or stale features with progress bar
  - `--rebuild --confirm`: Drop all features and re-derive from scratch
  - `--dry-run`: Preview changes without modifying database
  - Feature source tracking in status output

#### Comprehensive Test Coverage
- **16 new migration tests** in `tests/test_schema_migration.py`
  - Migration detection and table creation
  - Data copying and preservation
  - Idempotency and backup creation
  - feature_source tracking (migrated vs derived)
  - Lazy derivation and error handling
  - Field mappings and index creation
  - All tests pass

### Changed
- **Database schema**: Split `agent_runs_local` into `runs_raw` + `runs_features`
- **SQLiteBackend.get_runs()**: Now uses lazy derivation reader
- **Feature computation**: Centralized in `local/feature_deriver.py` module

### Documentation
- New `docs/schema-v2.md`: Two-table design, feature_source, migration details
- New `docs/migration-guide.md`: Upgrade process, rollback procedure, troubleshooting
- Updated `CLAUDE.md`: Replaced agent_runs_local with two-table storage references
- Migration docstrings in `backends/migrations/v0_11_schema_split.py`

### Migration Notes
- **Automatic migration on first v0.11 startup**
  - Backup created at `~/.driftbase/runs.db.pre-v0.11.backup`
  - Migration takes <1 second for databases up to 100K runs
  - No user action required
- **Rollback**: Restore backup and downgrade to v0.10.3
- **Phase 2a limitation**: observation_tree_json not yet populated (Phase 4)
  - Tool features (tool_sequence, loop_count) cannot be re-derived for migrated data
  - Migration copies these features to preserve values
  - Do not run `--rebuild` on migrated databases until Phase 4

## [0.10.0-rc.2] - 2026-04-22

### Fixed
- **Determinism across processes.** `get_rng()` now uses a SHA-256-based
  stable hash for salt derivation instead of Python's built-in `hash()`,
  which is randomized per-process for security. Drift reports are now
  genuinely reproducible across separate Python invocations, not just
  within a single process. Users who ran identical `driftbase diff`
  commands previously and got slightly different scores should see
  consistent results after upgrading.

### Added
- Cross-process determinism tests (`test_determinism_across_subprocesses`,
  `test_determinism_of_get_rng_salt`) using subprocess invocation to
  verify reproducibility at the boundary that matters.
- `scripts/verify_synthetic_numeric.py` utility for reproducing drift
  scores across versions and environments.

### Notes
- No schema changes. No action required from users beyond upgrading.
- Upgrading from v0.10.0-rc.1 to rc.2 is safe. Existing DBs continue
  to work without migration.

## [0.10.0-rc.1] - 2025-04-21

### Added - Phase 1: Correctness Foundation

#### Deterministic Drift Detection
- **Seeded randomness** for reproducible drift reports
  - New `DRIFTBASE_SEED` environment variable (default: 42)
  - All random operations (bootstrap, sampling, anomaly detection) use deterministic RNG
  - Same data + same seed = byte-identical reports
  - Salt-based random streams prevent correlation between operations
  - New `utils/determinism.py` module with `get_rng(salt)` utility

#### Unified Sample Limits
- **Configurable sampling** via environment variables
  - New `DRIFTBASE_FINGERPRINT_LIMIT` (default: 5000) for max runs per fingerprint
  - New `DRIFTBASE_BOOTSTRAP_ITERS` (default: 500) for confidence interval iterations
  - Replaced hardcoded limits (1000, 5000) throughout codebase
  - Logging of effective limits at INFO level in engine and diff computation

#### Version Resolution Transparency
- **Version source tracking** for deployment drift accuracy
  - New `version_source` field in AgentRunLocal: `release | tag | env | epoch | unknown`
  - 4-level precedence: Langfuse release → version tag → DRIFTBASE_VERSION env → epoch fallback
  - Three-way quality classification:
    - Confident sources (release/tag/env): no warning
    - Unknown sources: soft advisory, no tier downgrade (pre-existing data)
    - Epoch sources: loud warning + tier downgrade (time-bucketed)
  - Epoch-resolved versions trigger warnings in `driftbase diff` (>50% threshold)
  - Automatic confidence tier downgrade for time-bucketed comparisons (TIER3→TIER2, TIER2→TIER1)
  - LangSmith connector now tracks version_source (matching Langfuse)

#### Ingestion Source Provenance
- **Ingestion method tracking** to separate connector vs decorator runs
  - New `ingestion_source` field: `connector | decorator | otlp | webhook`
  - `get_runs()` filters to `connector` by default (imported traces only)
  - New `include_all_sources` parameter for comprehensive analysis
  - `driftbase diagnose` uses all sources by default for complete diagnosis
  - Migration adds column with `decorator` default for backward compatibility

#### Synthetic Drift Test Fixtures
- **Accuracy baseline test suite** for verification of drift detection
  - 5 seeded generators in `tests/fixtures/synthetic/generators.py`:
    - `no_drift_pair`: Identical distributions (negative control)
    - `decision_drift_pair`: Tool sequence changes (30% shift)
    - `latency_drift_pair`: Bimodal latency (+500ms for half)
    - `error_rate_drift_pair`: Error rate increase (2% → 10%)
    - `semantic_cluster_drift_pair`: Outcome distribution shift (15% → 30% escalation)
  - 5 accuracy tests in `tests/test_synthetic_drift.py` verifying correct detection
  - All generators use deterministic RNG for reproducible tests
  - Baseline for validating future detection improvements

### Changed
- **get_runs() behavior**: Now filters to connector-sourced runs by default
- **Bootstrap sampling**: Uses fingerprint IDs as salt for reproducibility per comparison
- **Anomaly detection**: IsolationForest now uses configurable DRIFTBASE_SEED
- **DriftReport schema**: Added `warnings` list field for epoch version warnings

### Fixed
- Unseeded bootstrap sampling in `stats/hypothesis.py` (now uses deterministic RNG)
- Hardcoded random seeds in `local/diff.py` (42, 43, 0) replaced with salted seeds
- Inconsistent sample limits across engine (1000) and CLI (5000) paths

### Documentation
- New `docs/determinism.md`: Reproducible drift reports guide
- New `docs/version-resolution.md`: Version precedence and epoch fallback explanation
- Updated README.md with Phase 1 environment variables
- Added inline documentation for all new config options

### Migration
- Automatic schema migration adds `version_source` column (default: `"unknown"`)
- Automatic schema migration adds `ingestion_source` column (default: `"decorator"`)
- No action required - migrations run on first startup
- **Upgrading users**: First diff after upgrade will show soft advisory about pre-existing data
  - Advisory: "Some runs predate version-source tracking. Re-sync from Langfuse to improve diff confidence."
  - No tier downgrade for unknown sources
  - Re-run `driftbase connect` to clear advisory and get proper version_source tags

## [0.9.3] - 2025-04-19

### Added

#### GitHub Action (Distribution Engine)
- **GitHub Action for automated drift checking in CI/CD**
  - Composite action with purple branding (`activity` icon)
  - Standalone mode (100% local via SQLite) and Cloud mode (API-based)
  - Rich PR comments with color-coded verdict badges (✅ 👀 ⚠️ 🚫)
  - Dimension breakdowns with traffic light indicators (🔴 🟡 🟢)
  - Configurable gating: `fail-on-review` and `fail-on-monitor` flags
  - Automatic deletion of previous comments to avoid spam
  - Example workflow and comprehensive README
  - Full test suite (11 tests, all passing)

#### CLI Enhancements
- **`driftbase diff --ci`** flag for CI/CD-friendly JSON output
- **`driftbase diagnose`** now shows informative introduction panel
- **`driftbase demo --offline`** flag with privacy-first confirmation
- **`driftbase deploy mark`** command for labeling deployment outcomes

#### Connectors
- **LangSmith connector** (full implementation, 308 lines)
  - Matches Cloud feature parity
  - httpx-based API client with proper authentication
  - Tool sequence extraction from child runs
  - Retry detection and loop count inference
  - Time-to-first-tool calculation
- **Enhanced Langfuse connector**
  - Added 7 missing fields for Cloud parity:
    - model extraction from trace metadata
    - environment detection
    - improved latency calculation
    - task_input_hash and output_structure_hash
    - raw_prompt storage (with PII warning)
    - better error detection (metadata.error, status, level)
  - Incremental sync support via connector metadata
  - Better retry pattern detection

#### Weight Learning (Moat Building)
- **Progressive blending formula** for learned weights
  - 30% learned at n=10 labeled deployments
  - 50% learned at n=50 labeled deployments
  - 70% learned (capped) at n=100+ labeled deployments
  - The more you use it, the better it gets for your specific agent
- Deploy outcome tracking in SQLite backend
- Learned weights cache with automatic invalidation

#### Developer Experience
- **Installation verification script** (`scripts/verify_install.sh`)
  - 11 comprehensive checks
  - Tests CLI, demo, diff, deploy commands, MCP server, imports, test suite
- **MCP server** for Claude Desktop integration
  - Exposes drift detection to AI assistants
  - Verified working in all installation checks

### Changed

#### Architecture
- **Consolidated drift engine** into single public API (`engine.py`)
  - Clean separation: engine (compute) vs. local (storage/CLI)
  - All core functionality exported via `from driftbase.engine import *`
  - Removed internal implementation details from public API
- **SQLite backend** now uses SQLModel for type safety
- **Progressive confidence tiers** clearly defined:
  - TIER1 (n<15): Insufficient data, progress bars only
  - TIER2 (15≤n<50): Indicative signals with arrows (↑ ↓ →)
  - TIER3 (n≥50): Full statistical analysis with verdict

#### Documentation
- Updated README with GitHub Action as primary feature
- Added 60-second demo section
- Updated roadmap to reflect completed work
- Updated FAQ with LangSmith support
- Comprehensive GitHub Action README (282 lines)

### Fixed
- Progressive weight blending formula (changed from 20%-90% to 30%-70% cap)
- Invalid git tag issue (v0.9.1-pre-refocus → v0.9.2)
- Demo `--no-color` flag positioning (must come before subcommand)
- Weight learner tests updated to match new blending formula

### Removed
- Cleaned up orphaned files from previous architecture
- Removed duplicate connector implementations
- Pruned obsolete examples and scenarios

### Deferred (Requires Cloud API)

These features are deferred until api.driftbase.io is live:

- **Phase 8: Privacy-first telemetry**
  - Usage analytics with local aggregation
  - Opt-out by default, explicit opt-in required
  - No PII transmission
- **Phase 9: Opt-in data contribution**
  - Anonymized drift patterns for moat building
  - Improves baseline weights for all users
  - Fully optional, clear value exchange

## [0.9.2] - 2025-04-18

### Fixed
- Invalid git tag removed (v0.9.1-pre-refocus)
- Package installation via setuptools_scm

## [0.9.1] - 2025-04-17

### Added
- Initial open-source release
- Langfuse connector
- 12-dimension drift analysis
- Local SQLite storage
- CLI commands: connect, diagnose, diff, history

### Changed
- Removed internal Anthropic context and branding
- Cleaned up for public release

## [0.9.0] - 2025-04-01 (Internal)

- Internal pre-release version
- Not published to PyPI

---

## Version Naming Convention

- **0.9.x**: Pre-1.0 releases during initial development
- **1.0.0**: First stable release (planned after Cloud API launch)
- **1.x.y**: Stable releases with semantic versioning
  - Major (1.x.0): Breaking API changes
  - Minor (1.0.x): New features, backward compatible
  - Patch (1.0.0.x): Bug fixes only

## Upgrade Guide

### From 0.9.2 to 0.9.3

No breaking changes. New features:
- GitHub Action now available via `driftbase-labs/driftbase-python/github-action@v1`
- LangSmith connector: `driftbase connect langsmith --project my-agent`
- CLI enhancements: `--ci` flag, `--offline` demo, improved diagnose output

### From 0.9.1 to 0.9.2

No breaking changes. Bug fix release only.

---

[0.10.0-rc.1]: https://github.com/driftbase-labs/driftbase-python/compare/v0.9.3...v0.10.0-rc.1
[0.9.3]: https://github.com/driftbase-labs/driftbase-python/compare/v0.9.2...v0.9.3
[0.9.2]: https://github.com/driftbase-labs/driftbase-python/compare/v0.9.1...v0.9.2
[0.9.1]: https://github.com/driftbase-labs/driftbase-python/releases/tag/v0.9.1
