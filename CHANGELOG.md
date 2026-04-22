# Changelog

All notable changes to Driftbase will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
