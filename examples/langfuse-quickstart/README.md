# Driftbase + Langfuse Quickstart

Get drift detection running in 5 minutes using your existing Langfuse traces.

## Prerequisites

1. **Langfuse account** with existing traces from your AI agent
   - Sign up at [cloud.langfuse.com](https://cloud.langfuse.com) if you don't have one
   - Your agent should already be traced with Langfuse (via any framework: LangChain, LangGraph, OpenAI, etc.)

2. **Langfuse API keys**
   - Go to Langfuse Settings → API Keys
   - Copy your Public Key and Secret Key

## Setup (2 minutes)

### 1. Install Driftbase

```bash
pip install driftbase
```

### 2. Set your Langfuse credentials

```bash
export LANGFUSE_PUBLIC_KEY=pk-lf-...
export LANGFUSE_SECRET_KEY=sk-lf-...
export LANGFUSE_HOST=https://cloud.langfuse.com  # optional, defaults to cloud
```

### 3. Connect and import traces

```bash
# Auto-detect and import (recommended)
driftbase connect

# Or specify project explicitly
driftbase connect langfuse --project my-agent --limit 1000
```

This will:
- Fetch up to 1000 traces from Langfuse
- Map them to Driftbase's behavioral schema
- Store them locally in `~/.driftbase/runs.db`
- Infer decision outcomes (resolved/escalated/error) heuristically

## Usage (3 minutes)

### View behavioral history

```bash
# See all versions and their behavioral fingerprints
driftbase history

# Filter by version
driftbase history --version v1.0
```

### Detect drift

```bash
# Automatic drift detection across all versions
driftbase diagnose

# Compare specific versions
driftbase diff v1.0 v2.0
```

### Continuous monitoring

Set up a daily sync to keep pulling new traces:

```bash
# Add to cron or GitHub Actions
driftbase connect langfuse --project my-agent --since $(date -d '1 day ago' +%Y-%m-%d)
driftbase diagnose
```

## What gets analyzed

Driftbase computes drift across 12 behavioral dimensions:

1. **Decision drift** - Changes in outcome distribution (resolved/escalated/error)
2. **Tool sequence** - Pattern changes in tool usage order
3. **Tool distribution** - Frequency changes in which tools are called
4. **Latency** - p95 latency shifts
5. **Error rate** - Proportion of failed runs
6. **Retry rate** - How often the agent retries operations
7. **Loop depth** - Changes in iterative reasoning patterns
8. **Verbosity ratio** - Output length relative to input
9. **Output length** - Total token count in responses
10. **Time to first tool** - How quickly the agent starts using tools
11. **Semantic drift** - Heuristic clustering of output semantics
12. **Tool transitions** - Changes in tool-to-tool call patterns

## Example output

```
═══════════════════════════════════════════════════════════════════════
DRIFT DIAGNOSIS
═══════════════════════════════════════════════════════════════════════

Agent: my-agent
Environment: production

┌─────────────┬──────┬─────────┬──────────────┬──────────┐
│ Version     │ Runs │ Latency │ Error Rate   │ Outcome  │
├─────────────┼──────┼─────────┼──────────────┼──────────┤
│ v1.0        │  120 │  1.2s   │ 2%           │ baseline │
│ v2.0        │   85 │  0.9s   │ 8%           │ ⚠ DRIFT  │
└─────────────┴──────┴─────────┴──────────────┴──────────┘

⚠ DETECTED DRIFT: v1.0 → v2.0

Top 3 drift signals:
  1. error_rate: 2% → 8% (+300%)
  2. decision_drift: 15% fewer "resolved" outcomes
  3. tool_sequence: "validate→execute→confirm" → "execute→validate"

Recommendation: REVIEW before production deploy
```

## Integration patterns

### GitHub Actions CI

```yaml
name: Drift Detection
on: [pull_request]

jobs:
  drift-check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - run: pip install driftbase
      - env:
          LANGFUSE_PUBLIC_KEY: ${{ secrets.LANGFUSE_PUBLIC_KEY }}
          LANGFUSE_SECRET_KEY: ${{ secrets.LANGFUSE_SECRET_KEY }}
        run: |
          driftbase connect
          driftbase diff prod-baseline ${{ github.sha }}
```

### Daily Monitoring

```bash
#!/bin/bash
# cron: 0 9 * * * /path/to/drift-check.sh

export LANGFUSE_PUBLIC_KEY=pk-lf-...
export LANGFUSE_SECRET_KEY=sk-lf-...

driftbase connect langfuse --project my-agent --since $(date -d '1 day ago' +%Y-%m-%d)
driftbase diagnose --alert-on-drift
```

## Next steps

- **Baseline calibration**: Run `driftbase baseline calibrate` after collecting 100+ runs
- **Use-case tuning**: Driftbase auto-infers your agent type, but you can override with `--use-case`
- **Custom thresholds**: Set drift sensitivity via `driftbase config`
- **Budget tracking**: Monitor cost drift with `driftbase budgets`

## FAQs

### Do I need to change my agent code?

No. Driftbase reads existing Langfuse traces. Your agent continues using Langfuse exactly as before.

### Where is my data stored?

All analysis runs locally. Traces are stored in `~/.driftbase/runs.db` (SQLite). Nothing leaves your machine.

### What if I don't have historical traces?

Use `driftbase testset generate` to create synthetic baseline data, or start collecting traces now and compare future versions.

### How often should I sync?

- **Development**: After every agent change
- **Production**: Daily or on-deploy via CI/CD

### Does this work with LangSmith?

Not yet. Driftbase currently supports Langfuse only. LangSmith support is planned.

## Support

- Docs: [driftbase.io/docs](https://driftbase.io/docs)
- Issues: [github.com/driftbase-labs/driftbase-python/issues](https://github.com/driftbase-labs/driftbase-python/issues)
- Discord: [driftbase.io/discord](https://driftbase.io/discord)
