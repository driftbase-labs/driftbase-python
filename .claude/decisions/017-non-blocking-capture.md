# 017 — Non-Blocking Capture Design

**Status:** Accepted
**Date:** 2026-03-30
**Files affected:** `local/local_store.py`, `sdk/track.py`

---

## Decision

All run capture is non-blocking. The `@track` decorator enqueues the run
payload to an in-memory queue and returns immediately. A background thread
drains the queue and writes to SQLite. The instrumented function is never
blocked by storage operations.

## Why non-blocking is non-negotiable

`@track` wraps production agent code. Any latency added to the instrumented
function is latency added to the user-facing response. Even a 10ms SQLite
write in the hot path is unacceptable for a tool positioned as having
"zero production performance impact."

The background writer decouples the capture latency from the agent execution
latency completely. From the agent's perspective, `@track` is a function
wrapper that adds ~0.1ms of queue enqueue overhead.

## Why in-memory queue, not disk queue

A disk queue (e.g. writing to a log file first) would require a separate
read step when draining. In-memory queue draining is O(1) per item and
requires no additional I/O.

The risk of in-memory queue is data loss on process crash — unwritten runs
are lost. This is acceptable for behavioral monitoring data:
- Individual run loss is acceptable; aggregate patterns are what matter
- A process crash usually means the agent also crashed — the run data is suspect anyway
- The queue is bounded (DRIFTBASE_MAX_QUEUE_SIZE, default 10,000) to prevent
  memory exhaustion

## Why the queue is bounded

An unbounded queue can exhaust memory if the background writer falls behind
(e.g. disk is slow, database is locked). The bounded queue drops the oldest
runs (not the newest) when capacity is exceeded, logging a warning every
100 drops.

Dropping oldest runs is correct: the most recent behavioral data is most
valuable for detecting current drift.

## Why background thread, not asyncio

The SDK must work in both sync and async agent codebases. Asyncio would
require the SDK to manage an event loop, which conflicts with frameworks
that already have their own event loop (LangChain, LangGraph, FastAPI).

A background thread is framework-agnostic — it runs in its own thread
regardless of whether the calling code is sync or async.

## Why budget checking runs in the background thread

Budget breach detection (rolling window comparison against limits) runs
after each batch write in the background thread, not in the instrumented
function. This ensures:

1. No latency added to the agent execution
2. Budget config is already persisted before breach detection reads it
3. Breach events are written atomically with the run that triggered them

The consequence: budget breach detection lags by one batch (typically
1-10 runs, configurable). For a monitoring feature this is acceptable —
immediate detection is Pro tier (real-time monitoring).

## Why SQLite WAL mode

Write-Ahead Logging (WAL mode) allows concurrent reads and writes without
blocking. In production, multiple processes may be reading the database
(CLI commands, multiple agent processes) while the background writer is
writing. WAL mode ensures reads never block writes and vice versa.

## Error handling in the background thread

Any exception in the background thread is logged to `errors.log` and the
thread continues. The thread never raises to the calling code. A storage
failure silently drops the run rather than crashing the agent.

This is the correct tradeoff: the agent's availability is more important
than telemetry completeness.

## Alternative considered

**Synchronous write in the decorator (simplest).**
Rejected — adds SQLite write latency to every agent invocation. Unacceptable
for production deployment.

**Write to a local file first, background thread reads file.**
Rejected — adds disk I/O on both the write and read paths. Slower than
in-memory queue with no benefit for our use case.

**Use Redis or RabbitMQ as the queue.**
Rejected — external service dependency violates the local-first, zero-config
principle. Developers should not need to run Redis to use Driftbase.
