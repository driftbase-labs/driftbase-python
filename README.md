# Driftbase

**Behavioral drift monitoring for AI agents: track runs locally, compare versions, get a drift score.**

When you ship a new prompt, model, or tool set, agent behavior can change in subtle ways. Driftbase records each run (tool names, latency, outcome) in a local SQLite DB and lets you diff any two versions so you see a numeric drift score and per-dimension breakdown before or after deploy.

---

## Quickstart

**1. Install**

```bash
pip install driftbase[local]
```

**2. Add the decorator**

```python
# my_agent.py
from driftbase import track

@track(version="v1.0", environment="production")
def my_agent(user_input: str) -> str:
    # your agent logic
    return "done"
```

**3. Run your agent**

Generate some runs for at least two versions (e.g. change code and use `version="v2.0"` for new runs).

```bash
python -c "from my_agent import my_agent; my_agent('hello')"
# Run a few more times, then switch to v2.0 and run again.
```

**4. Run diff**

```bash
driftbase diff v1.0 v2.0
```

**5. See output**

You get a threshold panel, a metrics table, tool frequency diff, optional sequence shifts, and a root-cause hypothesis. Example (with comments indicating where rich applies color):

```
# Panel: red border if above threshold, green if within
┌─ ▲ ABOVE THRESHOLD ─────────────────────────────────────────────────┐
│ Drift score 0.34 is above threshold 0.20. Consider investigating...   │
└──────────────────────────────────────────────────────────────────────┘

# Table: Drift — v1.0 → v2.0
┌─────────────────┬──────────┬─────────┬────────┐
│ Metric          │ Baseline │ Current │ Delta  │
├─────────────────┼──────────┼─────────┼────────┤
│ Overall drift   │     0.00 │    0.34 │  +0.34 │  # red if ≥ threshold
│ Decision drift  │     0.00 │    0.22 │  +0.22 │
│ Latency drift   │     0.00 │    0.18 │  +0.18 │
│ Error drift     │     0.00 │    0.00 │  +0.00 │
└─────────────────┴──────────┴─────────┴────────┘

# Tool call frequency diff (top 20 tools, Δ % in green/red/dim)
# Optional: Top 3 sequence shifts, Root cause hypothesis panel
# Footer: Runs: v1.0 (n=50) → v2.0 (n=50) · No data left your machine
```

---

## How it works

Runs are written to SQLite in a background thread so your app is not blocked. When you run `driftbase diff`, the CLI loads runs for the two versions, builds a behavioral fingerprint for each (tool distributions, latency percentiles, error rate), and computes a divergence score between them. The score and per-dimension deltas tell you how much behavior changed.

---

## Privacy

- **Captured and stored locally:** Tool call names and order, latency, token counts, error/retry counts, outcome label (e.g. resolved/error). No raw user or model content.
- **Hashed then discarded:** A hash of the task input and a hash of the output structure are stored; the original text is not.
- **Never stored or read:** Raw user messages, raw agent output, system prompts, API keys, user identifiers.

Use `driftbase inspect --run last` to see the exact breakdown for any run.

---

## CLI reference

| Command | Description | Example |
|---------|-------------|--------|
| `versions` | List deployment versions and run counts | `driftbase versions` |
| `diff` | Compare two versions; optional last N vs baseline | `driftbase diff v1.0 v2.0` or `driftbase diff v1.0 local --last 20` |
| `inspect` | Show what was captured/dropped for a run | `driftbase inspect --run last` |
| `report` | Generate markdown/JSON/HTML drift report | `driftbase report v1.0 v2.0 -o report.md` |
| `watch` | Live drift monitor against a baseline | `driftbase watch --against v1.0` |
| `push` | Send local runs to Driftbase platform API | `driftbase push` (uses `DRIFTBASE_API_URL`, `DRIFTBASE_API_KEY`) |

---

## Frameworks supported

The `@track()` decorator auto-detects and captures from:

- **LangChain** — tool calls via callbacks
- **LangGraph** — same as LangChain
- **LlamaIndex** — function_call and callback events
- **OpenAI** — `chat.completions.create` tool_calls and usage
- **Generic** — any callable; times the call and optionally parses tool_calls from the return value

---

## Docs and product

- [Documentation](https://docs.driftbase.io)
- [Driftbase](https://driftbase.io)
