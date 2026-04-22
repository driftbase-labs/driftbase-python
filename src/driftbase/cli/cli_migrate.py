"""
Migrate command: Schema migration management and feature backfill.
"""

from __future__ import annotations

from pathlib import Path

import click
from rich.markup import escape
from rich.progress import BarColumn, Progress, TaskID, TextColumn
from sqlalchemy import text
from sqlmodel import Session

from driftbase.backends.factory import get_backend
from driftbase.backends.migrations.v0_11_schema_split import (
    MigrationError,
    migrate,
    needs_migration,
)
from driftbase.backends.sqlite import FEATURE_SCHEMA_VERSION, RunFeatures, RunRaw
from driftbase.config import get_settings
from driftbase.local.feature_deriver import derive_features


def _safe_import_rich():
    try:
        from rich.console import Console
        from rich.table import Table

        return Console, Table
    except ImportError:
        return None, None


@click.command(name="migrate")
@click.option(
    "--status",
    "action",
    flag_value="status",
    default=True,
    help="Show migration status (default).",
)
@click.option(
    "--backfill",
    "action",
    flag_value="backfill",
    help="Derive missing or stale features.",
)
@click.option(
    "--rebuild",
    "action",
    flag_value="rebuild",
    help="Drop all features and re-derive (requires --confirm).",
)
@click.option("--dry-run", is_flag=True, help="Show what would happen without changes.")
@click.option(
    "--confirm",
    is_flag=True,
    help="Confirm destructive operations (required for --rebuild).",
)
@click.pass_context
def cmd_migrate(
    ctx: click.Context,
    action: str,
    dry_run: bool,
    confirm: bool,
) -> None:
    """
    Manage schema migrations and feature derivation.

    \b
    Examples:
      driftbase migrate --status          # Show migration and feature status
      driftbase migrate --backfill        # Derive missing/stale features
      driftbase migrate --rebuild --confirm  # Re-derive all features
      driftbase migrate --backfill --dry-run # Preview backfill without changes
    """
    Console, Table = _safe_import_rich()
    console = ctx.obj.get("console") if Console else None

    if not console:
        console = type("PlainConsole", (), {"print": lambda self, x: print(x)})()

    settings = get_settings()
    db_path = Path(settings.DRIFTBASE_DB_PATH)

    if action == "status":
        _show_status(console, db_path)
    elif action == "backfill":
        _backfill_features(console, db_path, dry_run)
    elif action == "rebuild":
        if not confirm and not dry_run:
            console.print(
                "[#FF6B6B]✗[/] --rebuild requires --confirm flag for safety. "
                "This will drop all features and re-derive them."
            )
            ctx.exit(1)
        _rebuild_features(console, db_path, dry_run)


def _show_status(console, db_path: Path) -> None:
    """Show migration status and feature breakdown."""
    from rich.table import Table

    backend = get_backend()
    engine = backend._engine

    # Check if v0.11 migration is needed
    migration_needed = needs_migration(engine)

    if migration_needed:
        console.print("[#FFA94D]⚠[/] Database needs v0.11 schema migration")
        console.print(
            "  Run migration with: [#8B5CF6]driftbase migrate --run-migration[/]"
        )
        console.print(
            f"  Database will be backed up to: {escape(str(db_path))}.pre-v0.11.backup"
        )
        return

    # Query feature status
    with Session(engine) as session:
        # Check if new schema exists
        result = session.execute(
            text(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='runs_raw'"
            )
        )
        has_new_schema = result.fetchone() is not None

        if not has_new_schema:
            console.print("[#4ADE80]✓[/] Using legacy schema (agent_runs_local)")
            console.print("  No migration needed")
            return

        # Count runs and features
        result = session.execute(text("SELECT COUNT(*) FROM runs_raw"))
        total_runs = result.fetchone()[0]

        result = session.execute(text("SELECT COUNT(*) FROM runs_features"))
        total_features = result.fetchone()[0]

        # Breakdown by feature_source
        result = session.execute(
            text(
                "SELECT feature_source, COUNT(*) FROM runs_features GROUP BY feature_source"
            )
        )
        source_counts = dict(result.fetchall())
        derived_count = source_counts.get("derived", 0)
        migrated_count = source_counts.get("migrated", 0)

        # Count stale features
        result = session.execute(
            text(
                f"""
                SELECT COUNT(*) FROM runs_features
                WHERE feature_schema_version < {FEATURE_SCHEMA_VERSION}
                  AND feature_schema_version != -1
            """
            )
        )
        stale_count = result.fetchone()[0]

        # Count failed derivations
        result = session.execute(
            text("SELECT COUNT(*) FROM runs_features WHERE feature_schema_version = -1")
        )
        failed_count = result.fetchone()[0]

        # Count missing features
        missing_count = total_runs - total_features

        # Count runs with quality scores and get distribution
        result = session.execute(
            text("SELECT COUNT(*) FROM runs_features WHERE run_quality > 0.0")
        )
        quality_scored_count = result.fetchone()[0]

        quality_min = quality_median = quality_max = None
        if quality_scored_count > 0:
            # Get min, max
            result = session.execute(
                text(
                    "SELECT MIN(run_quality), MAX(run_quality) FROM runs_features WHERE run_quality > 0.0"
                )
            )
            row = result.fetchone()
            quality_min, quality_max = row[0], row[1]

            # Get median (use PERCENTILE_CONT if supported, otherwise approximation)
            result = session.execute(
                text(
                    """
                    SELECT run_quality FROM runs_features
                    WHERE run_quality > 0.0
                    ORDER BY run_quality
                    LIMIT 1 OFFSET (
                        SELECT COUNT(*) / 2 FROM runs_features WHERE run_quality > 0.0
                    )
                """
                )
            )
            median_row = result.fetchone()
            quality_median = median_row[0] if median_row else None

    # Display status table
    if Table:
        table = Table(show_header=True, header_style="bold", title="Migration Status")
        table.add_column("Metric", style="#8B5CF6")
        table.add_column("Count", justify="right")
        table.add_column("Details")

        table.add_row("Schema version", "v0.11", "runs_raw + runs_features")
        table.add_row("Total runs", str(total_runs), "")
        table.add_row("Total features", str(total_features), "")
        table.add_row(
            "  ├─ Derived", str(derived_count), "Computed by derive_features()"
        )
        table.add_row(
            "  └─ Migrated",
            str(migrated_count),
            "Copied from agent_runs_local",
        )
        if missing_count > 0:
            table.add_row(
                "Missing features",
                f"[#FFA94D]{missing_count}[/]",
                "Need derivation",
            )
        if stale_count > 0:
            table.add_row(
                "Stale features",
                f"[#FFA94D]{stale_count}[/]",
                f"Schema v{FEATURE_SCHEMA_VERSION - 1} → v{FEATURE_SCHEMA_VERSION}",
            )
        if failed_count > 0:
            table.add_row(
                "Failed derivations",
                f"[#FF6B6B]{failed_count}[/]",
                "feature_schema_version=-1",
            )

        # Add quality score stats
        if total_features > 0:
            table.add_row(
                "Quality scored runs",
                f"{quality_scored_count} / {total_features}",
                f"{100.0 * quality_scored_count / total_features:.1f}%",
            )
            if (
                quality_min is not None
                and quality_median is not None
                and quality_max is not None
            ):
                table.add_row(
                    "Quality distribution",
                    "",
                    f"min={quality_min:.2f}, median={quality_median:.2f}, max={quality_max:.2f}",
                )

        console.print()
        console.print(table)
        console.print()
    else:
        # Plain text fallback
        print("\nMigration Status:")
        print("  Schema version: v0.11 (runs_raw + runs_features)")
        print(f"  Total runs: {total_runs}")
        print(f"  Total features: {total_features}")
        print(f"    - Derived: {derived_count}")
        print(f"    - Migrated: {migrated_count}")
        if missing_count > 0:
            print(f"  Missing features: {missing_count}")
        if stale_count > 0:
            print(f"  Stale features: {stale_count}")
        if failed_count > 0:
            print(f"  Failed derivations: {failed_count}")
        if total_features > 0:
            print(
                f"  Quality scored runs: {quality_scored_count} / {total_features} ({100.0 * quality_scored_count / total_features:.1f}%)"
            )
            if (
                quality_min is not None
                and quality_median is not None
                and quality_max is not None
            ):
                print(
                    f"  Quality distribution: min={quality_min:.2f}, median={quality_median:.2f}, max={quality_max:.2f}"
                )
        print()

    # Recommendations
    if missing_count > 0 or stale_count > 0:
        console.print(
            "[#FFA94D]💡[/] Run [#8B5CF6]driftbase migrate --backfill[/] to derive missing/stale features"
        )


def _backfill_features(console, db_path: Path, dry_run: bool) -> None:
    """Derive missing or stale features."""
    backend = get_backend()
    engine = backend._engine

    with Session(engine) as session:
        # Find runs needing feature derivation
        query = f"""
            SELECT r.* FROM runs_raw r
            LEFT JOIN runs_features f ON r.id = f.run_id
            WHERE f.run_id IS NULL
               OR (f.feature_schema_version < {FEATURE_SCHEMA_VERSION}
                   AND f.feature_schema_version != -1)
        """
        result = session.execute(text(query))
        rows = result.fetchall()

    if not rows:
        console.print("[#4ADE80]✓[/] All features are up to date")
        return

    console.print(f"Found {len(rows)} runs needing feature derivation")

    if dry_run:
        console.print("[dim][DRY RUN] Would derive features for these runs:[/]")
        for row in rows[:10]:
            console.print(f"  - {row.id} (timestamp: {row.timestamp})")
        if len(rows) > 10:
            console.print(f"  ... and {len(rows) - 10} more")
        return

    # Derive features with progress bar
    with Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        console=console,
    ) as progress:
        task = progress.add_task("Deriving features...", total=len(rows))

        derived_count = 0
        failed_count = 0

        with Session(engine) as session:
            for row in rows:
                # Build RunRaw instance
                raw = RunRaw(
                    id=row.id,
                    external_id=row.external_id,
                    source=row.source,
                    ingestion_source=row.ingestion_source,
                    session_id=row.session_id,
                    deployment_version=row.deployment_version,
                    version_source=row.version_source,
                    environment=row.environment,
                    timestamp=row.timestamp,
                    input=row.input or "",
                    output=row.output or "",
                    latency_ms=row.latency_ms,
                    tokens_prompt=row.tokens_prompt,
                    tokens_completion=row.tokens_completion,
                    tokens_total=row.tokens_total,
                    raw_status=row.raw_status,
                    raw_error_message=row.raw_error_message,
                    observation_tree_json=row.observation_tree_json,
                    ingested_at=row.ingested_at,
                    raw_schema_version=row.raw_schema_version,
                )

                # Derive features
                features = derive_features(raw)

                # Check if update or insert
                existing = session.execute(
                    text("SELECT id FROM runs_features WHERE run_id = :run_id"),
                    {"run_id": raw.id},
                ).fetchone()

                try:
                    if existing:
                        # Update existing
                        session.execute(
                            text(
                                """
                                UPDATE runs_features SET
                                    feature_schema_version = :fsv,
                                    feature_source = :source,
                                    derivation_error = :error,
                                    tool_sequence = :tool_seq,
                                    tool_call_sequence = :tool_call_seq,
                                    tool_call_count = :tool_count,
                                    semantic_cluster = :cluster,
                                    loop_count = :loop,
                                    verbosity_ratio = :verbosity,
                                    time_to_first_tool_ms = :ttft,
                                    fallback_rate = :fallback,
                                    retry_count = :retry,
                                    retry_patterns = :retry_patterns,
                                    error_classification = :error_class,
                                    input_hash = :input_hash,
                                    output_hash = :output_hash,
                                    input_length = :input_len,
                                    output_length = :output_len,
                                    run_quality = :quality,
                                    computed_at = :computed_at
                                WHERE run_id = :run_id
                            """
                            ),
                            {
                                "fsv": features.feature_schema_version,
                                "source": features.feature_source,
                                "error": features.derivation_error,
                                "tool_seq": features.tool_sequence,
                                "tool_call_seq": features.tool_call_sequence,
                                "tool_count": features.tool_call_count,
                                "cluster": features.semantic_cluster,
                                "loop": features.loop_count,
                                "verbosity": features.verbosity_ratio,
                                "ttft": features.time_to_first_tool_ms,
                                "fallback": features.fallback_rate,
                                "retry": features.retry_count,
                                "retry_patterns": features.retry_patterns,
                                "error_class": features.error_classification,
                                "input_hash": features.input_hash,
                                "output_hash": features.output_hash,
                                "input_len": features.input_length,
                                "output_len": features.output_length,
                                "quality": features.run_quality,
                                "computed_at": features.computed_at,
                                "run_id": raw.id,
                            },
                        )
                    else:
                        # Insert new
                        session.add(features)

                    session.commit()

                    if features.feature_schema_version == -1:
                        failed_count += 1
                    else:
                        derived_count += 1
                except Exception:
                    session.rollback()
                    failed_count += 1

                progress.update(task, advance=1)

    console.print(f"[#4ADE80]✓[/] Derived {derived_count} features successfully")
    if failed_count > 0:
        console.print(f"[#FF6B6B]⚠[/] {failed_count} derivations failed")


def _rebuild_features(console, db_path: Path, dry_run: bool) -> None:
    """Drop all features and re-derive."""
    backend = get_backend()
    engine = backend._engine

    with Session(engine) as session:
        result = session.execute(text("SELECT COUNT(*) FROM runs_raw"))
        total_runs = result.fetchone()[0]

    if dry_run:
        console.print(
            f"[dim][DRY RUN] Would delete all features and re-derive {total_runs} features[/]"
        )
        return

    console.print(
        f"[#FFA94D]⚠[/] Dropping all features and re-deriving {total_runs}..."
    )

    # Drop all features
    with Session(engine) as session:
        session.execute(text("DELETE FROM runs_features"))
        session.commit()

    console.print("[#4ADE80]✓[/] Deleted all existing features")

    # Re-derive all
    with Session(engine) as session:
        result = session.execute(text("SELECT * FROM runs_raw"))
        rows = result.fetchall()

    with Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        console=console,
    ) as progress:
        task = progress.add_task("Deriving features...", total=len(rows))

        derived_count = 0
        failed_count = 0

        with Session(engine) as session:
            for row in rows:
                raw = RunRaw(
                    id=row.id,
                    external_id=row.external_id,
                    source=row.source,
                    ingestion_source=row.ingestion_source,
                    session_id=row.session_id,
                    deployment_version=row.deployment_version,
                    version_source=row.version_source,
                    environment=row.environment,
                    timestamp=row.timestamp,
                    input=row.input or "",
                    output=row.output or "",
                    latency_ms=row.latency_ms,
                    tokens_prompt=row.tokens_prompt,
                    tokens_completion=row.tokens_completion,
                    tokens_total=row.tokens_total,
                    raw_status=row.raw_status,
                    raw_error_message=row.raw_error_message,
                    observation_tree_json=row.observation_tree_json,
                    ingested_at=row.ingested_at,
                    raw_schema_version=row.raw_schema_version,
                )

                features = derive_features(raw)

                try:
                    session.add(features)
                    session.commit()

                    if features.feature_schema_version == -1:
                        failed_count += 1
                    else:
                        derived_count += 1
                except Exception:
                    session.rollback()
                    failed_count += 1

                progress.update(task, advance=1)

    console.print(f"[#4ADE80]✓[/] Derived {derived_count} features successfully")
    if failed_count > 0:
        console.print(f"[#FF6B6B]⚠[/] {failed_count} derivations failed")
