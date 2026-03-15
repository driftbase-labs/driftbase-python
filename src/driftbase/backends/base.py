"""
Abstract storage backend for agent runs (local capture from @track()).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class StorageBackend(ABC):
    """Abstract backend for writing and reading agent runs (e.g. for driftbase versions CLI and fingerprinting)."""

    @abstractmethod
    def write_run(self, payload: dict[str, Any]) -> None:
        """Write a single agent run. Must not raise; log and swallow errors."""
        ...

    def write_runs(self, batch: list[dict[str, Any]]) -> None:
        """Write multiple runs in one transaction if supported. Default: loop write_run."""
        for payload in batch:
            self.write_run(payload)

    @abstractmethod
    def get_runs(
        self,
        deployment_version: str | None = None,
        environment: str | None = None,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        """Return runs, optionally filtered by deployment_version and environment. Newest first."""
        ...

    @abstractmethod
    def get_versions(self) -> list[tuple[str, int]]:
        """Return (deployment_version, run_count) pairs, ordered by deployment_version."""
        ...

    def delete_runs(self, deployment_version: str) -> int:
        """Delete all runs for the given deployment_version. Returns number of rows deleted."""
        raise NotImplementedError("delete_runs not implemented for this backend")

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        """Return a single run by id, or None if not found. Optional for backends."""
        return None

    def get_last_run(self) -> dict[str, Any] | None:
        """Return the most recently written run, or None. Optional for backends."""
        return None

    def get_all_runs(self) -> list[dict[str, Any]]:
        """Return all runs for sync to dashboard (e.g. driftbase push). Default: get_runs(limit=500_000)."""
        return self.get_runs(deployment_version=None, environment=None, limit=500_000)
