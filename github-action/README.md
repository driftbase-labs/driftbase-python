# Driftbase GitHub Action

**Behavioral drift detection for AI agents in CI/CD**

This GitHub Action automatically detects behavioral drift between agent versions and posts detailed reports as PR comments. Gate deployments based on drift severity to prevent regressions.

## Features

- 🔍 **12-Dimensional Drift Analysis** — Decision patterns, tool usage, latency, error rates, and more
- 🚦 **Automated CI Gating** — Block, review, monitor, or ship based on drift severity
- 💬 **Rich PR Comments** — Color-coded verdict badges, dimension breakdowns, plain English explanations
- 🏠 **Standalone Mode** — Runs 100% locally via SQLite (default)
- ☁️ **Cloud Mode** — Optionally use Driftbase Cloud API for advanced features
- 🔒 **Privacy-First** — Zero data transmission in standalone mode

## Quick Start

### 1. Add Workflow File

Create `.github/workflows/drift-check.yml`:

```yaml
name: Drift Check

on:
  pull_request:
    branches: [main]

permissions:
  pull-requests: write
  contents: read

jobs:
  drift-check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Run Driftbase drift check
        uses: driftbase-labs/driftbase-python/github-action@v1
        with:
          baseline-version: main
          current-version: ${{ github.head_ref }}
          fail-on-review: true
          fail-on-monitor: false
          github-token: ${{ secrets.GITHUB_TOKEN }}
```

### 2. Instrument Your Agent

Make sure your agent records traces via Langfuse or LangSmith:

```python
from langfuse import Langfuse

langfuse = Langfuse()

# In your agent code:
langfuse.trace(
    name="my-agent",
    session_id="my-agent",
    version="v1.0",  # Must match baseline-version/current-version
    input={"query": "..."},
    output={"response": "..."}
)
```

### 3. Deploy and Test

1. Deploy baseline version with `version="main"` or `version="v1.0"`
2. Generate at least 50 runs to establish baseline
3. Create a PR with changes using `version="feature-branch"` or `version="v2.0"`
4. GitHub Action will automatically detect drift and post a report

## Inputs

| Input | Required | Default | Description |
|-------|----------|---------|-------------|
| `baseline-version` | ✅ | — | Baseline version to compare against (e.g., `main`, `v1.0`) |
| `current-version` | ✅ | — | Current version being deployed (e.g., `feature-branch`, `v2.0`) |
| `github-token` | ✅ | — | GitHub token for PR comments (use `${{ secrets.GITHUB_TOKEN }}`) |
| `fail-on-review` | ❌ | `true` | Fail CI if verdict is REVIEW |
| `fail-on-monitor` | ❌ | `false` | Fail CI if verdict is MONITOR |
| `driftbase-api-key` | ❌ | — | Driftbase Cloud API key (enables Cloud mode) |
| `environment` | ❌ | `production` | Filter runs by environment |
| `sensitivity` | ❌ | `standard` | Threshold sensitivity: `strict`, `standard`, or `relaxed` |

## Outputs

| Output | Description |
|--------|-------------|
| `verdict` | Deployment verdict: `SHIP`, `MONITOR`, `REVIEW`, or `BLOCK` |
| `drift-score` | Overall drift score (0.0 - 1.0) |
| `exit-code` | Exit code (0 for pass, 1 for fail) |

## Modes

### Standalone Mode (Default)

Runs 100% locally using SQLite database:

```yaml
- uses: driftbase-labs/driftbase-python/github-action@v1
  with:
    baseline-version: main
    current-version: ${{ github.head_ref }}
    github-token: ${{ secrets.GITHUB_TOKEN }}
```

**Requirements:**
- Driftbase CLI installed (`pip install driftbase`)
- Local SQLite database with recorded runs
- At least 50 runs per version for statistical significance

### Cloud Mode

Uses Driftbase Cloud API for advanced features:

```yaml
- uses: driftbase-labs/driftbase-python/github-action@v1
  with:
    baseline-version: main
    current-version: ${{ github.head_ref }}
    github-token: ${{ secrets.GITHUB_TOKEN }}
    driftbase-api-key: ${{ secrets.DRIFTBASE_API_KEY }}
```

**Additional features:**
- Centralized drift tracking across teams
- Historical drift trends and analytics
- Advanced anomaly detection
- Full report URLs in PR comments

## Configuration Examples

### Strict Gating

Block PRs on REVIEW verdict:

```yaml
- uses: driftbase-labs/driftbase-python/github-action@v1
  with:
    baseline-version: main
    current-version: ${{ github.head_ref }}
    fail-on-review: true
    fail-on-monitor: false
    github-token: ${{ secrets.GITHUB_TOKEN }}
```

### Very Strict Gating

Block PRs on MONITOR or REVIEW:

```yaml
- uses: driftbase-labs/driftbase-python/github-action@v1
  with:
    baseline-version: main
    current-version: ${{ github.head_ref }}
    fail-on-review: true
    fail-on-monitor: true
    github-token: ${{ secrets.GITHUB_TOKEN }}
```

### Advisory Only

Never fail CI, just post reports:

```yaml
- uses: driftbase-labs/driftbase-python/github-action@v1
  with:
    baseline-version: main
    current-version: ${{ github.head_ref }}
    fail-on-review: false
    fail-on-monitor: false
    github-token: ${{ secrets.GITHUB_TOKEN }}
```

### Multi-Environment

Compare staging to production:

```yaml
- uses: driftbase-labs/driftbase-python/github-action@v1
  with:
    baseline-version: v1.0-production
    current-version: v2.0-staging
    environment: staging
    github-token: ${{ secrets.GITHUB_TOKEN }}
```

### Relaxed Sensitivity

For experimental features:

```yaml
- uses: driftbase-labs/driftbase-python/github-action@v1
  with:
    baseline-version: main
    current-version: ${{ github.head_ref }}
    sensitivity: relaxed
    github-token: ${{ secrets.GITHUB_TOKEN }}
```

## Understanding Verdicts

| Verdict | Meaning | Default Behavior |
|---------|---------|------------------|
| ✅ **SHIP IT** | Minimal drift, safe to deploy | Pass |
| 👀 **SHIP WITH MONITORING** | Moderate drift, deploy with caution | Pass |
| ⚠️ **REVIEW BEFORE SHIPPING** | Significant drift, manual review recommended | Fail (configurable) |
| 🚫 **DO NOT SHIP** | Critical drift, likely regression | Fail (always) |

## PR Comment Format

The action posts a comprehensive drift report:

```markdown
## 🔍 Driftbase Behavioral Report

**main** → **feature-branch**

---

### ✅ **SHIP IT**

| | |
|---|---|
| **Drift Score** | **0.12** (low) |
| **Confidence** | TIER3 |
| **Sample Size** | 1000 baseline · 950 current |

### What Changed

| Dimension | Drift |
|---|---|
| 🟢 **Decision patterns** | 8% |
| 🟢 **Latency** | 5% |
| 🟢 **Error rate** | 2% |

### Analysis

Minor latency variation within normal bounds. All behavioral dimensions remain stable.

**Recommended actions:**
- Continue monitoring
- No action required

---
🤖 Generated by Driftbase — 100% local, zero data transmission
```

## Data Requirements

For accurate drift detection:

- **Minimum:** 15 runs per version (TIER2 confidence)
- **Recommended:** 50+ runs per version (TIER3 confidence)
- **Best:** 100+ runs per version (maximum statistical power)

If insufficient data exists, the action will post a warning comment but **never fail** the CI check.

## Troubleshooting

### "No baseline data found"

**Cause:** No recorded runs for baseline version.

**Fix:**
1. Ensure baseline version has been deployed and generated traces
2. Check version identifiers match exactly (case-sensitive)
3. Verify environment filter is correct

### "Insufficient data for statistical analysis"

**Cause:** Fewer than 50 runs recorded for one or both versions.

**Fix:**
1. Continue deploying and generating runs
2. Wait until you have 50+ runs per version
3. Typical timeline: 1-7 days depending on traffic

### "driftbase command not found"

**Cause:** Driftbase CLI not installed in standalone mode.

**Fix:** The action automatically installs Driftbase CLI. If this error occurs, check GitHub Actions logs for installation failures.

### "GitHub API error 403"

**Cause:** Insufficient permissions to post PR comments.

**Fix:** Add permissions to workflow:
```yaml
permissions:
  pull-requests: write
  contents: read
```

## Privacy and Security

### Standalone Mode
- Runs 100% locally on GitHub Actions runner
- All data stored in SQLite database
- Zero data transmission to external services
- Raw prompts stay on your infrastructure

### Cloud Mode
- POSTs drift metrics to api.driftbase.io
- Raw prompts are scrubbed via Presidio before transmission
- All PII is removed server-side
- View privacy policy at https://driftbase.io/privacy

## Advanced Usage

### Using with Multiple Agents

Label runs with unique session IDs:

```python
langfuse.trace(
    session_id="agent-customer-support",
    version="v1.0",
    # ...
)

langfuse.trace(
    session_id="agent-sales-assistant",
    version="v1.0",
    # ...
)
```

### Custom Thresholds

Adjust sensitivity for different use cases:

- `strict`: Low tolerance for drift (0.15 threshold for REVIEW)
- `standard`: Balanced approach (0.25 threshold for REVIEW)
- `relaxed`: High tolerance for drift (0.35 threshold for REVIEW)

### Incremental Sync

The action supports incremental sync in standalone mode — only new traces since the last run are processed.

## Testing Locally

Test the action locally before committing:

```bash
# Install dependencies
pip install driftbase

# Generate demo data
driftbase demo --offline

# Test drift computation
driftbase diff v1.0 v2.0 --ci

# Run action tests
cd github-action/src
python test_run.py
```

## Support

- **Documentation:** https://docs.driftbase.io
- **Issues:** https://github.com/driftbase-labs/driftbase-python/issues
- **Community:** https://discord.gg/driftbase

## License

MIT License — See [LICENSE](../LICENSE) for details.
