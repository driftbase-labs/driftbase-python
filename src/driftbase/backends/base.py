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

    def write_budget_breach(self, breach: dict[str, Any]) -> None:
        """Write a budget breach record. Must not raise; log and swallow errors."""
        raise NotImplementedError(
            "write_budget_breach not implemented for this backend"
        )

    def get_budget_breaches(
        self, agent_id: str | None = None, version: str | None = None
    ) -> list[dict[str, Any]]:
        """Return budget breaches, optionally filtered by agent_id and version."""
        raise NotImplementedError(
            "get_budget_breaches not implemented for this backend"
        )

    def write_budget_config(
        self, agent_id: str, version: str, config: dict[str, Any], source: str
    ) -> None:
        """Write a budget config. Must not raise; log and swallow errors."""
        raise NotImplementedError(
            "write_budget_config not implemented for this backend"
        )

    def get_budget_config(self, agent_id: str, version: str) -> dict[str, Any] | None:
        """Return budget config for agent_id + version, or None if not found."""
        raise NotImplementedError("get_budget_config not implemented for this backend")

    def delete_budget_breaches(
        self, agent_id: str | None = None, version: str | None = None
    ) -> int:
        """Delete budget breaches, optionally filtered. Returns number deleted."""
        raise NotImplementedError(
            "delete_budget_breaches not implemented for this backend"
        )

    def write_change_event(self, event: dict[str, Any]) -> None:
        """Write a change event. On UNIQUE conflict, log warning and do not overwrite."""
        raise NotImplementedError("write_change_event not implemented for this backend")

    def get_change_events(self, agent_id: str, version: str) -> list[dict[str, Any]]:
        """Return change events for agent_id + version."""
        raise NotImplementedError("get_change_events not implemented for this backend")

    def get_change_events_for_versions(
        self, agent_id: str, v1: str, v2: str
    ) -> dict[str, list[dict[str, Any]]]:
        """Return change events for two versions. Returns {"v1": [...], "v2": [...]}."""
        raise NotImplementedError(
            "get_change_events_for_versions not implemented for this backend"
        )

    def write_deploy_outcome(
        self,
        agent_id: str,
        version: str,
        outcome: str,
        note: str = "",
        labeled_by: str = "user",
    ) -> None:
        """Write deploy outcome label. On UNIQUE conflict, overwrite. Must not raise."""
        raise NotImplementedError(
            "write_deploy_outcome not implemented for this backend"
        )

    def get_deploy_outcome(self, agent_id: str, version: str) -> dict[str, Any] | None:
        """Return deploy outcome for agent_id + version, or None if not found."""
        raise NotImplementedError("get_deploy_outcome not implemented for this backend")

    def get_deploy_outcomes(self, agent_id: str) -> list[dict[str, Any]]:
        """Return all labeled versions for agent_id, ordered by labeled_at desc."""
        raise NotImplementedError(
            "get_deploy_outcomes not implemented for this backend"
        )

    def get_labeled_versions_with_drift(self, agent_id: str) -> list[dict[str, Any]]:
        """
        Return versions with both deploy_outcome AND DriftReport.
        Training set for weight learning.
        Each record: {version, outcome, drift_scores_per_dimension}.
        """
        raise NotImplementedError(
            "get_labeled_versions_with_drift not implemented for this backend"
        )

    def write_learned_weights(
        self, agent_id: str, learned_weights: dict[str, Any]
    ) -> None:
        """Write learned weights to cache. On UNIQUE conflict, overwrite. Must not raise."""
        raise NotImplementedError(
            "write_learned_weights not implemented for this backend"
        )

    def get_learned_weights(self, agent_id: str) -> dict[str, Any] | None:
        """Return learned weights for agent_id, or None if not found."""
        raise NotImplementedError(
            "get_learned_weights not implemented for this backend"
        )
