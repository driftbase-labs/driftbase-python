# Changelog

All notable changes to Driftbase will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

[0.9.3]: https://github.com/driftbase-labs/driftbase-python/compare/v0.9.2...v0.9.3
[0.9.2]: https://github.com/driftbase-labs/driftbase-python/compare/v0.9.1...v0.9.2
[0.9.1]: https://github.com/driftbase-labs/driftbase-python/releases/tag/v0.9.1
