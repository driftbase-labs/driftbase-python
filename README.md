# Driftbase

**Behavioral drift detection for AI agents using your Langfuse traces.**

AI agents drift. A prompt update, a model swap, a RAG reindex — any of these can shift how your agent makes decisions, without triggering a single test failure.

Driftbase tells you **when** your agent changed, **what** caused it, and whether it got **better or worse** — by analyzing the traces you're already collecting in Langfuse.

```bash
pip install driftbase
```

Connect your Langfuse instance:

```bash
export LANGFUSE_PUBLIC_KEY=pk-lf-...
export LANGFUSE_SECRET_KEY=sk-lf-...

driftbase connect
```

Then, when something feels off:

```bash
driftbase diagnose
```

```
DRIFTBASE DIAGNOSTIC

  Behavioral shift detected 11 days ago (2026-03-20)
  Most likely cause: prompt change in release v2.1
  Affected:          escalation rate 4% → 19%, latency +1.2s

  Recommendation:    REVIEW before production deploy
```

No agent code changes. No instrumentation. Just instant answers from your existing Langfuse data.

[![PyPI version](https://badge.fury.io/py/driftbase.svg)](https://pypi.org/project/driftbase/)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://www.apache.org/licenses/LICENSE-2.0)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)

---

## How it works

Driftbase is a **drift detection layer** on top of Langfuse. You already trace your agent with Langfuse — Driftbase reads those traces and detects behavioral drift.

### 1. You're already tracing with Langfuse

Your AI agent is instrumented with Langfuse (via LangChain, LangGraph, OpenAI, or any other framework). Traces flow into Langfuse automatically.

### 2. Connect Driftbase to Langfuse

Driftbase pulls historical traces from Langfuse and stores them locally for analysis:

```bash
driftbase connect
```

This imports your traces into a local SQLite database (`~/.driftbase/runs.db`). All analysis runs on your machine. No data leaves your environment.

### 3. Detect drift

**When something feels wrong:**
```bash
driftbase diagnose
```

Scans your full trace history, detects behavioral shifts, and correlates them with version changes.

**Compare explicit versions:**
```bash
driftbase diff v1.0 v2.0
```

Produces a statistical drift score and a deployment verdict (SHIP / MONITOR / REVIEW / BLOCK).

**View behavioral history:**
```bash
driftbase history
```

Shows how your agent's behavior evolved over time — which epochs were stable, which shifted, and what changed at each breakpoint.

---

## Core Value Proposition

| What You Get | Why It Matters |
|--------------|----------------|
| **60-second wow moment** | Run `driftbase demo --offline` to see drift detection on synthetic data with zero dependencies |
| **Zero cold start** | Start detecting drift from day 1 using your existing Langfuse traces — no SDK to add, no baseline to collect |
| **GitHub Action integration** | Automatic drift checks on every PR with rich, color-coded reports posted as comments |
| **Self-calibrating drift scores** | Weights and thresholds learn from your labeled deployments — the more you use it, the better it gets |
| **Root cause pinpointing** | Correlates drift with version changes and surfaces the most likely cause with confidence level |
| **100% local-first** | All data stays on your machine in SQLite — no cloud required, GDPR-compliant by design |
| **Framework-agnostic** | Works with any framework already traced in Langfuse or LangSmith — LangChain, OpenAI, CrewAI, custom agents |
| **Progressive confidence** | Starts working with just 15 runs, full statistical power at 50+ runs per version |

---

## 60-Second Demo (No Dependencies)

Want to see drift detection in action before connecting your own traces?

```bash
pip install driftbase
driftbase demo --offline
```

This generates synthetic agent runs showing realistic behavioral drift scenarios and walks you through the core commands. **100% offline, zero external dependencies.**

---

## The 5-Minute Quickstart

### 1. Install

```bash
pip install driftbase
```

### 2. Set Langfuse credentials

```bash
export LANGFUSE_PUBLIC_KEY=pk-lf-...
export LANGFUSE_SECRET_KEY=sk-lf-...
export LANGFUSE_HOST=https://cloud.langfuse.com  # optional
```

Get your keys from [Langfuse Settings → API Keys](https://cloud.langfuse.com).

### 3. Import traces

```bash
# Auto-detect and import
driftbase connect

# Or specify project explicitly
driftbase connect langfuse --project my-agent --limit 1000
```

### 4. Detect drift

```bash
# Automatic drift detection
driftbase diagnose

# Compare specific versions
driftbase diff v1.0 v2.0

# View behavioral history
driftbase history
```

**That's it.** You're detecting drift in 5 minutes using traces you already have.

See [examples/langfuse-quickstart](examples/langfuse-quickstart/) for a complete walkthrough.

---

## What Driftbase analyzes

Driftbase computes drift across **12 behavioral dimensions**:

1. **Decision drift** — Changes in outcome distribution (resolved/escalated/error)
2. **Tool sequence** — Pattern changes in tool usage order
3. **Tool distribution** — Frequency changes in which tools are called
4. **Latency** — p95 latency shifts
5. **Error rate** — Proportion of failed runs
6. **Retry rate** — How often the agent retries operations
7. **Loop depth** — Changes in iterative reasoning patterns
8. **Verbosity ratio** — Output length relative to input
9. **Output length** — Total token count in responses
10. **Time to first tool** — How quickly the agent starts using tools
11. **Semantic drift** — Heuristic clustering of output semantics
12. **Tool transitions** — Changes in tool-to-tool call patterns

Each dimension is weighted based on your agent's inferred use case (e.g., customer support vs. code generation).

---

## CLI Commands

### Core Commands

```bash
# Connect to Langfuse and import traces
driftbase connect

# Detect drift automatically across all versions
driftbase diagnose

# Compare two specific versions
driftbase diff v1.0 v2.0

# View behavioral history over time
driftbase history

# Interactive setup guide
driftbase init
```

### Advanced Commands

```bash
# Inspect individual runs
driftbase inspect <run-id>

# Export drift report as JSON
driftbase export --format json --output report.json

# Set up behavioral budgets
driftbase budgets set --dimension error_rate --threshold 0.05

# Prune old runs to save space
driftbase prune --before 2026-01-01

# Health check
driftbase doctor
```

---

## CI/CD Integration

Driftbase integrates seamlessly into deployment pipelines to catch behavioral regressions before production.

### Output Formats

```bash
# Rich terminal output (default)
driftbase diff v1.0 v2.0

# JSON for programmatic consumption
driftbase diff v1.0 v2.0 --format=json

# Markdown for PR comments
driftbase diff v1.0 v2.0 --format=markdown
```

### Exit Codes

- **Exit 0**: SHIP or MONITOR verdicts (safe to deploy)
- **Exit 1**: REVIEW or BLOCK verdicts (manual review required)

### Quick Start: GitHub Actions

```yaml
# .github/workflows/drift-check.yml
name: Drift Check

on: [pull_request]

jobs:
  drift:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: pip install driftbase
      - run: driftbase diff v1.2.3 v1.3.0 --ci
        env:
          DRIFTBASE_DB_PATH: ./runs.db
```

The `--ci` flag enables:
- JSON output
- Non-zero exit on drift
- Compact formatting

### Detailed Verdict Analysis

After a diff completes, use `driftbase explain` to see the full breakdown:

```bash
# Explain most recent verdict
driftbase explain

# Explain specific verdict by ID
driftbase explain abc-123-def
```

Shows:
- Top 3 contributing dimensions with evidence
- Confidence intervals and significance markers
- Minimum Detectable Effects (MDEs)
- Rollback target (for REVIEW/BLOCK verdicts)

### PR Comment Integration

Post drift reports directly to pull requests:

```yaml
- name: Generate drift report
  run: |
    OUTPUT=$(driftbase diff v1 v2 --format=markdown)
    echo "report<<EOF" >> $GITHUB_OUTPUT
    echo "$OUTPUT" >> $GITHUB_OUTPUT
    echo "EOF" >> $GITHUB_OUTPUT

- uses: actions/github-script@v7
  with:
    script: |
      github.rest.issues.createComment({
        issue_number: context.issue.number,
        owner: context.repo.owner,
        repo: context.repo.name,
        body: `${{ steps.drift.outputs.report }}`
      })
```

Result: GitHub-flavored markdown table with top contributors, MDEs, and rollback targets.

### Rollback on Regression

```bash
VERDICT=$(driftbase diff v1 v2 --format=json | jq -r .verdict)
ROLLBACK=$(driftbase diff v1 v2 --format=json | jq -r .rollback_target)

if [ "$VERDICT" = "BLOCK" ]; then
  echo "Behavioral regression detected. Rolling back to $ROLLBACK"
  kubectl set image deployment/agent agent=$ROLLBACK
  exit 1
fi
```

See [docs/ci-integration.md](docs/ci-integration.md) for GitLab CI, CircleCI, and advanced patterns.

---

## Use Cases

### 1. Pre-Deploy Drift Gate (GitHub Action)

Add `.github/workflows/drift-check.yml`:

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
          github-token: ${{ secrets.GITHUB_TOKEN }}
```

Posts a color-coded drift report as a PR comment with verdict (SHIP/MONITOR/REVIEW/BLOCK) and dimension breakdown.

See [github-action/README.md](github-action/README.md) for full documentation.

### 2. Post-Deploy Monitoring

```bash
#!/bin/bash
# Daily drift check (cron: 0 9 * * *)

export LANGFUSE_PUBLIC_KEY=...
export LANGFUSE_SECRET_KEY=...

driftbase connect --since $(date -d '1 day ago' +%Y-%m-%d)
driftbase diagnose --alert-on-drift
```

### 3. Incident Response

When users report unexpected agent behavior:

```bash
# Pull latest traces and diagnose
driftbase connect --since 2026-03-01
driftbase diagnose

# Inspect specific problematic run
driftbase inspect <run-id>

# Compare current vs. last known good
driftbase diff v2.0-stable v2.1-current
```

---

## Configuration

Driftbase works out of the box with zero configuration. Optional settings:

```bash
# Set custom DB path
export DRIFTBASE_DB_PATH=/path/to/runs.db

# Set default Langfuse host
export LANGFUSE_HOST=https://your-instance.com

# Configure cost tracking
export DRIFTBASE_RATE_PROMPT_1M=2.50
export DRIFTBASE_RATE_COMPLETION_1M=10.00

# Reproducibility and sampling (Phase 1 correctness features)
export DRIFTBASE_SEED=42                    # Random seed for reproducible drift reports (default: 42)
export DRIFTBASE_FINGERPRINT_LIMIT=5000     # Max runs per fingerprint (default: 5000)
export DRIFTBASE_BOOTSTRAP_ITERS=500        # Bootstrap iterations for confidence intervals (default: 500)
```

See [docs/configuration.md](docs/configuration.md) for advanced settings.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│  YOUR AI AGENT                                               │
│  (instrumented with Langfuse via any framework)              │
└────────────────┬─────────────────────────────────────────────┘
                 │
                 │ traces
                 ▼
┌──────────────────────────────────────────────────────────────┐
│  LANGFUSE                                                    │
│  (observability platform)                                    │
└────────────────┬─────────────────────────────────────────────┘
                 │
                 │ driftbase connect
                 ▼
┌──────────────────────────────────────────────────────────────┐
│  DRIFTBASE                                                   │
│  ├─ Local SQLite DB (runs, fingerprints, epochs)            │
│  ├─ Drift analysis engine (12 dimensions)                   │
│  ├─ Baseline calibrator (auto-weights + thresholds)         │
│  ├─ Anomaly detector (multivariate outliers)                │
│  └─ Verdict engine (SHIP/MONITOR/REVIEW/BLOCK)              │
└──────────────────────────────────────────────────────────────┘
```

**Key principle:** Driftbase is NOT a tracing tool. It's a drift detection layer that reads existing traces from Langfuse.

---

## Roadmap

**Completed:**
- [x] Langfuse connector with incremental sync
- [x] LangSmith connector
- [x] 12-dimension drift analysis
- [x] Progressive weight learning from labeled deployments
- [x] Statistical confidence tiers (TIER1/TIER2/TIER3)
- [x] GitHub Action with standalone + cloud modes
- [x] MCP server for Claude Desktop integration
- [x] 60-second offline demo

**Deferred (requires Cloud API):**
- [ ] Privacy-first telemetry
- [ ] Opt-in data contribution for moat building

**Future:**
- [ ] Arize connector
- [ ] Generic OTEL ingestion
- [ ] Slack/PagerDuty alerting
- [ ] Web dashboard (Cloud tier)

---

## Development

```bash
# Clone repo
git clone https://github.com/driftbase-labs/driftbase-python
cd driftbase-python

# Install in editable mode with dev dependencies
pip install -e '.[dev]'

# Run tests
pytest tests/

# Run linter
ruff check .
ruff format .
```

---

## FAQ

### Do I need to change my agent code?

No. Driftbase reads existing Langfuse traces. Your agent continues using Langfuse exactly as before.

### Where is my data stored?

All analysis runs locally. Traces are stored in `~/.driftbase/runs.db` (SQLite). Nothing leaves your machine unless you explicitly push to a remote backend (Pro tier feature).

### What if I don't have Langfuse yet?

Set up Langfuse first: [langfuse.com/docs/get-started](https://langfuse.com/docs/get-started). It takes ~10 minutes to instrument your agent with Langfuse, then you can use Driftbase.

### What if I don't have historical traces?

Use `driftbase testset generate` to create synthetic baseline data, or start collecting traces now and compare future versions.

### How often should I sync?

- **Development**: After every agent change
- **Production**: Daily or on-deploy via CI/CD

### Does this work with LangSmith?

Yes! Driftbase supports both **Langfuse and LangSmith**. Use:

```bash
driftbase connect langsmith --project my-agent
```

Arize and generic OTEL support are planned for future releases.

### Is this free?

Yes. The OSS SDK is free forever. We'll offer a Pro tier (hosted web dashboard, real-time alerting, team features) in the future, but the local CLI will always be free.

---

## Support

- **Docs**: [driftbase.io/docs](https://driftbase.io/docs)
- **Issues**: [github.com/driftbase-labs/driftbase-python/issues](https://github.com/driftbase-labs/driftbase-python/issues)
- **Discord**: [driftbase.io/discord](https://driftbase.io/discord)
- **Email**: info@driftbase.io

---

## License

Apache 2.0. See [LICENSE](LICENSE).

---

Built with ❤️ for AI engineers who want to ship with confidence.
