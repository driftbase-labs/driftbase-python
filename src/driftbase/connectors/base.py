"""Base classes for trace connectors."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ConnectorConfig:
    """Configuration for connector sync."""

    project_name: str
    since: datetime | None = None
    limit: int = 500
    agent_id: str | None = None


@dataclass
class SyncResult:
    """Result of a connector sync operation."""

    success: bool
    traces_fetched: int = 0
    runs_written: int = 0
    skipped: int = 0  # already imported
    errors: list[str] = field(default_factory=list)


class TraceConnector(ABC):
    """Abstract base class for trace connectors."""

    @abstractmethod
    def validate_credentials(self) -> bool:
        """
        Check if credentials are valid.
        Never raises — return False on failure.
        """

    @abstractmethod
    def fetch_traces(self, config: ConnectorConfig) -> list[dict]:
        """
        Fetch raw traces from the external source.
        Never raises — return empty list on failure.
        """

    @abstractmethod
    def map_trace(self, trace: dict, config: ConnectorConfig) -> dict | None:
        """
        Map a single trace to Driftbase run schema.
        Return None to skip this trace.
        Never raises — return None on error.
        """

    def sync(
        self,
        config: ConnectorConfig,
        db_path: str,
        dry_run: bool = False,
        incremental: bool = True,
    ) -> SyncResult:
        """
        Full or incremental sync: fetch → map → write to SQLite.

        Args:
            config: Connector configuration
            db_path: Path to database (unused, kept for compatibility)
            dry_run: If True, don't write to database
            incremental: If True, use last_sync_at to fetch only new traces

        Never raises. Returns SyncResult with counts and any errors.
        """
        from driftbase.backends.factory import get_backend

        errors = []

        # Validate credentials
        if not self.validate_credentials():
            return SyncResult(
                success=False,
                errors=["Invalid credentials. Check your API keys."],
            )

        # Get backend
        try:
            backend = get_backend()
        except Exception as e:
            logger.error(f"Failed to get backend: {e}")
            return SyncResult(
                success=False,
                errors=[f"Failed to get backend: {str(e)}"],
            )

        # Check for last sync (incremental mode)
        last_sync_data = None
        if incremental and not config.since:
            try:
                last_sync_data = backend.get_connector_sync(
                    source=self.__class__.__name__.lower().replace("connector", ""),
                    project_name=config.project_name or "",
                )
                if last_sync_data and last_sync_data.get("last_sync_at"):
                    config.since = last_sync_data["last_sync_at"]
                    logger.info(f"Incremental sync from {config.since}")
            except Exception as e:
                logger.debug(f"Failed to get last sync: {e}")

        # Fetch traces
        try:
            traces = self.fetch_traces(config)
        except Exception as e:
            logger.error(f"Failed to fetch traces: {e}")
            return SyncResult(
                success=False,
                errors=[f"Failed to fetch traces: {str(e)}"],
            )

        if not traces:
            return SyncResult(
                success=True,
                traces_fetched=0,
                runs_written=0,
                errors=["No traces found for the given criteria."],
            )

        # Get backend
        try:
            backend = get_backend()
        except Exception as e:
            logger.error(f"Failed to get backend: {e}")
            return SyncResult(
                success=False,
                errors=[f"Failed to get backend: {str(e)}"],
            )

        # Map and write
        runs_to_write = []
        skipped_count = 0

        for trace in traces:
            try:
                run = self.map_trace(trace, config)
                if run is None:
                    continue

                # Check if already imported (by external_id)
                external_id = run.get("external_id")
                if external_id and self._is_already_imported(
                    backend, external_id, run.get("source")
                ):
                    skipped_count += 1
                    continue

                runs_to_write.append(run)
            except Exception as e:
                logger.error(f"Failed to map trace {trace.get('id')}: {e}")
                errors.append(f"Failed to map trace {trace.get('id')}: {str(e)}")

        # Write to backend
        if not dry_run and runs_to_write:
            try:
                backend.write_runs(runs_to_write)
            except Exception as e:
                logger.error(f"Failed to write runs: {e}")
                return SyncResult(
                    success=False,
                    traces_fetched=len(traces),
                    runs_written=0,
                    skipped=skipped_count,
                    errors=[f"Failed to write runs: {str(e)}"],
                )

        # Update sync metadata (for incremental sync)
        if not dry_run and runs_to_write:
            try:
                source_name = self.__class__.__name__.lower().replace("connector", "")
                last_external_id = (
                    runs_to_write[-1].get("external_id") if runs_to_write else None
                )

                backend.write_connector_sync(
                    source=source_name,
                    project_name=config.project_name or "",
                    agent_id=config.agent_id or "",
                    runs_imported=len(runs_to_write),
                    last_external_id=last_external_id,
                )
            except Exception as e:
                logger.debug(f"Failed to update sync metadata: {e}")

        return SyncResult(
            success=True,
            traces_fetched=len(traces),
            runs_written=len(runs_to_write),
            skipped=skipped_count,
            errors=errors,
        )

    def _is_already_imported(
        self, backend: Any, external_id: str, source: str | None
    ) -> bool:
        """Check if a trace with this external_id already exists."""
        try:
            # Query for runs with this external_id and source
            from sqlmodel import Session, select

            from driftbase.backends.sqlite import AgentRunLocal

            with Session(backend._engine) as session:
                stmt = select(AgentRunLocal).where(
                    AgentRunLocal.external_id == external_id
                )
                if source:
                    stmt = stmt.where(AgentRunLocal.source == source)
                result = session.execute(stmt)
                return result.first() is not None
        except Exception as e:
            logger.debug(f"Failed to check if already imported: {e}")
            return False
