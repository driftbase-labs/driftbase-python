# Driftbase

**Behavioral drift detection for AI agents — catch regressions before your users do.**

Fingerprint your agent's behavior in production. Diff two versions. Get a statistically grounded drift score, financial impact analysis, and plain-English verdict — all computed locally on your machine.

[![PyPI version](https://badge.fury.io/py/driftbase.svg)](https://pypi.org/project/driftbase/)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://www.apache.org/licenses/LICENSE-2.0)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)

---

## Why Driftbase?

Most observability tools tell you your agent *ran*. They don't tell you it **behaved differently** than last week.

When you deploy a new prompt, update your model version, or refactor tool calling logic, you need answers:
- Did decision patterns change? (Are we routing more to humans?)
- Did latency increase? (Are we burning tokens on retry loops?)
- Did costs balloon? (What's the financial impact per 10k runs?)
- What *caused* the change? (Which tool disappeared from the call graph?)

Driftbase gives you a single drift score, a financial delta in euros, and a root-cause hypothesis — in 2 seconds, from your terminal.

### Core Value Proposition

| What You Get | Why It Matters |
|--------------|----------------|
| **Statistical drift scores** | Know *how much* behavior changed (0.0 = identical, 1.0 = completely different) |
| **Financial impact analysis** | Translate token bloat into €/$ cost deltas for leadership |
| **Root cause hypotheses** | Auto-generated plain-English explanations of what changed |
| **Zero-egress architecture** | All data stays on your machine — no US servers, GDPR-compliant by design |
| **EU AI Act compliance** | Generate Article 72 post-market monitoring reports with `--template eu-ai-act` |
| **Framework-agnostic** | Auto-detects LangChain, LangGraph, OpenAI, AutoGen, CrewAI, smolagents, Haystack, DSPy, LlamaIndex — zero config |

---

## The 60-Second Quickstart

See the drift engine in action **right now** without writing any code.

### 1. Install

**For production tracking** (decorator only, minimal deps):
```bash
pip install driftbase
```

**For local analysis** (CLI + statistical diff engine):
```bash
pip install 'driftbase[analyze]'
```

The base install adds the `@track()` decorator with minimal dependencies (pydantic, httpx, click). The `[analyze]` profile adds numpy, scipy, and rich for statistical drift computation and beautiful terminal UI.

### 2. Run the synthetic demo

This command instantly populates your local database with 50 baseline runs (v1.0) and 50 regressed runs (v2.0) that simulate real behavioral drift:

```bash
driftbase demo
```

**Note:** Run this only once on a fresh database. To reset, delete `~/.driftbase/runs.db` before running again.

### 3. Diff the versions

```bash
driftbase diff v1.0 v2.0
```

You'll immediately see a rich terminal UI with financial impact, tool sequence changes, and root-cause analysis:

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
│ Significant behavioral drift detected.             │
│                                                     │
│ Most likely cause:                                 │
│   → Tool 'search_knowledge_base' dropped from      │
│     baseline — no longer being called              │
│                                                     │
│ Next steps:                                        │
│ □ Review prompt changes that removed tool usage   │
│ □ Check if escalation rate increase is acceptable │
│ □ Profile latency regression before production    │
╰────────────────────────────────────────────────────╯
```

### 4. Inspect individual runs

Grab a run ID from the output and deep-dive into exactly what happened:

```bash
driftbase inspect <RUN_ID>
```

This proves your raw text is safely hashed at the edge — only structural metadata is stored.

---

## Instrument Your Code

Once you see the value, drop Driftbase into your actual application. It auto-detects your framework and captures telemetry with zero configuration.

### Supported Frameworks

Driftbase has native integrations for:
- **OpenAI SDK** (direct client calls)
- **LangChain** (chains, agents, tools)
- **LangGraph** (graph-based workflows)
- **AutoGen** (multi-agent conversations)
- **CrewAI** (crew-based agent orchestration)
- **smolagents** (Hugging Face code-first agents)
- **Haystack** (deepset RAG pipelines)
- **DSPy** (programmatic prompt optimization)
- **LlamaIndex** (data framework for LLM applications)

### Quick Integration Examples

#### OpenAI SDK

```python
from driftbase import track
import openai

@track(version="v2.1")
def run_agent(user_query: str):
    client = openai.Client()
    return client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": user_query}],
        tools=[{"type": "function", "function": {"name": "query_database"}}]
    )

# Just run your code normally. Telemetry is captured automatically.
result = run_agent("What's Q4 revenue?")
```

#### LangChain

```python
from driftbase import track
from langchain.agents import AgentExecutor, create_openai_functions_agent
from langchain_openai import ChatOpenAI

@track(version="v2.1", environment="staging")
def run_langchain_agent(query: str):
    llm = ChatOpenAI(model="gpt-4o")
    agent = create_openai_functions_agent(llm, tools, prompt)
    executor = AgentExecutor(agent=agent, tools=tools)
    return executor.invoke({"input": query})

result = run_langchain_agent("Find similar documents")
```

#### LangGraph

```python
from driftbase import track
from langgraph.graph import StateGraph

@track(version="v2.1")
def run_langgraph_workflow(input_data: dict):
    graph = StateGraph(state_schema)
    # ... build your graph
    return graph.invoke(input_data)
```

#### smolagents (Hugging Face)

For **code-first agents** that require full auditability (EU AI Act compliance):

```python
from driftbase.integrations import SmolagentsTracer
from smolagents import ToolCallingAgent, DuckDuckGoSearchTool

tracer = SmolagentsTracer(version="v1.0", agent_id="research-agent")
agent = ToolCallingAgent(
    model=model,
    tools=[DuckDuckGoSearchTool()],
    step_callbacks=[tracer]  # Attach the tracer
)
result = agent.run("Find the latest AI regulations")
```

**Why use the explicit tracer?** smolagents generates Python code at runtime and executes it in a sandbox. The `SmolagentsTracer` captures:
- **Generated code blocks** (full text for local audit trail)
- **Sandbox execution outputs** (stdout, results, errors)
- **Planning steps** (model reasoning before code generation)
- **Action steps** (actual code execution)

This provides **complete traceability** for high-risk AI systems under EU AI Act Article 72.

#### Haystack (deepset)

For **GDPR-compliant RAG pipelines** (German/Dutch enterprise on-premise deployments):

```python
from driftbase.integrations import HaystackTracer
from haystack import Pipeline
from haystack.tracing import enable_tracing

tracer = HaystackTracer(version="v1.0", agent_id="rag-pipeline")
enable_tracing(tracer)  # Enable BEFORE building pipeline

pipeline = Pipeline()
# ... add retriever, prompt builder, LLM components
result = pipeline.run({"query": "What are GDPR requirements?"})
```

**GDPR-first design:** By default, document content is **SHA256-hashed**, not stored as raw text. This prevents GDPR liability when retrieving employee records or financial data. The tracer captures:
- **Document metadata** (source, score, content hash)
- **Component execution sequence** (embedder → retriever → prompt builder → LLM)
- **Filters applied** (metadata queries for reproducibility)
- **Retrieval counts** (number of chunks per query)

Set `record_full_text=True` to store raw text (opt-in for companies that accept the privacy risk).

#### DSPy

For **programmatic LM systems** requiring exact model traceability (EU AI Act compliance):

```python
from driftbase.integrations import DSPyTracer
import dspy

tracer = DSPyTracer(version="v1.0", agent_id="qa-system")
dspy.configure(callbacks=[tracer], lm=dspy.LM("openai/gpt-4o"))

class QA(dspy.Module):
    def forward(self, question):
        return dspy.Predict("question -> answer")(question=question)

qa = QA()
result = qa(question="What is DSPy?")
```

**EU AI Act traceability:** The tracer captures **exact model strings** (e.g., "openai/gpt-4o-mini") and token counts per module. If a provider silently updates model weights and causes failures, European auditors can trace back to the precise model version. The tracer also captures:
- **Signature strings** ("question -> answer") - documented intent for transparency
- **Resolved field schemas** (actual input/output structure)
- **Reasoning steps** (ChainOfThought, ReAct intermediate thoughts)
- **LM metadata** (model, provider, tokens)

**GDPR data minimization:** `track_optimizer=False` by default. DSPy teleprompters run thousands of LM calls during compilation. Storing these violates data minimization principles and bloats your database. Only production inference is tracked unless you explicitly set `track_optimizer=True` for debugging.

#### LlamaIndex

For **RAG and agentic workflows** with comprehensive event tracking:

```python
from driftbase.integrations import LlamaIndexTracer
from llama_index.core import VectorStoreIndex, SimpleDirectoryReader
from llama_index.core.settings import Settings

tracer = LlamaIndexTracer(version="v1.0", agent_id="rag-engine")
Settings.callback_manager.add_handler(tracer)

documents = SimpleDirectoryReader("data").load_data()
index = VectorStoreIndex.from_documents(documents)
query_engine = index.as_query_engine()
response = query_engine.query("What is LlamaIndex?")
```

**Comprehensive event capture:** The tracer hooks into LlamaIndex's native callback system and captures every operation:
- **Query events** (user queries with latency)
- **Retrieval events** (documents retrieved from index, GDPR-hashed)
- **LLM events** (generation calls with exact model name and token counts)
- **Embedding events** (query and document vectorization)
- **Synthesis events** (response generation from retrieved context)

**Migration from auto-detection:** If you were using the `@track()` decorator with LlamaIndex, switch to the explicit `LlamaIndexTracer` for better event granularity and control. The auto-detection fallback has been removed in favor of the explicit integration.

### Behavioral Metrics Captured

The `@track` decorator automatically captures comprehensive behavioral telemetry:

**Core Metrics:**
- **Tool call sequences** and parameters (SHA256 hashed)
- **Token usage** (prompt + completion tokens)
- **Latency distribution** (p50, p95, p99)
- **Error rates and types**
- **Decision outcomes** (e.g., escalation to human)
- **Cost deltas** (computed from your configured rates)

**Advanced Behavioral Metrics (New):**
- **Loop count** (`loop_count`) - Number of tool execution iterations (tracks agentic reasoning depth)
- **Verbosity ratio** (`verbosity_ratio`) - Response length relative to input (detects output bloat)
- **Tool call sequence** (`tool_sequence`) - Ordered list of tools called (tracks decision pathways)
- **Time to first tool** (`time_to_first_tool_ms`) - Latency before agent takes first action
- **Retry count** (`retry_count`) - Number of tool call retries (reliability indicator)
- **Output length** (`output_length`) - Character count of final response
- **Tool sequence drift** (`tool_sequence_drift`) - Detects changes in tool calling order

These metrics enable detection of subtle behavioral changes:
- **Reasoning depth changes**: Loop count increases suggest more complex agent reasoning
- **Response verbosity changes**: Verbosity ratio spikes indicate wordier outputs
- **Decision pathway changes**: Tool sequence shifts reveal altered problem-solving strategies
- **Performance regressions**: Time-to-first-tool increases suggest planning bottlenecks
- **Reliability issues**: Retry count increases indicate tool instability

All data is stored in `~/.driftbase/runs.db` (SQLite) with automatic retention limits and WAL mode for safe concurrent writes.

---

## Diff Analysis & CI/CD Integration

Once you have telemetry from two versions, compare them locally:

```bash
# Terminal UI (requires [analyze] profile)
driftbase diff v2.0 v2.1

# Markdown for PR comments
driftbase diff v2.0 v2.1 --format md > pr_comment.md

# JSON for automated pipelines
driftbase diff v2.0 v2.1 --format json > drift_report.json

# HTML report for stakeholders
driftbase diff v2.0 v2.1 --format html --output report.html
```

### Statistical Methodology

Driftbase uses the **Kolmogorov-Smirnov test** to measure distributional differences between version populations:
- **Bootstrap confidence intervals** (95% CI) for stable estimates with small sample sizes
- **Composite drift score** weighted across 10 behavioral dimensions:
  - **Tool sequence distribution** (40%) — Which tools are called and in what order
  - **Latency distribution** (12%) — Response time changes (p50, p95, p99)
  - **Error rates** (12%) — Failure and exception patterns
  - **Semantic clustering** (8%) — Decision outcome distribution (resolved, escalated, error)
  - **Output structure** (4%) — Changes in response schema/format
  - **Verbosity ratio** (6%) — Response length relative to input (output bloat detection)
  - **Loop count** (6%) — Agentic reasoning depth (number of tool execution iterations)
  - **Output length** (4%) — Absolute response size changes
  - **Tool sequence drift** (4%) — Changes in tool calling order/patterns
  - **Retry count** (4%) — Tool call retry frequency (reliability indicator)
- **Hypothesis engine** that generates plain-English root-cause explanations (see [Hypothesis rules](docs/hypothesis_rules.md) for the two YAML roles and how to override)

This isn't just logging — it's a **statistical behavioral fingerprint** that captures both performance and behavioral changes.

---

## EU AI Act Compliance Reporting

For teams subject to the EU AI Act (Regulation 2024/1689), Driftbase can generate Article 72 post-market monitoring reports:

```bash
driftbase report v2.0 v2.1 --format html --template eu-ai-act --sign
```

This produces a self-contained HTML compliance report with:
1. **Cover page** with compliance notice and metadata
2. **Compliance status badge** mapping verdict to regulatory language
3. **Article 72 evidence table** documenting monitoring requirements
4. **Detailed behavioral metrics** with EU AI Act article references
5. **SHA256 integrity hash** (when `--sign` flag is used) for tamper detection
6. **Legal disclaimer** clarifying the tool's role in compliance

Output filename: `drift-report-eu-ai-act-{baseline}-{current}-{timestamp}.html`

**Important:** This tool assists with post-market monitoring but does not replace human oversight, risk assessment, or legal review. Consult qualified legal counsel for compliance guidance.

---

## Data Privacy & Sovereignty

Driftbase is engineered for European teams with strict compliance obligations (GDPR, EU AI Act, DORA, NIS2).

### Zero-Egress Architecture

- **Local-first**: All data stays in `~/.driftbase/runs.db` on your machine
- **No telemetry**: We removed PostHog and all third-party analytics
- **Structural hashing**: We analyze *what tools were called*, not *what the user said*
- **Edge PII scrubbing**: Optional regex-based redaction before disk write

### Enable PII Scrubbing

```bash
export DRIFTBASE_SCRUB_PII=true
```

This strips emails, IBANs, phone numbers, and IP addresses from tool parameters and user inputs before hashing. Scrubbing happens **at the edge** — sensitive data never touches disk.

### Database Resilience

Driftbase implements a robust database path fallback chain:
1. `~/.driftbase/runs.db` (default)
2. `/tmp/driftbase/runs.db` (if home directory unavailable)
3. `./driftbase/runs.db` (current working directory)

This ensures telemetry works in Docker containers, CI environments, and restricted filesystems.

### Retention & Performance

- **Automatic pruning**: Oldest runs are deleted when count exceeds `DRIFTBASE_LOCAL_RETENTION_LIMIT` (default: 100,000)
- **Pruning optimization**: Runs every 100 batches (~1,000 records) instead of every write for 99% less overhead
- **Drop counter**: Logs warning every 100 dropped payloads if background writer can't keep up
- **WAL mode**: SQLite write-ahead logging for safe concurrent access

---

## Configuration Reference

Driftbase is **zero-config by default** but fully customizable via environment variables:

### Core Settings

```bash
# Database location (default: ~/.driftbase/runs.db)
export DRIFTBASE_DB_PATH="/path/to/custom/runs.db"

# Default deployment version (if not set in @track decorator)
export DRIFTBASE_DEPLOYMENT_VERSION="v2.1"

# Environment label (e.g., production, staging, dev)
export DRIFTBASE_ENVIRONMENT="staging"

# Retention limit (default: 100,000 runs)
export DRIFTBASE_LOCAL_RETENTION_LIMIT=50000

# Queue size for background writer (default: 10,000)
export DRIFTBASE_MAX_QUEUE_SIZE=20000
```

### Privacy & Scrubbing

```bash
# Enable PII redaction (default: false)
export DRIFTBASE_SCRUB_PII=true
```

### Financial Configuration

```bash
# Configure your enterprise rates for accurate cost deltas
export DRIFTBASE_RATE_PROMPT_1M=2.50      # € per 1M prompt tokens
export DRIFTBASE_RATE_COMPLETION_1M=10.00 # € per 1M completion tokens
```

### UI & Output

```bash
# Disable colored output (default: false)
export DRIFTBASE_OUTPUT_COLOR=false
```

### Driftbase Pro (Team Sync)

```bash
# API key for syncing to centralized dashboard
export DRIFTBASE_API_KEY="your_pro_key"
```

View your current configuration:

```bash
driftbase config
```

---

## CLI Reference

### Core Commands

| Command | Description |
|---------|-------------|
| `driftbase init` | Interactive setup guide — get started in 60 seconds |
| `driftbase config` | Show current configuration (env, config file, defaults) |
| `driftbase doctor` | Check configuration and database health |
| `driftbase status` | Quick dashboard of key metrics and system health |
| `driftbase demo` | Inject synthetic runs to test the drift engine |

### Drift Detection & Analysis

| Command | Description |
|---------|-------------|
| `driftbase diff <v1> <v2>` | Compare two versions with statistical analysis |
| `driftbase watch -a <version>` | Live terminal dashboard monitoring incoming runs |
| `driftbase report <v1> <v2>` | Generate shareable reports (markdown, JSON, HTML, EU AI Act) |

### Data Management

| Command | Description |
|---------|-------------|
| `driftbase runs -v <version>` | List runs for a deployment version |
| `driftbase versions` | List all deployment versions and run counts |
| `driftbase inspect <run_id>` | Deep-dive into a specific run's execution trace |
| `driftbase tail` | Stream recent runs with minimal output |
| `driftbase prune` | Delete runs based on retention criteria |
| `driftbase reset -v <version>` | Delete all runs for a deployment version |
| `driftbase export` | Export all runs to JSON for backup/archival |
| `driftbase import <file.json>` | Import runs from JSON (supports merge/replace modes) |
| `driftbase push` | Sync local runs to dashboard (Pro) |

### Visualization & Analysis

| Command | Description |
|---------|-------------|
| `driftbase chart -v <version>` | Display terminal charts for run metrics |
| `driftbase compare <v1> <v2> <v3>` | Multi-version batch comparison (tournament mode) |
| `driftbase explore` | Interactive terminal UI for exploring runs |
| `driftbase cost` | Analyze costs with detailed breakdown and forecasting |

### Command Groups

| Command | Description |
|---------|-------------|
| `driftbase baseline` | Manage baseline version (set, get, clear) |
| `driftbase bookmark` | Save and run commonly used queries |
| `driftbase git` | Git integration (status, compare, tag) |
| `driftbase plugin` | Manage plugins for custom checks and integrations |

### Command Aliases

| Alias | Equivalent | Description |
|-------|------------|-------------|
| `driftbase cat <run_id>` | `driftbase inspect` | Unix-style run inspection |
| `driftbase log` | `driftbase tail` | Unix-style log viewing |
| `driftbase clean` | `driftbase prune` | Unix-style cleanup |

### Utility Commands

| Command | Description |
|---------|-------------|
| `driftbase db-stats` | Print internal statistics (semantic clusters, etc.) |

### CLI Examples

#### Basic Drift Detection
```bash
# Compare two versions
driftbase diff v1.0 v2.0

# Compare last 20 runs against baseline
driftbase diff --last 20 --against v2.0

# Filter by environment
driftbase diff v2.0 v2.1 --environment production

# Filter by time and outcome
driftbase diff v1.0 v2.0 --since 24h --outcomes resolved,escalated

# Statistical significance testing
driftbase diff v1.0 v2.0 --show-stats --significance-level 0.05
```

#### Monitoring & Alerts
```bash
# Watch for drift in real-time
driftbase watch --against v2.0 --threshold 0.15

# Watch with desktop notifications
driftbase watch -a v2.0 --notify

# Monitor with custom interval
driftbase watch -a v2.0 -i 10 --min-runs 20
```

#### Data Exploration
```bash
# Quick status dashboard
driftbase status

# List runs with smart filters
driftbase runs -v v2.0 --today --errors-only
driftbase runs -v v2.0 --slow --format json

# Follow recent runs like tail -f
driftbase tail -f
driftbase tail -n 50 -v v2.0

# Deep dive into specific run
driftbase inspect <run_id>
driftbase cat <run_id>  # Alias
```

#### Visualization
```bash
# Display terminal charts
driftbase chart -v v2.0 -m latency
driftbase chart -v v2.0 -m outcomes
driftbase chart -v v2.0 -m tools

# Multi-version comparison
driftbase compare v1.0 v1.5 v2.0
driftbase compare v1.0 v1.5 v2.0 --matrix  # Tournament mode

# Interactive TUI
driftbase explore
```

#### Cost Analysis
```bash
# Overall cost summary
driftbase cost

# Cost for specific version
driftbase cost -v v2.0

# Group by provider/outcome/day
driftbase cost --groupby provider
driftbase cost --since 7d --groupby day

# Budget tracking
driftbase cost --budget 100 --since 30d
driftbase cost --format json
```

#### Baseline Management
```bash
# Set baseline for comparisons
driftbase baseline set v2.0

# Show current baseline
driftbase baseline get

# Clear baseline
driftbase baseline clear
```

#### Bookmarks
```bash
# Save frequently used queries
driftbase bookmark save prod-errors "runs -v production --errors-only"
driftbase bookmark save weekly-diff "diff v1.0 v2.0 --since 7d"

# List bookmarks
driftbase bookmark list

# Run saved bookmark
driftbase bookmark run prod-errors
```

#### Git Integration
```bash
# Show git repository status
driftbase git status

# Compare branches
driftbase git compare main feature-branch

# Enable git auto-tagging
driftbase git tag --enable
```

#### Plugin System
```bash
# Initialize plugin system
driftbase plugin init

# List installed plugins
driftbase plugin list

# Show plugin details
driftbase plugin info example

# Disable/enable plugins
driftbase plugin disable example
driftbase plugin enable example
```

#### Reports & Export
```bash
# Generate markdown report for PR comment
driftbase diff v2.0 v2.1 --format md --output pr_comment.md

# Generate EU AI Act compliance report
driftbase report v2.0 v2.1 --format html --template eu-ai-act --sign

# Export all production runs to JSON
driftbase export --output backup.json

# Import runs with merge strategy
driftbase import backup.json --merge
```

#### CI/CD Integration
```bash
# Fail on any drift (strict mode)
driftbase diff v1.0 v2.0 --json --fail-on-drift

# Fail above specific threshold
driftbase diff v1.0 v2.0 --json --exit-nonzero-above 0.15

# Combine with budget checks
driftbase cost -v v2.0 --budget 100 --format json
```

#### Data Cleanup
```bash
# Preview what would be deleted
driftbase prune --keep-last 5000 --dry-run

# Delete old runs
driftbase prune --older-than 30d
driftbase prune --version v1.0 --older-than 7d

# Quick cleanup with alias
driftbase clean --keep-last 1000
```

---

## Driftbase Pro (Team Sync)

Local SQLite is perfect for individual feature branches and CI pipelines. But when you need to:
- **Compare baselines across teammates** (Engineer A vs Engineer B)
- **Monitor production deployments** continuously
- **Share dashboards with stakeholders** (PMs, leadership)
- **Store long-term trend data** beyond local retention limits

...you need a shared source of truth.

**Driftbase Pro** provides:
- EU-hosted centralized dashboard (Frankfurt, GDPR-compliant)
- Team collaboration and version comparison
- Long-term trend analysis and alerting
- SSO/SAML integration for enterprise
- Dedicated support and SLA

To sync your local runs:

```bash
export DRIFTBASE_API_KEY="your_pro_key"
driftbase push
```

All sensitive context is stripped before upload — only structural metadata and hashed tool parameters are transmitted.

#### Connecting existing local data to the dashboard

If you’ve been using the SDK locally (runs, diffs, all in SQLite) and then subscribe to Pro, you can connect that existing data in one step:

1. Get your API key from the Driftbase dashboard after subscribing.
2. Set it once: `export DRIFTBASE_API_KEY='your_key'` (or add to `.env`).
3. Run **`driftbase push`** — this syncs **all** existing local runs to the dashboard. No need to re-run your agent.
4. After that, run `driftbase push` whenever you want to sync new runs (e.g. after a deploy or weekly). The dashboard will show runs, drift scores, and version comparisons.

Your local SQLite data stays on your machine; push only sends structural metadata (tool chains, token counts, latency, versions). Raw prompts and outputs are never sent.

[Learn more about Driftbase Pro →](https://driftbase.io/pro)

---

## Architecture & Design Philosophy

### Why Local-First?

1. **Privacy by design**: Sensitive customer data never leaves your infrastructure
2. **Zero latency**: No network calls in the hot path — just append to SQLite
3. **Works offline**: Full functionality in air-gapped environments
4. **Cost efficiency**: No per-run pricing — unlimited telemetry capture
5. **Compliance simplicity**: GDPR/NIS2/DORA obligations are easier when data stays local

### How It Works

```
┌─────────────────────────────────────────────────┐
│ 1. Your Agent Code                              │
│    @track(version="v2.1")                       │
│    def run_agent(query: str): ...              │
└─────────────────┬───────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────────┐
│ 2. Auto-Detection Layer                         │
│    Detects: LangChain / LangGraph / OpenAI      │
│    Captures: tools, tokens, latency, errors     │
└─────────────────┬───────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────────┐
│ 3. PII Scrubbing (optional)                     │
│    Regex-based redaction at the edge            │
│    Strips: emails, IBANs, IPs, phone numbers    │
└─────────────────┬───────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────────┐
│ 4. Structural Hashing                           │
│    Hash tool parameters and user inputs         │
│    Preserve semantic structure, not raw text    │
└─────────────────┬───────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────────┐
│ 5. Background Writer (bounded queue)            │
│    Non-blocking writes to SQLite (WAL mode)     │
│    Auto-pruning every 100 batches               │
│    Drop counter warns if queue saturates        │
└─────────────────┬───────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────────┐
│ 6. Local SQLite Database                        │
│    ~/.driftbase/runs.db                         │
│    Fallback: /tmp or cwd if home unavailable    │
└─────────────────────────────────────────────────┘

Later, in your terminal or CI:

┌─────────────────────────────────────────────────┐
│ driftbase diff v2.0 v2.1                        │
│   ↓                                             │
│ 1. Load runs from SQLite                        │
│ 2. Build behavioral fingerprints                │
│ 3. Compute KS test + bootstrap CI               │
│ 4. Generate root-cause hypotheses               │
│ 5. Render verdict with financial impact         │
└─────────────────────────────────────────────────┘
```

### Production Deployment Model

**Recommended architecture:**
1. Instrument your production containers with `pip install driftbase` (minimal deps)
2. Mount a persistent volume at `~/.driftbase/` or set `DRIFTBASE_DB_PATH`
3. Periodically export with `driftbase export` and archive to S3/GCS
4. On your laptop/CI, install `pip install 'driftbase[analyze]'` for statistical analysis
5. Diff against exported baselines or use `driftbase push` for Pro sync

This keeps heavy dependencies (numpy, scipy) out of production while maintaining full observability.

---

## Contributing

We welcome contributions! Areas of interest:
- Additional framework integrations (DSPy, Haystack, etc.)
- Additional drift dimensions (retrieval quality, prompt complexity, safety/alignment metrics)
- Alternative statistical tests (MMD, Wasserstein distance, permutation tests)
- Visualization improvements (terminal UI, HTML reports, interactive dashboards)

**Before submitting a PR:**
1. Run tests: `pytest tests/`
2. Lint and format: `ruff check src/ tests/` and `ruff format src/ tests/`
3. Check types: `mypy src/`

---

## FAQ

**Q: Does this slow down my agent?**
A: No. The `@track` decorator writes to an in-memory bounded queue and returns immediately. A background worker persists to SQLite asynchronously. Production overhead is <1ms per run.

**Q: Can I use this with streaming responses?**
A: Yes. Driftbase hooks into framework callbacks and captures the final aggregated result, including streaming token counts.

**Q: What if I exceed the retention limit?**
A: Oldest runs are automatically pruned when count exceeds `DRIFTBASE_LOCAL_RETENTION_LIMIT` (default: 100k). Pruning runs in the background every 100 batches.

**Q: Can I disable telemetry in tests?**
A: Yes. Use a separate database for tests (e.g. `export DRIFTBASE_DB_PATH=/tmp/driftbase-test.db`) or point to a throwaway SQLite file. All capture is local; no data is sent unless you run `driftbase push`.

**Q: How accurate is the cost calculation?**
A: Very accurate. We read token counts directly from LLM responses and multiply by your configured rates (`DRIFTBASE_RATE_PROMPT_1M`, `DRIFTBASE_RATE_COMPLETION_1M`). Default rates are OpenAI list prices.

**Q: Does this work with Azure OpenAI?**
A: Yes. Any OpenAI-compatible client is supported (Azure, Anthropic, Groq, local LLMs).

**Q: Can I self-host the Pro dashboard?**
A: Not yet. Self-hosted enterprise edition is on the roadmap for Q2 2026. Email pro@driftbase.io for early access.

---

## License

Apache License 2.0. See [LICENSE](LICENSE) for details.

---

## Community & Support

- **Documentation:** [docs.driftbase.io](https://docs.driftbase.io)
- **GitHub Issues:** [github.com/driftbase/driftbase-python/issues](https://github.com/driftbase/driftbase-python/issues)
- **Email:** support@driftbase.io
- **Pro inquiries:** pro@driftbase.io

**Built with 🇪🇺 in Europe. Data sovereignty by default.**
