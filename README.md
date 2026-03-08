# Driftbase Python SDK

**Behavioral drift monitoring for AI agents.** Track agent runs locally, compare versions, and detect when behavior changes—with zero external services and no cloud required.

## Features

- **Local-first** — All data stays on your machine. SQLite by default (`~/.driftbase/runs.db`). Nothing is sent to any external server.
- **Zero-friction `@track()`** — One decorator on your agent entrypoint. Auto-detects LangGraph, LangChain, LlamaIndex, OpenAI, or generic callables; captures tool calls, latency, and outcome in a background thread so it doesn’t block your app.
- **CLI** — List versions, diff two deployments, inspect what was captured (privacy audit), generate markdown/JSON/HTML reports, and watch for drift in real time.
- **Privacy-aware** — Raw user messages and agent output are not stored. Only hashes and metadata (tool names, latency, token counts, etc.) are written. Use `driftbase inspect` to see exactly what was captured and what was dropped.

## Install

```bash
pip install driftbase
```

For full CLI support (diff, report, watch) with rich output and optional embeddings:

```bash
pip install driftbase[local]
```

Requires **Python 3.9+**.

## Quick start

Decorate your agent so runs are recorded locally:

```python
from driftbase import track

@track(version="v1.0", environment="production")
def my_agent(user_input: str) -> str:
    # Your agent logic; tool calls, latency, and outcome are captured automatically.
    ...
    return response
```

Then use the CLI to list versions, compare behavior, and inspect runs:

```bash
driftbase versions
driftbase diff v1.0 v2.0
driftbase inspect --run last
driftbase report v1.0 v2.0 -o report.md
```

## CLI commands

| Command | Description |
|--------|-------------|
| `driftbase versions` | List deployment versions and run counts from the local DB |
| `driftbase diff <baseline> <current>` | Compare two versions (e.g. `v1.0` vs `v2.0` or `v1.0` vs `local`) |
| `driftbase inspect --run <id\|last>` | Show what was captured, hashed, and dropped for a run (verifiable privacy) |
| `driftbase report <baseline> <current>` | Generate a shareable drift report (markdown, JSON, or HTML) |
| `driftbase watch --against <version>` | Live drift monitor: poll and compare recent runs against a baseline |

Examples:

```bash
# Diff last 20 runs vs a tagged version
driftbase diff v1.0 local --last 20

# Inspect the most recent run, export as JSON
driftbase inspect -r last -o run.json

# Report with custom threshold and environment
driftbase report v1.0 v2.0 -f markdown -o report.md -t 0.15 -e staging
```

## What gets stored (and what doesn’t)

- **Stored locally:** Tool call names and order, latency, token usage, error/retry counts, decision outcome, and *hashes* of inputs/outputs (not the content).
- **Never stored:** Raw user messages, raw agent output, system prompts, API keys, user identifiers.

Run `driftbase inspect --run last` to see the exact breakdown for any run. Nothing is sent to an external server.

## Configuration

All configuration is via environment variables (no `.env` file required). Sensible defaults work out of the box.

| Variable | Default | Description |
|----------|---------|-------------|
| `DRIFTBASE_DB_PATH` | `~/.driftbase/runs.db` | Path to the SQLite database |
| `DRIFTBASE_ENVIRONMENT` | `production` | Environment label for `@track(environment=...)` |
| `DRIFTBASE_SESSION_ID` | (empty) | Optional session ID for grouping runs |
| `DRIFTBASE_OUTPUT_COLOR` | `1` | Set to `0` to disable colored CLI output |
| `DRIFTBASE_MIN_SAMPLES` | `10` | Minimum runs before computing a fingerprint |
| `DRIFTBASE_BASELINE_DAYS` | `7` | Days for temporal baseline window |
| `DRIFTBASE_CURRENT_HOURS` | `24` | Hours for current window in temporal drift |

Errors from the tracking layer are appended to `~/.driftbase/errors.log` (or the same directory as `DRIFTBASE_DB_PATH`).

## License

See [LICENSE](LICENSE) in this repository.
