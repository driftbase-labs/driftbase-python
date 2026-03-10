# Driftbase

**Behavioral drift detection for AI agents.**

Fingerprint your agent's behavior in production. Diff two versions. Get a statistically grounded drift score and plain-English verdict — before your users notice something changed.

[![PyPI version](https://badge.fury.io/py/driftbase.svg)](https://pypi.org/project/driftbase/)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://www.apache.org/licenses/LICENSE-2.0)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)

---

## What it does

Most observability tools tell you your agent ran. They don't tell you it *behaved differently* than last week.

Driftbase records behavioral signals from each run — tool call sequences, latency percentiles, decision outcomes, error patterns — and computes a drift score when you compare two versions. Every deploy gets a verdict: ship, monitor, review, or block.

- **One decorator, zero config** — wraps your existing agent entry point
- **No account, no API key, no signup** — works out of the box
- **Data never leaves your machine** — local SQLite, always
- **Statistically rigorous** — bootstrap confidence intervals on every drift score
- **Plain-English verdicts** — not just a number, tells you what changed and what to do

---

## Quickstart

### 1. Install
```bash
pip install driftbase
```

### 2. Wrap your agent
```python
from driftbase import track

@track(version="v1.0")
def run_agent(input, config=None):
    return agent.invoke(input, config=config)
```

### 3. Run your agent normally

Generate at least 50 runs on each version you want to compare.
```bash
# Check how many runs you have
driftbase runs list
```

### 4. Deploy a new version
```python
@track(version="v2.0")
def run_agent(input, config=None):
    return agent.invoke(input, config=config)
```

### 5. Diff
```bash
driftbase diff v1.0 v2.0
```

### 6. Read your verdict
```
────────────────────────────────────────────────
  DRIFTBASE  v1.0 → v2.0  ·  127 vs 89 runs
────────────────────────────────────────────────

  drift_score      0.29  [0.24 – 0.34, 95% CI]

  decision_drift   0.47  ⚠ HIGH
  └─ escalation rate: 4% → 11%
  └─ agent is routing 2.1× more to humans

  latency_drift    0.17  · MODERATE
  └─ p95: 243ms → 423ms

  tool_dist        0.12  · LOW
  error_drift      0.04  ✓ STABLE

────────────────────────────────────────────────
  VERDICT  ⚠  REVIEW BEFORE SHIPPING
────────────────────────────────────────────────
  Most likely cause:
  → Decision layer changed — escalation rate
    jumped from 4% to 11%.

  Next steps:
  □ Review system prompt changes between versions
  □ Check outcome routing and decision tree logic

────────────────────────────────────────────────
  ✓ Computed in 120ms · No data left your machine
```

---

## How it works

Driftbase captures four behavioral signals per run:

| Signal | What it measures |
|---|---|
| **Tool distribution** | Which tools were called and how often |
| **Latency profile** | Response time percentiles (p50, p95, p99) |
| **Decision outcomes** | Escalation rate, resolution rate, fallback rate |
| **Error patterns** | Error rate and error type distribution |

After 50 runs, a behavioral fingerprint is computed. When you diff two versions, Driftbase computes Jensen-Shannon divergence between fingerprints across all four dimensions, runs 500 bootstrap iterations for confidence intervals, and produces a verdict.

**Nothing else is captured.** Raw inputs, outputs, prompts, and user content are never stored or transmitted.

---

## Privacy

| What | Status |
|---|---|
| Tool call names and sequences | ✓ Captured locally |
| Latency measurements | ✓ Captured locally |
| Decision outcome labels | ✓ Captured locally |
| Error type identifiers | ✓ Captured locally |
| SHA-256 input hash (deduplication only) | ✓ Captured locally |
| Raw user inputs or prompts | ✗ Never captured |
| Model outputs or completions | ✗ Never captured |
| Conversation content | ✗ Never captured |
| Any data transmitted to Driftbase | ✗ Free tier: never |

All data is stored in `~/.driftbase/runs.db`. Nothing leaves your machine in the free tier.

---

## Frameworks supported

| Framework | Integration |
|---|---|
| LangChain | `@track()` decorator on executor invocation |
| LangGraph | `@track()` decorator on compiled graph invoke |
| AutoGen | `@track()` decorator on conversation initiator |
| CrewAI | `@track()` decorator on crew kickoff |
| Raw OpenAI / Anthropic | `@track()` decorator on API call function |

See [Framework integrations](https://driftbase.io/docs/framework-integration) for copy-paste examples.

---

## CLI reference

| Command | Description | Example |
|---|---|---|
| `diff` | Compare two versions | `driftbase diff v1.0 v2.0` |
| `runs list` | List versions and run counts | `driftbase runs list` |
| `runs inspect` | Show detailed stats for a version | `driftbase runs inspect v1.0` |
| `runs delete` | Delete runs for a version | `driftbase runs delete --version v1.0` |
| `report` | Generate drift report | `driftbase report v1.0 v2.0 --format html` |
| `export` | Export raw run data | `driftbase export --version v1.0 --format json` |
| `config show` | Show current config and DB path | `driftbase config show` |

---

## Decorator reference
```python
@track(
    version="v1.0",          # Required. Version identifier for this run.
    agent_id="my-agent",     # Optional. Defaults to function name.
    tags={"env": "prod"},    # Optional. Arbitrary metadata per run.
    outcomes=["resolved",    # Optional. Enables decision rate monitoring.
              "escalated"]
)
def run_agent(input, config=None):
    return agent.invoke(input, config=config)
```

Async functions are supported:
```python
@track(version="v1.0")
async def run_agent(input, config=None):
    return await agent.ainvoke(input, config=config)
```

---

## Interpreting drift scores

| Score | Verdict | Action |
|---|---|---|
| 0.00 – 0.10 | ✓ STABLE | Ship |
| 0.10 – 0.20 | · MONITOR | Ship with monitoring |
| 0.20 – 0.40 | ⚠ REVIEW | Investigate before shipping |
| 0.40+ | ✗ BLOCK | Do not ship without review |

See [What to do about drift](https://driftbase.io/docs/what-to-do-about-drift) for dimension-specific playbooks.

---

## EU compliance

Driftbase is designed for European teams with compliance obligations:

- **GDPR by architecture** — no personal data captured, no DPA required for free tier
- **EU AI Act Articles 9 & 12** — behavioral audit trail generated automatically
- **DORA** — timestamped change documentation per deploy
- **No US servers** — free tier runs entirely on your machine

See [driftbase.io/docs/gdpr-compliance](https://driftbase.io/docs/gdpr-compliance) for details.

---

## Installation options
```bash
# Core (recommended)
pip install driftbase

# With semantic root-cause analysis (local embeddings, no API calls)
pip install driftbase[semantic]
```

Requires Python 3.9+. Works on macOS, Linux, and Windows (WSL recommended).

---

## Links

- **Website:** [driftbase.io](https://driftbase.io)
- **Docs:** [driftbase.io/docs](https://driftbase.io/docs/quickstart)
- **PyPI:** [pypi.org/project/driftbase](https://pypi.org/project/driftbase/)
- **License:** Apache 2.0
- **Contact:** hello@driftbase.io

---

## License

Apache License 2.0. See [LICENSE](LICENSE) for details.