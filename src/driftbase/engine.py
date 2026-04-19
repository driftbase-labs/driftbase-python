"""
Public API surface for Driftbase drift detection engine.

This module provides the canonical entry points for all drift operations.
All other modules in driftbase.local/ and driftbase.connectors/ are
implementation details.

Usage:
    from driftbase.engine import compute_drift, compute_verdict, import_traces

    # Import traces from Langfuse
    result = import_traces(
        connector_type="langfuse",
        project_name="my-project",
        since=datetime(2026, 4, 1),
        limit=1000
    )

    # Compute drift between two versions
    report = compute_drift(
        baseline_version="v1.0",
        current_version="v2.0",
        sensitivity="standard"
    )

    # Generate verdict
    verdict = compute_verdict(report)

    # Check verdict
    if verdict.exit_code != 0:
        print(f"⚠ {verdict.title}: {verdict.explanation}")
        for step in verdict.next_steps:
            print(f"  • {step}")
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from driftbase.local.local_store import DriftReport, run_dict_to_agent_run
from driftbase.verdict import Verdict, VerdictResult
from driftbase.verdict import compute_verdict as _compute_verdict

__all__ = [
    "compute_drift",
    "compute_verdict",
    "import_traces",
    "ImportResult",
    "DriftReport",
    "VerdictResult",
    "Verdict",
]


class ImportResult:
    """Result of trace import operation."""

    def __init__(
        self,
        success: bool,
        traces_fetched: int,
        runs_written: int,
        skipped: int,
        errors: list[str],
        connector_type: str,
        project_name: str,
    ):
        self.success = success
        self.traces_fetched = traces_fetched
        self.runs_written = runs_written
        self.skipped = skipped
        self.errors = errors
        self.connector_type = connector_type
        self.project_name = project_name

    def __repr__(self) -> str:
        status = "SUCCESS" if self.success else "FAILED"
        return (
            f"ImportResult({status}: {self.runs_written}/{self.traces_fetched} runs imported, "
            f"{len(self.errors)} errors)"
        )


def import_traces(
    connector_type: str,
    project_name: str | None = None,
    since: datetime | None = None,
    limit: int = 500,
    agent_id: str | None = None,
    dry_run: bool = False,
    db_path: str | None = None,
) -> ImportResult:
    """
    Import traces from an external source (Langfuse, LangSmith, etc.).

    This is the canonical way to import traces into Driftbase for drift analysis.

    Args:
        connector_type: Type of connector ("langfuse", "langsmith", etc.)
        project_name: Project/workspace name in the external system
        since: Fetch traces since this datetime (default: 30 days ago)
        limit: Maximum number of traces to fetch (default: 500)
        agent_id: Override agent ID in Driftbase (default: use project_name)
        dry_run: If True, show what would be imported without writing (default: False)
        db_path: Optional database path (default: from DRIFTBASE_DB_PATH env var)

    Returns:
        ImportResult with success status, counts, and any errors

    Raises:
        ValueError: If connector_type is not supported or required params missing
        ImportError: If connector dependencies not installed

    Example:
        >>> from datetime import datetime, timedelta
        >>> result = import_traces(
        ...     connector_type="langfuse",
        ...     project_name="support-bot",
        ...     since=datetime.utcnow() - timedelta(days=7),
        ...     limit=1000
        ... )
        >>> print(f"Imported {result.runs_written} runs")
    """
    from datetime import timedelta

    from driftbase.backends.factory import get_backend
    from driftbase.connectors.base import ConnectorConfig

    # Validate connector_type
    if connector_type not in ["langfuse", "langsmith"]:
        raise ValueError(
            f"Unsupported connector_type: {connector_type}. "
            f"Supported: langfuse, langsmith"
        )

    # Import connector
    if connector_type == "langfuse":
        try:
            from driftbase.connectors.langfuse import (
                LANGFUSE_AVAILABLE,
                LangFuseConnector,
            )

            if not LANGFUSE_AVAILABLE:
                raise ImportError(
                    "langfuse package not installed. Run: pip install driftbase"
                )
            connector = LangFuseConnector()
        except ImportError as e:
            raise ImportError(
                f"Failed to import LangFuse connector: {e}. "
                f"Install with: pip install driftbase"
            ) from e

    elif connector_type == "langsmith":
        # TODO: Implement LangSmith connector
        raise NotImplementedError(
            "LangSmith connector not yet implemented. "
            "Track progress at: https://github.com/anthropics/driftbase-python/issues"
        )

    # Set defaults
    if since is None:
        since = datetime.utcnow() - timedelta(days=30)

    if project_name is None and agent_id is None:
        raise ValueError("Either project_name or agent_id must be specified")

    # Create config
    config = ConnectorConfig(
        project_name=project_name or "",
        since=since,
        limit=limit,
        agent_id=agent_id,
    )

    # Sync
    backend = get_backend()
    if db_path:
        # Override db_path if provided
        # TODO: Support custom db_path in backend
        pass

    result = connector.sync(config, backend.db_path, dry_run=dry_run)

    # Convert to ImportResult
    return ImportResult(
        success=result.success,
        traces_fetched=result.traces_fetched,
        runs_written=result.runs_written,
        skipped=result.skipped,
        errors=result.errors,
        connector_type=connector_type,
        project_name=project_name or agent_id or "unknown",
    )


def compute_drift(
    baseline_version: str,
    current_version: str,
    sensitivity: str = "standard",
    agent_id: str | None = None,
    environment: str = "production",
    db_path: str | None = None,
) -> DriftReport:
    """
    Compute behavioral drift between two deployment versions.

    This is the canonical way to compute drift in Driftbase. It:
    1. Loads runs from the backend for both versions
    2. Builds behavioral fingerprints
    3. Infers use case from tool names and behavioral patterns
    4. Calibrates dimension weights based on baseline variance
    5. Computes 12-dimensional drift scores
    6. Generates bootstrap confidence intervals
    7. Detects multivariate anomalies
    8. Returns a comprehensive drift report

    Args:
        baseline_version: Baseline version identifier (e.g., "v1.0")
        current_version: Current version identifier (e.g., "v2.0")
        sensitivity: Threshold sensitivity ("strict" | "standard" | "relaxed")
                    - strict: Lower thresholds, catch smaller changes
                    - standard: Balanced (default)
                    - relaxed: Higher thresholds, reduce false positives
        agent_id: Optional agent ID to filter runs (default: uses all runs for versions)
        environment: Environment filter (default: "production")
        db_path: Optional database path (default: from DRIFTBASE_DB_PATH env var)

    Returns:
        DriftReport with drift scores, confidence tier, verdict thresholds, and metadata

    Raises:
        ValueError: If versions not found or insufficient data

    Example:
        >>> report = compute_drift("v1.0", "v2.0")
        >>> print(f"Drift score: {report.drift_score:.2f}")
        >>> print(f"Confidence tier: {report.confidence_tier}")
        >>> print(f"Decision drift: {report.decision_drift:.2f}")
        >>> print(f"Latency drift: {report.latency_drift:.2f}")

    Confidence Tiers:
        - TIER1 (n < 15): Insufficient data, progress bars only
        - TIER2 (15 ≤ n < min_runs): Indicative signals (arrows), no verdict
        - TIER3 (n ≥ min_runs): Full analysis with verdict

    See ARCHITECTURE.md for detailed documentation.
    """
    from driftbase.backends.factory import get_backend
    from driftbase.local.diff import compute_drift as _compute_drift_internal
    from driftbase.local.fingerprinter import build_fingerprint_from_runs

    backend = get_backend()

    # Load runs for both versions
    baseline_runs = backend.get_runs(
        deployment_version=baseline_version,
        environment=environment,
        limit=1000,
    )
    current_runs = backend.get_runs(
        deployment_version=current_version,
        environment=environment,
        limit=1000,
    )

    # Filter by agent_id if provided
    if agent_id:
        baseline_runs = [r for r in baseline_runs if r.get("session_id") == agent_id]
        current_runs = [r for r in current_runs if r.get("session_id") == agent_id]

    # Validate data availability
    if not baseline_runs:
        raise ValueError(
            f"No runs found for baseline version '{baseline_version}'. "
            f"Import traces first with import_traces() or driftbase connect."
        )

    if not current_runs:
        raise ValueError(
            f"No runs found for current version '{current_version}'. "
            f"Import traces first with import_traces() or driftbase connect."
        )

    # Convert to AgentRun objects
    baseline_agent_runs = [run_dict_to_agent_run(r) for r in baseline_runs]
    current_agent_runs = [run_dict_to_agent_run(r) for r in current_runs]

    # Build fingerprints
    baseline_fp = build_fingerprint_from_runs(
        baseline_agent_runs,
        window_start=min(r.started_at for r in baseline_agent_runs),
        window_end=max(r.completed_at or r.started_at for r in baseline_agent_runs),
        deployment_version=baseline_version,
        environment=environment,
    )

    current_fp = build_fingerprint_from_runs(
        current_agent_runs,
        window_start=min(r.started_at for r in current_agent_runs),
        window_end=max(r.completed_at or r.started_at for r in current_agent_runs),
        deployment_version=current_version,
        environment=environment,
    )

    # Compute drift
    report = _compute_drift_internal(
        baseline=baseline_fp,
        current=current_fp,
        baseline_runs=baseline_runs,
        current_runs=current_runs,
        sensitivity=sensitivity,
        backend=backend,
    )

    return report


def compute_verdict(
    report: DriftReport,
    baseline_tools: dict[str, float] | None = None,
    current_tools: dict[str, float] | None = None,
    baseline_n: int = 0,
    current_n: int = 0,
    baseline_label: str = "",
    current_label: str = "",
) -> VerdictResult | None:
    """
    Generate a ship/no-ship verdict from a drift report.

    This is the canonical way to get a deployment verdict in Driftbase.
    Maps drift scores to actionable decisions: SHIP, MONITOR, REVIEW, or BLOCK.

    Args:
        report: DriftReport from compute_drift()
        baseline_tools: Optional tool distribution for baseline (for next steps)
        current_tools: Optional tool distribution for current (for next steps)
        baseline_n: Number of baseline runs (for context)
        current_n: Number of current runs (for context)
        baseline_label: Version label for baseline (for next steps command)
        current_label: Version label for current (for next steps command)

    Returns:
        VerdictResult with verdict, explanation, next steps, and exit code.
        Returns None for TIER1 and TIER2 (insufficient data for verdict).

    Verdict Levels:
        - SHIP (exit_code=0): No meaningful change, safe to deploy
        - MONITOR (exit_code=0): Minor drift, ship with awareness
        - REVIEW (exit_code=1): Behavioral change, review before shipping
        - BLOCK (exit_code=1): Major divergence, do not ship

    Example:
        >>> report = compute_drift("v1.0", "v2.0")
        >>> verdict = compute_verdict(report, baseline_label="v1.0", current_label="v2.0")
        >>> if verdict is None:
        ...     print("Insufficient data for verdict")
        >>> elif verdict.exit_code != 0:
        ...     print(f"{verdict.symbol} {verdict.title}")
        ...     print(f"Reason: {verdict.explanation}")
        ...     for step in verdict.next_steps:
        ...         print(f"  • {step}")

    See ARCHITECTURE.md for detailed documentation.
    """
    return _compute_verdict(
        report=report,
        baseline_tools=baseline_tools,
        current_tools=current_tools,
        baseline_n=baseline_n,
        current_n=current_n,
        baseline_label=baseline_label,
        current_label=current_label,
    )
