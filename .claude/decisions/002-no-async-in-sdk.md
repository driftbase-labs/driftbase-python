# ADR-002: No Async/Await in SDK Storage

**Status:** Accepted

**Date:** 2025-01

**Context:**

Python's async ecosystem is mature. Many libraries offer both sync and async APIs. The question is whether driftbase SDK should use async storage.

**Decision:**

All storage operations in `backends/` and `local/` are **synchronous only**. No async/await.

**Rationale:**

1. **SQLite is synchronous** — SQLModel/SQLAlchemy use synchronous drivers. `aiosqlite` exists but is incompatible with SQLModel.

2. **No parallelism in SQLite** — SQLite has a global write lock. Async doesn't improve throughput.

3. **Complexity cost** — async/await infects the entire call stack. Every function becomes async. Testing becomes harder.

4. **Local-first design** — The SDK writes to local disk, not remote API. Latency is ~1ms. Async overhead exceeds savings.

5. **User code simplicity** — Developers can use @track on sync or async functions. The decorator handles both. But if storage is async, users must await internal calls.

**Consequences:**

- All backend methods are sync: `write_run()`, `get_runs()`, etc.
- No asyncio imports in `backends/` or `local/` modules
- CLI commands are sync (Click doesn't support async commands well)

**Where async might be used later:**

- `sdk/push.py` — Pushing to Pro tier API over HTTP (not local)
- Keep async contained to that one module

**Alternatives Considered:**

1. **Use aiosqlite** — Rejected because it requires rewriting all SQLModel queries to raw SQL.

2. **Wrap sync calls in asyncio.to_thread()** — Rejected because it adds overhead for no benefit (disk I/O is the bottleneck, not Python).

3. **Abstract interface supports both** — Rejected because it doubles API surface and testing burden.

**References:**

- https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html (SQLAlchemy async support—not compatible with SQLModel)
