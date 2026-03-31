# ADR-003: SQLite Only (No Postgres) in Free SDK

**Status:** Accepted

**Date:** 2025-01

**Context:**

Many analytics tools use Postgres for better concurrency and querying. Should driftbase free SDK support Postgres as an alternative backend?

**Decision:**

Free SDK uses **SQLite only**. No Postgres support in `driftbase` package.

**Rationale:**

1. **Local-first philosophy** — Free SDK stores data on developer's laptop. No server required.

2. **Zero-config experience** — SQLite "just works":
   ```python
   @track(agent_id="my-agent", version="v1.0")
   def agent_fn(input):
       # Runs are automatically saved to ~/.driftbase/driftbase.db
       return result
   ```

   Postgres requires:
   - Installing and running Postgres server
   - Creating database
   - Managing connection strings
   - Handling network failures
   - Schema migrations across versions

3. **Deployment complexity** — SQLite is a single file. Backup = `cp driftbase.db driftbase.backup`. Postgres requires pg_dump, connection pooling, etc.

4. **Performance sufficient** — Free SDK is pre-production analysis. Queries are small (typically < 1000 runs per diff). SQLite handles this easily.

5. **Abstraction cost** — Supporting both SQLite and Postgres means:
   - Abstract backend interface (done, but)
   - Testing both backends (doubles test matrix)
   - Postgres-specific tuning (connection pools, query optimization)
   - Leaking Postgres complexity into free tier

**Consequences:**

- `backends/sqlite.py` is the only backend in this repo
- No Postgres dependencies in `pyproject.toml`
- Pro tier can use Postgres (separate codebase, not this repo)

**When would we add Postgres?**

Pro tier with:
- Multi-user access (team dashboards)
- Large-scale monitoring (10,000+ runs/day)
- Cross-agent analytics (compare 50 agents)

For free SDK, SQLite is sufficient.

**Alternatives Considered:**

1. **Support both via abstract backend** — Rejected because 99% of free users would use SQLite. Postgres support adds complexity for 1% of users.

2. **Use Postgres by default** — Rejected because it destroys zero-config experience.

3. **Use DuckDB instead of SQLite** — Considered. DuckDB has better analytics performance. Rejected because:
   - SQLModel doesn't support DuckDB
   - Requires rewriting all queries
   - DuckDB is less mature (SQLite has 20+ years of battle-testing)

**References:**

- https://www.sqlite.org/whentouse.html (When to use SQLite vs client/server DB)
