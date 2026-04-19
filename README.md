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
| **Zero cold start** | Start detecting drift from day 1 using your existing Langfuse traces — no SDK to add, no baseline to collect |
| **Self-calibrating drift scores** | Weights and thresholds adapt to your agent's use case and baseline behavior automatically — no configuration needed |
| **Behavioral budgets** | Define acceptable ranges per dimension upfront. Breaches fire immediately, before manual drift checks |
| **Root cause pinpointing** | Correlates drift with version changes and surfaces the most likely cause with confidence level |
| **Rollback suggestion** | When regression is unambiguous, suggests the specific prior version to roll back to |
| **Financial impact analysis** | Translate token bloat into €/$ cost deltas for leadership |
| **Zero-egress architecture** | All data stays on your machine — no US servers, GDPR-compliant by design |
| **Framework-agnostic** | Works with any framework already traced in Langfuse — LangChain, OpenAI, CrewAI, custom agents |

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

## Use Cases

### 1. Pre-Deploy Drift Gate (CI/CD)

```yaml
# .github/workflows/drift-check.yml
name: Drift Check
on: [pull_request]

jobs:
  drift:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - run: pip install driftbase
      - env:
          LANGFUSE_PUBLIC_KEY: ${{ secrets.LANGFUSE_PUBLIC_KEY }}
          LANGFUSE_SECRET_KEY: ${{ secrets.LANGFUSE_SECRET_KEY }}
        run: |
          driftbase connect
          driftbase diff main ${{ github.sha }} --exit-on-block
```

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

- [x] Langfuse connector
- [x] 12-dimension drift analysis
- [x] Self-calibrating weights & thresholds
- [x] Anomaly detection
- [x] Behavioral epochs
- [x] Root cause correlation
- [ ] LangSmith connector
- [ ] Arize connector
- [ ] Generic OTEL ingestion
- [ ] Slack/PagerDuty alerting
- [ ] Web dashboard (Pro tier)

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

Not yet. Driftbase currently supports **Langfuse only**. LangSmith, Arize, and generic OTEL support are planned for future releases.

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
