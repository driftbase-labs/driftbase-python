# v0.11 Migration Guide

## Overview

Driftbase v0.11 introduces a **schema split**: the single `agent_runs_local` table is replaced with two tables (`runs_raw` + `runs_features`).

This migration:
- ✅ **Preserves all data** — no data loss
- ✅ **Creates automatic backup** — `.pre-v0.11.backup` file
- ✅ **Is idempotent** — safe to re-run
- ✅ **Is atomic** — transaction-based, all-or-nothing

**Estimated time:** <1 second for databases up to 100K runs.

## Pre-Migration Checklist

Before upgrading to v0.11:

1. **Backup your database** (manual, in addition to automatic backup):
   ```bash
   cp ~/.driftbase/runs.db ~/.driftbase/runs.db.manual-backup
   ```

2. **Check disk space**: Migration requires ~2x database size temporarily (original + backup).

3. **Stop all processes** using Driftbase (connectors, analysis scripts, etc).

4. **Note current version**:
   ```bash
   pip show driftbase | grep Version
   ```

5. **(Optional) Export runs** for external backup:
   ```bash
   driftbase export --format json > runs-backup.jsonl
   ```

## Migration Methods

### Method 1: Automatic (Recommended)

Upgrade and let backend initialization handle migration:

```bash
# Upgrade to v0.11+
pip install --upgrade driftbase

# Trigger migration by initializing backend
python -c "from driftbase import get_backend; get_backend()"
```

**Output:**
```
⚠ Database needs v0.11 schema migration
  Creating backup: ~/.driftbase/runs.db.pre-v0.11.backup
  Migrating 5,432 rows to new schema...
✓ Migrated 5,432 rows to runs_raw
✓ Migrated 5,432 rows to runs_features
✓ Backup saved at: /Users/you/.driftbase/runs.db.pre-v0.11.backup
```

### Method 2: CLI (Explicit Control)

Use the `driftbase migrate` command:

```bash
# Check if migration is needed
driftbase migrate --status

# Preview migration (no changes)
driftbase migrate --dry-run

# Run migration
driftbase migrate
```

### Method 3: Programmatic

For CI/CD pipelines or custom scripts:

```python
from pathlib import Path
from driftbase.backends.migrations.v0_11_schema_split import migrate, needs_migration
from driftbase import get_backend

backend = get_backend()
db_path = Path("~/.driftbase/runs.db").expanduser()

if needs_migration(backend._engine):
    print("Running migration...")
    result = migrate(backend._engine, db_path, dry_run=False)
    print(f"Migrated {result.rows_copied} rows")
    print(f"Backup: {result.backup_path}")
else:
    print("Already migrated")
```

## Post-Migration Verification

After migration completes:

### 1. Check Migration Status

```bash
driftbase migrate --status
```

**Expected output:**
```
Migration Status
┏━━━━━━━━━━━━━━━━━━┳━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Metric           ┃ Count ┃ Details                         ┃
┡━━━━━━━━━━━━━━━━━━╇━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ Schema version   │ v0.11 │ runs_raw + runs_features        │
│ Total runs       │ 5,432 │                                 │
│ Total features   │ 5,432 │                                 │
│   ├─ Derived     │     0 │ Computed by derive_features()   │
│   └─ Migrated    │ 5,432 │ Copied from agent_runs_local    │
└──────────────────┴───────┴─────────────────────────────────┘
```

### 2. Verify Data Integrity

```bash
# List versions (should match pre-migration)
driftbase versions

# Check runs for a specific version
driftbase runs -v v1.0 --limit 10

# Run a drift check (should work as before)
driftbase diff v1.0 v1.1
```

### 3. Check Backup File

```bash
ls -lh ~/.driftbase/runs.db.pre-v0.11.backup
```

Should exist and be similar size to original database.

### 4. Run Test Suite (If Applicable)

If you have custom tests using Driftbase:

```bash
pytest tests/  # or your test command
```

## Rollback Procedure

If migration causes issues, rollback to v0.10:

### Step 1: Stop All Processes

Stop any scripts, connectors, or applications using Driftbase.

### Step 2: Restore Backup

```bash
# Replace current DB with backup
cp ~/.driftbase/runs.db.pre-v0.11.backup ~/.driftbase/runs.db

# Verify backup is restored
ls -lh ~/.driftbase/runs.db
```

### Step 3: Downgrade Driftbase

```bash
# Downgrade to last v0.10 release
pip install driftbase==0.10.3
```

### Step 4: Verify Rollback

```bash
# Check version
pip show driftbase | grep Version

# Test database
driftbase versions
driftbase runs -v v1.0 --limit 5
```

### Step 5: Report Issue

If rollback was necessary, please report:

1. Driftbase version: `pip show driftbase`
2. Python version: `python --version`
3. Database size: `ls -lh ~/.driftbase/runs.db`
4. Error logs: `driftbase doctor`
5. Migration output: Full output from migration command

Open an issue at: https://github.com/anthropics/driftbase-python/issues

## Troubleshooting

### "Migration failed: database is locked"

**Cause:** Another process is using the database.

**Fix:**
```bash
# Check for running processes
ps aux | grep driftbase

# Kill any driftbase processes
pkill -f driftbase

# Retry migration
python -c "from driftbase import get_backend; get_backend()"
```

### "Backup already exists"

**Cause:** Migration was previously run or attempted.

**Fix:** Migration automatically adds timestamp suffix for multiple backups:
```
~/.driftbase/runs.db.pre-v0.11.backup           # First backup
~/.driftbase/runs.db.pre-v0.11.backup.20250421_143022  # Second
```

No action needed — migration will proceed.

### "Out of disk space"

**Cause:** Insufficient disk space for backup + new tables.

**Fix:**
```bash
# Check available space
df -h ~/.driftbase

# Free up space or move DB to larger drive
mv ~/.driftbase/runs.db /path/to/larger/drive/runs.db
export DRIFTBASE_DB_PATH=/path/to/larger/drive/runs.db

# Retry migration
python -c "from driftbase import get_backend; get_backend()"
```

### "Foreign key constraint failed"

**Cause:** Rare SQLite foreign key enforcement issue.

**Fix:**
```bash
# Restore from backup
cp ~/.driftbase/runs.db.pre-v0.11.backup ~/.driftbase/runs.db

# Disable foreign keys temporarily
export SQLITE_DISABLE_FOREIGN_KEYS=1

# Retry migration
python -c "from driftbase import get_backend; get_backend()"
```

### "Schema version mismatch"

**Cause:** Partially completed migration or database corruption.

**Fix:**
```bash
# Check migration status
driftbase migrate --status

# If shows mixed state, restore backup and retry
cp ~/.driftbase/runs.db.pre-v0.11.backup ~/.driftbase/runs.db
python -c "from driftbase import get_backend; get_backend()"
```

## Performance Expectations

### Migration Time

| Database Size | Migration Time | Backup Time |
|--------------|----------------|-------------|
| 1K runs      | <100ms         | <10ms       |
| 10K runs     | ~500ms         | ~50ms       |
| 100K runs    | ~3s            | ~300ms      |
| 1M runs      | ~30s           | ~3s         |

### Disk Space

Migration requires:
- Original DB size (existing)
- Backup DB size (~100% of original)
- New tables (~100% of original)

**Total during migration:** ~200% of original size
**After migration:** ~150% (original + backup, can delete backup after verification)

### Post-Migration Performance

- **Reads:** Same as v0.10 (LEFT JOIN is fast with indexes)
- **Writes:** Slightly faster (smaller individual inserts)
- **Lazy derivation:** First read of new run adds 1-5ms, subsequent reads have no overhead

## Best Practices

### 1. Migrate During Low-Traffic Window

Schedule migration when minimal or no ingestion is happening:
- Stop connectors temporarily
- Pause decorator-based ingestion
- Wait for existing analysis to complete

### 2. Verify Backups Work

After migration, test backup restoration in a non-production environment:

```bash
# Create test directory
mkdir /tmp/driftbase-test

# Copy backup to test location
cp ~/.driftbase/runs.db.pre-v0.11.backup /tmp/driftbase-test/runs.db

# Test with temporary DB path
DRIFTBASE_DB_PATH=/tmp/driftbase-test/runs.db driftbase versions
```

### 3. Keep Backups

Don't delete `.pre-v0.11.backup` files until:
- ✅ Post-migration verification passes
- ✅ At least one full analysis cycle completes
- ✅ One week of production use without issues

### 4. Monitor First Week

After migration, watch for:
- Unexpected drift score changes
- Missing or incorrect feature values
- Performance regressions
- Disk space usage

Run weekly:
```bash
driftbase migrate --status  # Check for missing/stale features
driftbase doctor            # Health check
```

### 5. Backfill Missing Features

If migration status shows missing features (rare edge case):

```bash
driftbase migrate --backfill
```

## FAQ

**Q: Will my drift scores change after migration?**

A: No. Migration preserves all computed features, so fingerprints and drift scores remain identical.

**Q: Do I need to re-ingest data?**

A: No. Migration copies all data automatically.

**Q: Can I continue using v0.10 after migration?**

A: No. Once migrated to v0.11 schema, you must use v0.11+. Rollback requires restoring the backup.

**Q: What happens to the old `agent_runs_local` table?**

A: It remains in the database as a read-only safety net. Future versions may add a cleanup command.

**Q: Can I delete the backup after migration?**

A: Yes, but wait at least one week and verify everything works correctly first.

**Q: Does migration affect cloud sync (if using)?**

A: No. Local DB migration is independent of cloud features.

**Q: How do I migrate multiple databases?**

A: Run migration for each database separately:
```bash
DRIFTBASE_DB_PATH=/path/to/db1.db python -c "from driftbase import get_backend; get_backend()"
DRIFTBASE_DB_PATH=/path/to/db2.db python -c "from driftbase import get_backend; get_backend()"
```

## See Also

- [Schema v2 Documentation](schema-v2.md) — Two-table design details
- [Version Resolution](version-resolution.md) — How versions are determined
- [CHANGELOG](../CHANGELOG.md) — Full v0.11 release notes
