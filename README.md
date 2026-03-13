# Driftbase

**Behavioral drift detection for AI agents.**

Fingerprint your agent's behavior in production. Diff two versions. Get a statistically grounded drift score, financial impact analysis, and plain-English verdict — before your users notice something changed.

[![PyPI version](https://badge.fury.io/py/driftbase.svg)](https://pypi.org/project/driftbase/)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://www.apache.org/licenses/LICENSE-2.0)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)

---

## What it does

Most observability tools tell you your agent ran. They don't tell you it *behaved differently* than last week.

Driftbase records behavioral signals from each run — tool call sequences, latency percentiles, token cost bloat, and decision outcomes — and computes a drift score when you compare two versions. Every deploy gets a verdict: ship, monitor, review, or block.

- **One decorator, zero config** — wraps your existing agent entry point.
- **Financial impact** — translates token bloat directly into Euro (€) cost deltas.
- **Data never leaves your machine** — local SQLite, zero egress architecture.
- **Edge PII Scrubbing** — built-in regex engine strips emails, IBANs, and IPs before hashing.
- **Plain-English verdicts** — tells you exactly what changed and what to do next.

---

## The 60-Second Quickstart

See the drift engine in action right now without writing any code.

### 1. Install

**For production tracking** (decorator only):
```bash
pip install driftbase
```

**For local analysis** (CLI + diff engine):
```bash
pip install 'driftbase[analyze]'
```

The base install provides the `@track()` decorator with minimal dependencies (pydantic, httpx). The `[analyze]` profile adds numpy, scipy, and rich for statistical drift computation and terminal UI.

### 2. Run the synthetic demo
This command instantly populates your local database with 50 baseline runs (v1.0) and 50 regressed runs (v2.0 with higher token usage and hallucinated tool calls).

```bash
driftbase demo
```

### 3. Diff the versions
```bash
driftbase diff v1.0 v2.0
```

You will immediately see a rich terminal UI detailing the financial impact, tool sequence changes, and a root-cause hypothesis:

```plaintext
────────────────────────────────────────────────
  DRIFTBASE  v1.0 → v2.0  ·  50 vs 50 runs
────────────────────────────────────────────────

  Overall drift      0.28  [0.24–0.31, 95% CI]

  Decisions          0.39  · MODERATE
    └─ escalation rate jumped from 5% → 17%
  Latency            0.34  · MODERATE
    └─ p95 increased 4970ms → 6684ms
  Errors             0.03  ✓ STABLE

╭──────────────── Financial Impact ─────────────────╮
│ Cost increased by 223.6%. This change will cost   │
│ an additional €10.46 per 10,000 runs.             │
╰────────────────────────────────────────────────────╯

╭──────────────── VERDICT  ⚠ REVIEW ────────────────╮
│ Most likely cause:                                 │
│   → Tool 'search_knowledge_base' dropped from      │
│     baseline — no longer being called              │
╰────────────────────────────────────────────────────╯
```

### 4. Inspect the failure
Grab a run ID from the synthetic data and see exactly what happened. This proves your raw text is safely hashed at the edge:

```bash
driftbase inspect <RUN_ID>
```

---

## Instrument Your Code

Once you see the value, drop Driftbase into your actual application. It auto-detects LangChain, LangGraph, LlamaIndex, and raw OpenAI clients.

**In your production container** (requires only `pip install driftbase`):
```python
from driftbase import track
import openai

@track(version="v1.0")
def run_agent(prompt: str):
    client = openai.Client()
    return client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        tools=[{"type": "function", "function": {"name": "query_db"}}]
    )

# Run your code normally. Telemetry is silently captured in ~/.driftbase/runs.db
run_agent("What's the revenue for Q4?")
```

**On your laptop or in CI** (requires `pip install 'driftbase[analyze]'`), let the data decide:

```bash
driftbase diff v1.0 v2.0 --format md > pr_comment.md
```

The `@track` decorator has zero production overhead (pydantic + httpx only). Statistical analysis runs locally with numpy/scipy.

---

## EU Compliance & Data Sovereignty

Driftbase is engineered specifically for European teams with strict compliance obligations (GDPR, EU AI Act, DORA).

- **Zero-Egress**: The free tier runs entirely on your machine. Data never goes to US servers.
- **Structural Hashing**: We analyze the structure of the behavior, not the sensitive context.
- **Edge PII Scrubbing**: Enable the scrubber to redact personal data before it even hits your local disk.

```bash
# Enable PII redaction
export DRIFTBASE_SCRUB_PII=true

# Configure your custom enterprise rates for accurate cost deltas
export DRIFTBASE_RATE_PROMPT_1M=2.50
export DRIFTBASE_RATE_COMPLETION_1M=10.00
```

---

## Driftbase Pro (Team Sync)

Local SQLite is perfect for individual feature branches. But when Engineer A and Engineer B need to compare baselines, or when you deploy to production, you need a shared source of truth.

To sync your local runs to a secure, EU-hosted centralized dashboard:

```bash
export DRIFTBASE_API_KEY="your_pro_key"
driftbase push
```

[Learn more about Driftbase Pro](https://driftbase.io/pro)

---

## CLI Reference

| Command | Description |
|---------|-------------|
| `driftbase demo` | Inject synthetic runs to test the engine |
| `driftbase diff <v1> <v2>` | Compare two versions (use `--format md` for CI/CD) |
| `driftbase inspect <id>` | Deep-dive into a specific run's execution path |
| `driftbase watch -a <v1>` | Live terminal dashboard monitoring incoming runs |
| `driftbase runs -v <v1>` | List all local runs for a version |
| `driftbase config` | View your current local configuration and DB path |
| `driftbase push` | Sync local database to the Driftbase Pro cloud |

---

## License

Apache License 2.0. See LICENSE for details.
