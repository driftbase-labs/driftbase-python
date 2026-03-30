# Driftbase

**Behavioral drift detection for AI agents — catch regressions before your users do.**

Fingerprint your agent's behavior in production. Diff two versions. Get a statistically grounded drift score, financial impact analysis, and plain-English verdict — all computed locally on your machine.

[![PyPI version](https://badge.fury.io/py/driftbase.svg)](https://pypi.org/project/driftbase/)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://www.apache.org/licenses/LICENSE-2.0)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)

---

## What Driftbase does

Driftbase is a pre-production behavioral analysis tool for AI agents.

Before you ship a new version of your agent, run:

```bash
driftbase diff v1.0 v2.0
```

You get a statistically grounded drift score, financial impact, root-cause hypothesis, and a plain-English verdict (SHIP / MONITOR / REVIEW / BLOCK) — computed locally on your machine, no cloud required.

The free SDK is for pre-deploy analysis. Production monitoring is Pro.

### Core Value Proposition

| What You Get | Why It Matters |
|--------------|----------------|
| **Self-calibrating drift scores** | Weights and thresholds adapt to your agent's use case and baseline behavior automatically — no configuration needed |
| **Behavioral budgets** | Define acceptable ranges per dimension upfront. Breach fires immediately, before a full diff is needed |
| **Root cause pinpointing** | Correlates drift with recorded change events (model update, prompt change, RAG snapshot) and surfaces the most likely cause with confidence level |
| **Rollback suggestion** | When regression is unambiguous, surfaces the specific prior version to target in your deploy pipeline |
| **Financial impact analysis** | Translate token bloat into €/$ cost deltas for leadership |
| **Zero-egress architecture** | All data stays on your machine — no US servers, GDPR-compliant by design |
| **Framework-agnostic** | Auto-detects LangChain, LangGraph, OpenAI, AutoGen, CrewAI, smolagents, Haystack, DSPy, LlamaIndex — zero config |

---

## The 60-Second Quickstart

### 1. Install

```bash
pip install driftbase
```

That's it. All analysis features included.

For semantic drift detection (optional, adds ~50MB):
```bash
pip install 'driftbase[semantic]'
```

### 2. Run the demo

```bash
driftbase demo              # Standard demo (50 runs each)
driftbase demo --quick      # Fast mode (~5 seconds)
driftbase demo --interactive  # Step-by-step tutorial
```

### 3. Diff the versions

```bash
driftbase diff v1.0 v2.0
```

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

  Calibration
  ───────────────────────────────────────────
  Inferred use case   customer_support  (confidence: 0.84)
  Calibration method  statistical  (baseline n=312)
  Top dimensions      decision_drift 0.31 · tool_sequence 0.22 · latency 0.18

╭──────────────── Financial Impact ─────────────────╮
│ Cost increased by 223.6%. This change will cost   │
│ an additional €10.46 per 10,000 runs.             │
╰────────────────────────────────────────────────────╯

  Root Cause
  ────────────────────────────────────────────────────────
  Most likely cause   model version change  (confidence: HIGH)
                      gpt-4o-2024-03 → gpt-4o-2024-11
  Affected dims       decision_drift ✓  error_rate ✓  tool_sequence ✓
  Ruled out           prompt_hash (unchanged)
  Suggested action    Pin model version explicitly: model="gpt-4o-2024-03"

  Rollback
  ────────────────────────────────────────────────────────
  Suggested version   v1.2
  Reason              v1.2 was last stable (SHIP) with 312 runs recorded
  Command             driftbase rollback customer-agent v1.2

╭──────────────── VERDICT  ⚠ REVIEW ────────────────╮
│ Significant behavioral drift detected.             │
│                                                     │
│ Next steps:                                        │
│ □ Review prompt changes that removed tool usage   │
│ □ Check if escalation rate increase is acceptable │
│ □ Profile latency regression before production    │
╰────────────────────────────────────────────────────╯
```

---

## Instrument Your Code

Drop `@track` onto the function that runs your agent. Driftbase auto-detects your framework and captures telemetry with zero additional configuration.

```python
from driftbase import track

@track(version="v2.1")
def run_agent(user_query: str):
    # Your agent logic here — unchanged
    ...
```

### Full parameter reference

```python
@track(
    version="v2.1",                    # Required. Your deployment version string.
    environment="production",          # Optional. Label for filtering (staging/prod/etc).

    # Record what changed at deploy time — enables root cause pinpointing
    changes={
        "model_version": "gpt-4o-2024-11",
        "prompt_hash": "sha256:abc123...",
        "rag_snapshot": "snapshot-2024-03-21",
    },

    # Define acceptable ranges — breach fires immediately, before a full diff
    budget={
        "max_p95_latency": 4.0,        # seconds
        "max_error_rate": 0.05,        # 5%
        "max_escalation_rate": 0.20,   # 20%
        "min_resolution_rate": 0.70,   # 70%
        "max_retry_rate": 0.10,
        "max_loop_depth": 5.0,
    },

    # Optional. Default: "standard". Adjusts detection sensitivity.
    # strict = catches more, higher false positive rate
    # relaxed = only flags clear regressions
    sensitivity="strict",
)
def run_agent(user_query: str):
    ...
```

All parameters except `version` are optional. `@track(version="v2.1")` is all you need to start.

---

## Behavioral Budgets

Budgets are hard limits on absolute dimension values. They fire immediately when a rolling average breaches a limit — no full diff needed. Independent from drift scoring.

```python
@track(
    version="v2.0",
    budget={
        "max_p95_latency": 4.0,
        "max_error_rate": 0.05,
        "max_escalation_rate": 0.20,
        "min_resolution_rate": 0.70,
    }
)
def my_agent(query: str) -> str:
    ...
```

Breach detection activates after 5 runs. Uses a rolling window of the last 10 runs (configurable via `DRIFTBASE_BUDGET_WINDOW`). A single slow run does not trigger a breach — the window smooths noise.

**Supported budget keys:**

| Key | Dimension |
|-----|-----------|
| `max_p95_latency` | latency_p95 (seconds) |
| `max_p50_latency` | latency_p50 (seconds) |
| `max_error_rate` | error_rate (0.0–1.0) |
| `max_escalation_rate` | escalation outcome proportion |
| `min_resolution_rate` | resolution outcome proportion |
| `max_retry_rate` | retry_rate (0.0–1.0) |
| `max_loop_depth` | average loop depth |
| `max_verbosity_ratio` | verbosity_ratio |
| `max_output_length` | output token count |
| `max_time_to_first_tool` | seconds before first tool call |

**Define budgets in config (persistent, team defaults):**

```yaml
# .driftbase/config
budgets:
  my-agent-id:
    max_p95_latency: 4.0
    max_error_rate: 0.05
```

`@track` budget takes precedence over config file on key conflicts.

**CLI:**

```bash
driftbase budgets show [agent_id] [version]   # View breaches (exit 1 if any)
driftbase budgets set <agent_id> <version> --config budget.yaml
driftbase budgets clear [agent_id] [version]  # Clear breach history
```

`driftbase budgets show` returns exit code 1 if breaches exist — use it as a CI gate independent of drift verdict.

---

## Root Cause Pinpointing

Record what changed at deploy time. When drift is detected, Driftbase correlates the drifted dimensions with recorded change events and surfaces the most likely cause.

**Via `@track`:**

```python
@track(
    version="v2.0",
    changes={
        "model_version": "gpt-4o-2024-11",
        "prompt_hash": "sha256:abc123...",
        "rag_snapshot": "snapshot-2024-03-21",
    }
)
def my_agent(query: str) -> str:
    ...
```

**Via CLI (for infra-level changes outside your code):**

```bash
driftbase changes record my-agent v2.0 \
  --model-version gpt-4o-2024-11 \
  --prompt-hash sha256:abc123 \
  --rag-snapshot snapshot-2024-03-21 \
  --custom deployed_by=ci-pipeline-447

driftbase changes list my-agent [version]
```

**Supported change types:**

| Key | What it tracks |
|-----|----------------|
| `model_version` | LLM model identifier |
| `prompt_hash` | SHA256 of system prompt |
| `rag_snapshot` | RAG index or document snapshot identifier |
| `tool_version` | A specific tool's version |
| `custom_*` | Any custom key with `custom_` prefix |

When drift is detected, the diff output includes a root cause section showing the most likely cause, affected dimensions, ruled-out changes, and a suggested action. Confidence levels: HIGH (≥80%), MEDIUM (≥50%), LOW (≥20%), UNLIKELY (<20%).

Model version is auto-detected from run payloads when not explicitly provided — you get root cause data even without configuring `changes={}`.

---

## Rollback Suggestion

When verdict is REVIEW or BLOCK and a prior stable version exists in SQLite with 30+ runs, Driftbase surfaces the specific version to target in your deploy pipeline.

```
Rollback
────────────────────────────────────────────────────────
Suggested version   v1.2
Reason              v1.2 was last stable (SHIP) with 312 runs recorded
Command             driftbase rollback my-agent v1.2
```

Fires only when the regression is unambiguous. If the bar is not met, nothing is shown — a wrong suggestion destroys trust faster than no suggestion.

Conditions required: verdict is BLOCK or REVIEW, a prior version exists with SHIP or MONITOR verdict, that version has ≥30 runs recorded.

---

## Intelligent Scoring

Driftbase does not use hardcoded weights or thresholds. The scoring system self-calibrates to your specific agent automatically.

### How it works

**1. Use-case inference**

On every diff, Driftbase reads the tool names your agent called and infers its use case via keyword scoring across 14 categories: FINANCIAL, CUSTOMER_SUPPORT, RESEARCH_RAG, CODE_GENERATION, AUTOMATION, CONTENT_GENERATION, HEALTHCARE, LEGAL, HR_RECRUITING, DATA_ANALYSIS, ECOMMERCE_SALES, SECURITY_ITOPS, DEVOPS_SRE, GENERAL.

Each use case maps to a preset weight table that reflects what actually matters for that type of agent. A financial agent weights `decision_drift` and `error_rate` heavily. A content generation agent weights `semantic_drift` and `output_length`. Zero configuration required.

**2. Baseline variance calibration**

With 30+ runs, Driftbase measures each dimension's natural variance during a stable baseline period and applies a reliability multiplier:

```
reliability_multiplier = 1.0 / (1.0 + coefficient_of_variation)
```

Noisy dimensions (high natural variance) get their weight suppressed. Stable dimensions (low natural variance) keep their full weight. Thresholds are then derived statistically:

```
MONITOR  when score > baseline_mean + 2σ
REVIEW   when score > baseline_mean + 3σ
BLOCK    when score > baseline_mean + 4σ
```

**3. Volume-adjusted thresholds**

As run count grows, thresholds tighten automatically — because drift at 10,000 runs/month means more mishandled interactions than drift at 100 runs/month.

| Run count | Threshold adjustment |
|-----------|---------------------|
| < 500 | No adjustment |
| 500–2,000 | Tighten 10% |
| 2,000–10,000 | Tighten 20% |
| > 10,000 | Tighten 30% |

**4. Optional sensitivity override**

```python
@track(version="v2.0", sensitivity="strict")   # catches more, higher false positive rate
@track(version="v2.0", sensitivity="relaxed")  # only flags clear regressions
```

Or via env var: `DRIFTBASE_SENSITIVITY=strict`

### Drift dimensions (12 total)

| # | Dimension | What it measures |
|---|-----------|-----------------|
| 1 | decision_drift | Outcome distribution — resolved vs escalated vs fallback vs error |
| 2 | tool_sequence | Order in which tools are called (Markov transitions) |
| 3 | tool_distribution | Mix of which tools are used, regardless of order |
| 4 | latency | Composite of p50/p95/p99 — typical speed and tail behavior |
| 5 | error_rate | Proportion of runs that produced an error |
| 6 | loop_depth | How deeply the agent cycles through tool-call loops |
| 7 | verbosity_ratio | Ratio of output tokens to input tokens |
| 8 | retry_rate | How often the agent retries a tool call within a single run |
| 9 | output_length | Raw output token count distribution |
| 10 | time_to_first_tool | Latency from run start to first tool call — isolates reasoning overhead |
| 11 | semantic_drift | Whether the meaning of outputs shifts (requires `[semantic]` extra) |
| 12 | tool_sequence_transitions | Specific A→B Markov transitions — catches new paths through the tool graph |

The diff output shows which dimensions the calibration system weighted most heavily for your agent, and why.

### Verdict mapping

| Verdict | Meaning | CI exit code |
|---------|---------|--------------|
| SHIP | No meaningful drift detected | 0 |
| MONITOR | Minor drift — watch but don't block | 0 |
| REVIEW | Significant drift — human review recommended | 1 |
| BLOCK | Severe regression — block this deploy | 1 |

---

## Supported Frameworks

Driftbase auto-detects your framework. The `@track` decorator works with all of them.

Explicit tracers are available for frameworks where that provides better granularity:

| Framework | Integration |
|-----------|-------------|
| OpenAI SDK | `@track` auto-detects |
| LangChain | `@track` auto-detects |
| LangGraph | `@track` auto-detects |
| AutoGen | `@track` auto-detects |
| CrewAI | `@track` auto-detects |
| smolagents | `SmolagentsTracer` — captures generated code blocks and sandbox execution |
| Haystack | `HaystackTracer` — GDPR-hashed document content, component sequence |
| DSPy | `DSPyTracer` — exact model strings, signature tracking, optimizer excluded by default |
| LlamaIndex | `LlamaIndexTracer` — query, retrieval, LLM, embedding, synthesis events |

**smolagents:**
```python
from driftbase.integrations import SmolagentsTracer
tracer = SmolagentsTracer(version="v1.0", agent_id="research-agent")
agent = ToolCallingAgent(model=model, tools=tools, step_callbacks=[tracer])
```

**Haystack:**
```python
from driftbase.integrations import HaystackTracer
from haystack.tracing import enable_tracing
tracer = HaystackTracer(version="v1.0", agent_id="rag-pipeline")
enable_tracing(tracer)
```

**DSPy:**
```python
from driftbase.integrations import DSPyTracer
tracer = DSPyTracer(version="v1.0", agent_id="qa-system")
dspy.configure(callbacks=[tracer], lm=dspy.LM("openai/gpt-4o"))
```

**LlamaIndex:**
```python
from driftbase.integrations import LlamaIndexTracer
tracer = LlamaIndexTracer(version="v1.0", agent_id="rag-engine")
Settings.callback_manager.add_handler(tracer)
```

---

## CI/CD Integration

```bash
# Fail on REVIEW or BLOCK verdict
driftbase diff v1.0 v2.0 --exit-nonzero-above 0.15

# Gate on budget health independently of drift verdict
driftbase budgets show my-agent v2.0  # exit 1 if breaches exist

# Output formats
driftbase diff v1.0 v2.0 --format md > pr_comment.md
driftbase diff v1.0 v2.0 --json > drift_report.json
```

GitHub Actions example:

```yaml
- name: Drift check
  run: |
    pip install driftbase
    driftbase diff ${{ env.BASELINE_VERSION }} ${{ env.DEPLOY_VERSION }} \
      --exit-nonzero-above 0.15
```

---

## Data Privacy & Sovereignty

Driftbase is engineered for European teams with strict compliance obligations (GDPR, EU AI Act, DORA, NIS2).

- **Local-first**: All data stays in `~/.driftbase/runs.db` on your machine
- **No telemetry**: No third-party analytics
- **Structural hashing**: We analyze *what tools were called*, not *what the user said*
- **Edge PII scrubbing**: Optional regex-based redaction before disk write

```bash
export DRIFTBASE_SCRUB_PII=true
```

Strips emails, IBANs, phone numbers, and IP addresses from tool parameters and user inputs before hashing. Scrubbing happens at the edge — sensitive data never touches disk.

---

## Configuration Reference

```bash
# Database location (default: ~/.driftbase/runs.db)
DRIFTBASE_DB_PATH="/path/to/runs.db"

# Default version label if not set in @track
DRIFTBASE_DEPLOYMENT_VERSION="v2.1"

# Environment label
DRIFTBASE_ENVIRONMENT="staging"

# Detection sensitivity: strict | standard | relaxed (default: standard)
DRIFTBASE_SENSITIVITY="strict"

# Budget rolling window size (default: 10, min: 5)
DRIFTBASE_BUDGET_WINDOW=10

# Retention limit (default: 100,000 runs)
DRIFTBASE_LOCAL_RETENTION_LIMIT=50000

# PII scrubbing (default: false)
DRIFTBASE_SCRUB_PII=true

# Token pricing for cost delta calculation
DRIFTBASE_RATE_PROMPT_1M=2.50       # € per 1M prompt tokens
DRIFTBASE_RATE_COMPLETION_1M=10.00  # € per 1M completion tokens

# Pro sync
DRIFTBASE_API_KEY="your_pro_key"
```

Layered config: env vars → `.driftbase/config` → `pyproject.toml [tool.driftbase]` → defaults.

```bash
driftbase config   # Show resolved configuration
driftbase doctor   # Check configuration and database health
```

---

## CLI Reference

### Analysis

| Command | Description |
|---------|-------------|
| `driftbase diff <v1> <v2>` | Compare two versions — the main event |
| `driftbase diagnose` | Pattern recognition on a single version |
| `driftbase compare <v1> <v2> <v3>` | Multi-version comparison |

### Data

| Command | Description |
|---------|-------------|
| `driftbase runs -v <version>` | List runs for a version |
| `driftbase versions` | List all versions and run counts |
| `driftbase inspect <run_id>` | Deep-dive a specific run |
| `driftbase prune` | Delete runs by retention criteria |
| `driftbase export` | Export runs to JSON |
| `driftbase import <file>` | Import runs from JSON |
| `driftbase baseline` | Set/get/clear baseline version |

### Pre-production gates

| Command | Description |
|---------|-------------|
| `driftbase budgets` | Define acceptance criteria, view breaches |
| `driftbase changes` | Record what changed at deploy time |
| `driftbase deploy` | Label versions good/bad for weight learning |

### Visualization

| Command | Description |
|---------|-------------|
| `driftbase chart -v <version>` | Terminal charts for run metrics |
| `driftbase cost` | Financial impact analysis |
| `driftbase demo` | Generate synthetic runs for exploration |

### Setup

| Command | Description |
|---------|-------------|
| `driftbase init` | Interactive setup |
| `driftbase config` | Show resolved configuration |
| `driftbase doctor` | Check configuration and database health |

---

## Architecture

```
┌─────────────────────────────────────────────────┐
│ 1. Your Agent Code                              │
│    @track(version="v2.1", changes={...},        │
│           budget={...})                         │
└─────────────────┬───────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────────┐
│ 2. Auto-Detection Layer                         │
│    Detects: LangChain / LangGraph / OpenAI /    │
│    AutoGen / CrewAI / smolagents / Haystack     │
│    Captures: tools, tokens, latency, errors,    │
│    loop depth, verbosity, retries, outcomes     │
└─────────────────┬───────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────────┐
│ 3. PII Scrubbing + Structural Hashing           │
│    Optional regex redaction at the edge         │
│    Hash tool parameters, preserve structure     │
└─────────────────┬───────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────────┐
│ 4. Background Writer                            │
│    Non-blocking writes to SQLite (WAL mode)     │
│    Budget breach detection after each batch     │
│    Change event persistence on first run        │
└─────────────────┬───────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────────┐
│ 5. Local SQLite — ~/.driftbase/runs.db          │
│    Tables: agent_runs_local, calibration_cache, │
│    budget_configs, budget_breaches,             │
│    change_events                                │
└─────────────────────────────────────────────────┘

Later, in your terminal or CI:

┌─────────────────────────────────────────────────┐
│ driftbase diff v2.0 v2.1                        │
│   ↓                                             │
│ 1. Load runs from SQLite                        │
│ 2. Infer use case from tool names               │
│ 3. Calibrate weights from baseline variance     │
│ 4. Compute 12-dimension drift score             │
│ 5. Correlate with change events → root cause    │
│ 6. Check for rollback candidate                 │
│ 7. Render verdict with financial impact         │
└─────────────────────────────────────────────────┘
```

---

## Driftbase Pro

Local SQLite is perfect for individual feature branches and CI pipelines. Driftbase Pro adds:

- EU-hosted centralized dashboard (GDPR-compliant)
- Team collaboration and shared baselines
- Long-term trend analysis and alerting
- SSO/SAML for enterprise

```bash
export DRIFTBASE_API_KEY="your_pro_key"
driftbase push   # Sync local runs — raw text stripped before upload
```

[Learn more →](https://driftbase.io/pro)

---

## FAQ

**Q: Does this slow down my agent?**
A: No. `@track` writes to an in-memory bounded queue and returns immediately. Background thread persists to SQLite. Production overhead is <1ms per run.

**Q: How many runs do I need before calibration activates?**
A: 30 runs per version. Below that, Driftbase uses preset weights for your inferred use case and logs a notice. Statistical calibration (baseline variance → per-dimension thresholds) activates at 30+ runs automatically.

**Q: What if Driftbase infers the wrong use case?**
A: Check `driftbase diff --verbose` to see which tool names matched and what use case was inferred. If the inference is wrong, it means your tool names don't contain strong keywords for the correct category. You can also check `driftbase config` for the resolved settings. If you consistently see wrong inference, open an issue with your tool names and we'll add keywords.

**Q: Can I disable telemetry in tests?**
A: Yes. `export DRIFTBASE_DB_PATH=/tmp/driftbase-test.db` points to a throwaway file. No data is sent anywhere unless you run `driftbase push`.

**Q: How accurate is the cost calculation?**
A: Very accurate. Token counts are read directly from LLM responses and multiplied by your configured rates. Default rates are OpenAI list prices.

**Q: Does this work with Azure OpenAI / Anthropic / local LLMs?**
A: Yes. Any OpenAI-compatible client is supported.

**Q: When should I use `[semantic]`?**
A: Only if you want semantic drift detection — detecting whether the meaning of agent outputs shifts over time. Requires ~50MB of additional model weights. Everything else works without it.

**Q: Can I self-host the Pro dashboard?**
A: Not yet. Enterprise self-hosted is on the roadmap. Email pro@driftbase.io for early access.

---

## Development Setup

```bash
pip install -e '.[dev]'
pre-commit install     # Runs ruff format + lint before each commit
pytest tests/          # Run test suite
```

---

## Contributing

Areas of interest:
- Additional framework integrations
- Additional drift dimensions (retrieval quality, safety/alignment metrics)
- Alternative statistical tests (MMD, Wasserstein distance)
- Visualization improvements

**Before submitting a PR:** install pre-commit hooks, run tests, check types with `mypy src/`.

---

## License

Apache License 2.0. See [LICENSE](LICENSE) for details.

---

## Community & Support

- **Documentation:** [docs.driftbase.io](https://docs.driftbase.io)
- **GitHub Issues:** [github.com/driftbase-labs/driftbase-python/issues](https://github.com/driftbase-labs/driftbase-python/issues)
- **Email:** support@driftbase.io
- **Pro:** pro@driftbase.io

**Built with 🇪🇺 in Europe. Data sovereignty by default.**
