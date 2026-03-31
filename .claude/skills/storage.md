# Storage Skill

**Read this skill before adding tables, modifying schemas, or touching backends/.**

## Storage Backend Architecture

Driftbase uses a **factory pattern** with abstract base + concrete implementations:

```
backends/
  base.py          — StorageBackend abstract class
  sqlite.py        — SQLite implementation (only one in this repo)
  factory.py       — get_backend() returns singleton
```

**Never use async DB calls. All storage in this repo is synchronous SQLite.**

## The SQLite Backend

### Core Tables

```python
# agent_runs_local — raw run records
class AgentRunLocal(SQLModel, table=True):
    id: str (PK)
    session_id: str
    deployment_version: str
    environment: str
    started_at: datetime
    completed_at: datetime
    task_input_hash: str
    tool_sequence: str  # JSON list
    tool_call_count: int
    output_length: int
    output_structure_hash: str
    latency_ms: int
    error_count: int
    retry_count: int
    semantic_cluster: str
    prompt_tokens: int | None
    completion_tokens: int | None
    raw_prompt: str
    raw_output: str
    # Behavioral metrics
    loop_count: int
    tool_call_sequence: str  # JSON list
    time_to_first_tool_ms: int
    verbosity_ratio: float
    sensitivity: str | None

# calibration_cache — cached calibration results per agent+version
class CalibrationCache(SQLModel, table=True):
    id: int (PK)
    cache_key: str (unique index)  # "{baseline_version}:{eval_version}:{use_case}:{sensitivity}"
    calibrated_weights: str  # JSON
    thresholds: str  # JSON
    composite_thresholds: str  # JSON
    calibration_method: str
    baseline_n: int
    run_count_at_calibration: int
    reliability_multipliers: str  # JSON
    confidence: float
    computed_at: datetime

# budget_configs — persisted budget definitions
class BudgetConfig(SQLModel, table=True):
    id: int (PK)
    agent_id: str (index)
    version: str (index)
    config: str  # JSON serialized BudgetConfig
    source: str  # "decorator" | "config_file"
    created_at: datetime

# budget_breaches — breach events with rolling average values
class BudgetBreach(SQLModel, table=True):
    id: int (PK)
    agent_id: str (index)
    version: str (index)
    dimension: str
    budget_key: str
    limit_value: float
    actual_value: float
    direction: str  # "above" | "below"
    run_count: int
    breached_at: datetime

# change_events — recorded change events per agent+version
class ChangeEvent(SQLModel, table=True):
    id: int (PK)
    agent_id: str (index)
    version: str (index)
    change_type: str  # "model_version" | "prompt_hash" | "rag_snapshot" | "tool_version" | "custom"
    previous: str | None
    current: str
    recorded_at: datetime
    source: str  # "decorator" | "cli" | "auto"

# deploy_outcomes — labeled outcomes for weight learning
class DeployOutcome(SQLModel, table=True):
    id: int (PK)
    agent_id: str (index)
    version: str (index)
    outcome: str  # "good" | "bad"
    labeled_by: str  # "user" | "auto"
    note: str
    labeled_at: datetime

# learned_weights_cache — cached learned weights from labeled outcomes
class LearnedWeightsCache(SQLModel, table=True):
    id: int (PK)
    agent_id: str (unique index)
    weights: str  # JSON
    weights_metadata: str  # JSON
    n_total: int
    computed_at: datetime

# significance_thresholds — adaptive thresholds from power analysis
class SignificanceThreshold(SQLModel, table=True):
    id: int (PK)
    agent_id: str (index)
    version: str (index)
    use_case: str
    effect_size: float
    min_runs_overall: int
    min_runs_per_dim: str  # JSON
    limiting_dim: str
    computed_at: datetime
    baseline_n_at_computation: int

# deploy_events — schema-only, deferred UX
class DeployEvent(SQLModel, table=True):
    id: int (PK)
    agent_id: str
    version: str
    environment: str
    deployed_at: datetime
    triggered_by: str
```

## Schema Migration Pattern

**Never change the fingerprint schema without a migration note.**

Migrations are handled in `sqlite.py:_migrate_schema()`:

```python
def _migrate_schema(engine: Any) -> None:
    """Add new columns if missing (existing DBs)."""
    try:
        with engine.connect() as conn:
            r = conn.execute(text("PRAGMA table_info(agent_runs_local)"))
            columns = {row[1] for row in r.fetchall()}

            if "new_column" not in columns:
                conn.execute(text(
                    "ALTER TABLE agent_runs_local ADD COLUMN new_column INTEGER DEFAULT 0"
                ))
                conn.commit()
                logger.info("Migrated schema: added new_column to agent_runs_local")
    except Exception as e:
        logger.warning(f"Schema migration failed: {e}")
```

**Migration rules:**
1. Use `ALTER TABLE ADD COLUMN` with sensible defaults
2. Never drop columns (breaks old CLIs)
3. Never rename columns (breaks old CLIs)
4. Always wrap in try/except and log
5. Test migration with a pre-existing database file

## Factory Pattern

```python
from driftbase.backends.factory import get_backend

backend = get_backend()  # Returns singleton SQLiteBackend instance
```

The factory reads `DRIFTBASE_DB_PATH` from config and returns a cached backend instance.

**Never instantiate backends directly. Always use `get_backend()`.**

## StorageBackend Interface

Key methods all backends must implement:

```python
class StorageBackend(ABC):
    @abstractmethod
    def write_run(self, run: AgentRun) -> str:
        """Write a single run, return ID."""

    @abstractmethod
    def get_runs(
        self,
        deployment_version: str | None = None,
        environment: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Query runs with optional filters."""

    @abstractmethod
    def get_last_run(self) -> dict[str, Any] | None:
        """Get most recent run."""

    @abstractmethod
    def get_calibration_cache(self, cache_key: str) -> dict | None:
        """Retrieve cached calibration."""

    @abstractmethod
    def set_calibration_cache(self, cache_key: str, data: dict) -> None:
        """Store calibration result."""
```

## Adding a New Table

1. **Define SQLModel class** in `sqlite.py`:
   ```python
   class MyNewTable(SQLModel, table=True):
       __tablename__ = "my_new_table"
       id: int | None = Field(default=None, primary_key=True)
       agent_id: str = Field(index=True)
       data: str = "{}"  # JSON
       created_at: datetime = Field(default_factory=datetime.utcnow)
   ```

2. **Add to metadata** in `SQLiteBackend.__init__()`:
   ```python
   SQLModel.metadata.create_all(self.engine)  # Already creates all tables
   ```

3. **Add accessor methods** to `StorageBackend` base class and `SQLiteBackend`:
   ```python
   # In base.py
   @abstractmethod
   def get_my_data(self, agent_id: str) -> dict | None:
       pass

   # In sqlite.py
   def get_my_data(self, agent_id: str) -> dict | None:
       with Session(self.engine) as session:
           result = session.exec(
               select(MyNewTable).where(MyNewTable.agent_id == agent_id)
           ).first()
           return result.model_dump() if result else None
   ```

4. **Update tests** to verify CRUD operations on new table

5. **Document in CLAUDE.md** under "Database tables" section

## JSON Serialization Pattern

For dict/list fields, use JSON strings:

```python
# Writing
tool_sequence = json.dumps(["tool1", "tool2"])
run.tool_sequence = tool_sequence

# Reading
tools = json.loads(run.tool_sequence)
```

**Never store raw dicts in SQLite. Always JSON-serialize first.**

## Query Patterns

### Simple filter
```python
with Session(engine) as session:
    runs = session.exec(
        select(AgentRunLocal)
        .where(AgentRunLocal.deployment_version == version)
        .order_by(AgentRunLocal.started_at.desc())
        .limit(100)
    ).all()
```

### Aggregate
```python
with Session(engine) as session:
    count = session.exec(
        select(func.count(AgentRunLocal.id))
        .where(AgentRunLocal.deployment_version == version)
    ).one()
```

### Multiple filters
```python
stmt = select(AgentRunLocal)
if version:
    stmt = stmt.where(AgentRunLocal.deployment_version == version)
if environment:
    stmt = stmt.where(AgentRunLocal.environment == environment)
results = session.exec(stmt).all()
```

## Database Path Resolution

Default: `~/.driftbase/driftbase.db`

Override with env var: `DRIFTBASE_DB_PATH=/custom/path/db.sqlite`

The `_ensure_dir()` helper creates parent directories automatically.

## Error Handling

Storage operations should **degrade silently** and log, never crash the CLI:

```python
def get_runs(self, deployment_version: str) -> list[dict]:
    try:
        with Session(self.engine) as session:
            # ... query
            return results
    except Exception as e:
        logger.error(f"Failed to get runs: {e}")
        return []  # Return empty, don't raise
```

**Exception: `write_run()` should raise on failure** (SDK needs to know if tracking failed).

## Testing Storage

No async tests needed. All storage is synchronous.

Test pattern:
```python
def test_write_and_read_run(tmp_path):
    db_path = str(tmp_path / "test.db")
    backend = SQLiteBackend(db_path)

    run = AgentRun(
        session_id="test",
        deployment_version="v1.0",
        # ... fields
    )
    run_id = backend.write_run(run)

    fetched = backend.get_runs(deployment_version="v1.0")
    assert len(fetched) == 1
    assert fetched[0]["id"] == run_id
```

Use `tmp_path` fixture for isolated test databases.

## Never Do

- Don't add cloud API calls or external HTTP requests (those go in `sdk/push.py` only)
- Don't use async DB calls (SQLModel in this repo is synchronous)
- Don't touch `web/` directory (separate concern)
- Don't hardcode database paths (always use config)
- Don't add dependencies outside `pyproject.toml` extras

## Summary

- Factory pattern: always use `get_backend()`
- Synchronous SQLite only, no async
- Migrations via `_migrate_schema()` with `ALTER TABLE ADD COLUMN`
- JSON strings for complex types
- Degrade gracefully on read errors, raise on write errors
- Test with `tmp_path` fixture for isolation
