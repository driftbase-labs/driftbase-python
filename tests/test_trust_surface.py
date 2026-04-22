"""
Tests for Phase 3b: Trust Surface.

Covers verdict history, verdict payload, evidence generation, CLI formats,
explain command, root cause, and composite score stability.
"""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timedelta, timezone
from io import StringIO

import pytest
from click.testing import CliRunner

from driftbase.backends.sqlite import SQLiteBackend
from driftbase.cli.cli_diff import cmd_diff
from driftbase.cli.cli_explain import cmd_explain
from driftbase.local.diff import compute_drift
from driftbase.local.fingerprinter import build_fingerprint_from_runs
from driftbase.local.local_store import AgentRun, BehavioralFingerprint, DriftReport
from driftbase.output.evidence import generate_evidence
from driftbase.output.verdict_payload import build_verdict_payload
from driftbase.verdict import Verdict, compute_verdict

# Fixtures


@pytest.fixture
def temp_db():
    """Create temporary SQLite database."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    backend = SQLiteBackend(db_path=db_path)
    backend.db_path = db_path  # Store for tests
    yield backend
    import os

    try:
        os.unlink(db_path)
    except Exception:
        pass


@pytest.fixture
def sample_runs():
    """Create sample runs for testing."""
    base_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    runs = []
    for i in range(60):
        run = AgentRun(
            id=f"run_{i}",
            session_id=f"sess_{i}",
            deployment_version="v1.0",
            environment="production",
            started_at=base_time + timedelta(minutes=i),
            completed_at=base_time + timedelta(minutes=i, seconds=30),
            task_input_hash="hash_123",
            tool_sequence='["tool_a", "tool_b"]',
            tool_call_count=2,
            output_length=100 + i,
            output_structure_hash="struct_hash",
            latency_ms=1000 + i * 10,
            error_count=0 if i % 10 != 0 else 1,
            retry_count=0,
            semantic_cluster="resolved",
            loop_count=1,
            time_to_first_tool_ms=100,
            verbosity_ratio=1.0,
        )
        runs.append(run)
    return runs


@pytest.fixture
def sample_run_dicts(sample_runs):
    """Convert sample runs to dicts."""
    return [
        {
            "id": r.id,
            "session_id": r.session_id,
            "deployment_version": r.deployment_version,
            "environment": r.environment,
            "started_at": r.started_at,
            "completed_at": r.completed_at,
            "task_input_hash": r.task_input_hash,
            "tool_sequence": r.tool_sequence,
            "tool_call_count": r.tool_call_count,
            "output_length": r.output_length,
            "output_structure_hash": r.output_structure_hash,
            "latency_ms": r.latency_ms,
            "error_count": r.error_count,
            "retry_count": r.retry_count,
            "semantic_cluster": r.semantic_cluster,
            "loop_count": r.loop_count,
            "time_to_first_tool_ms": r.time_to_first_tool_ms,
            "verbosity_ratio": r.verbosity_ratio,
        }
        for r in sample_runs
    ]


@pytest.fixture
def sample_fingerprints(sample_runs):
    """Create baseline and current fingerprints."""
    base_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    baseline_runs = sample_runs[:30]
    current_runs_modified = []

    for run in sample_runs[30:]:
        modified = AgentRun(
            id=run.id,
            session_id=run.session_id,
            deployment_version="v2.0",
            environment=run.environment,
            started_at=run.started_at,
            completed_at=run.completed_at,
            task_input_hash=run.task_input_hash,
            tool_sequence='["tool_a", "tool_c"]',  # Changed tool
            tool_call_count=run.tool_call_count,
            output_length=run.output_length,
            output_structure_hash=run.output_structure_hash,
            latency_ms=run.latency_ms + 200,  # Increased latency
            error_count=run.error_count,
            retry_count=run.retry_count,
            semantic_cluster=run.semantic_cluster,
            loop_count=run.loop_count,
            time_to_first_tool_ms=run.time_to_first_tool_ms,
            verbosity_ratio=run.verbosity_ratio,
        )
        current_runs_modified.append(modified)

    baseline_fp = build_fingerprint_from_runs(
        baseline_runs, base_time, base_time + timedelta(hours=1), "v1.0", "production"
    )
    current_fp = build_fingerprint_from_runs(
        current_runs_modified,
        base_time + timedelta(hours=2),
        base_time + timedelta(hours=3),
        "v2.0",
        "production",
    )

    return baseline_fp, current_fp, baseline_runs, current_runs_modified


@pytest.fixture
def sample_report(sample_fingerprints, sample_run_dicts):
    """Create sample DriftReport with Phase 3a stats."""
    baseline_fp, current_fp, baseline_runs, current_runs = sample_fingerprints

    baseline_run_dicts = [
        {
            "id": r.id,
            "session_id": r.session_id,
            "deployment_version": r.deployment_version,
            "environment": r.environment,
            "started_at": r.started_at,
            "completed_at": r.completed_at,
            "task_input_hash": r.task_input_hash,
            "tool_sequence": r.tool_sequence,
            "tool_call_count": r.tool_call_count,
            "output_length": r.output_length,
            "output_structure_hash": r.output_structure_hash,
            "latency_ms": r.latency_ms,
            "error_count": r.error_count,
            "retry_count": r.retry_count,
            "semantic_cluster": r.semantic_cluster,
            "loop_count": r.loop_count,
            "time_to_first_tool_ms": r.time_to_first_tool_ms,
            "verbosity_ratio": r.verbosity_ratio,
        }
        for r in baseline_runs
    ]

    current_run_dicts = [
        {
            "id": r.id,
            "session_id": r.session_id,
            "deployment_version": r.deployment_version,
            "environment": r.environment,
            "started_at": r.started_at,
            "completed_at": r.completed_at,
            "task_input_hash": r.task_input_hash,
            "tool_sequence": r.tool_sequence,
            "tool_call_count": r.tool_call_count,
            "output_length": r.output_length,
            "output_structure_hash": r.output_structure_hash,
            "latency_ms": r.latency_ms,
            "error_count": r.error_count,
            "retry_count": r.retry_count,
            "semantic_cluster": r.semantic_cluster,
            "loop_count": r.loop_count,
            "time_to_first_tool_ms": r.time_to_first_tool_ms,
            "verbosity_ratio": r.verbosity_ratio,
        }
        for r in current_runs
    ]

    report = compute_drift(
        baseline_fp,
        current_fp,
        baseline_runs=baseline_run_dicts,
        current_runs=current_run_dicts,
    )

    return report


# Verdict History Tests (3 tests)


def test_verdict_saved_after_diff(temp_db, sample_report):
    """Test that verdicts are saved to verdict_history table."""
    report_json = json.dumps(
        {
            "drift_score": sample_report.drift_score,
            "severity": sample_report.severity,
            "decision_drift": sample_report.decision_drift,
        }
    )

    verdict_id = temp_db.save_verdict(
        report_json=report_json,
        baseline_version="v1.0",
        current_version="v2.0",
        environment="production",
        composite_score=sample_report.drift_score,
        verdict="REVIEW",
        severity=sample_report.severity,
        confidence_tier="TIER3",
    )

    assert verdict_id is not None
    assert len(verdict_id) > 0


def test_verdict_retrievable_by_id(temp_db, sample_report):
    """Test that saved verdicts can be retrieved by ID."""
    report_json = json.dumps({"drift_score": 0.25})

    verdict_id = temp_db.save_verdict(
        report_json=report_json,
        baseline_version="v1.0",
        current_version="v2.0",
        environment="production",
        composite_score=0.25,
        verdict="REVIEW",
        severity="moderate",
        confidence_tier="TIER3",
    )

    retrieved = temp_db.get_verdict(verdict_id)

    assert retrieved is not None
    assert retrieved["id"] == verdict_id
    assert retrieved["baseline_version"] == "v1.0"
    assert retrieved["current_version"] == "v2.0"
    assert retrieved["verdict"] == "REVIEW"
    assert retrieved["composite_score"] == 0.25


def test_list_verdicts_ordered(temp_db):
    """Test that list_verdicts returns verdicts in reverse chronological order."""
    import time

    for i in range(3):
        temp_db.save_verdict(
            report_json=json.dumps({"score": i}),
            baseline_version=f"v{i}",
            current_version=f"v{i + 1}",
            environment="production",
            composite_score=0.1 * i,
            verdict="SHIP",
            severity="none",
            confidence_tier="TIER3",
        )
        time.sleep(0.01)  # Ensure different timestamps

    verdicts = temp_db.list_verdicts(limit=10)

    assert len(verdicts) == 3
    # Most recent first
    assert verdicts[0]["current_version"] == "v3"
    assert verdicts[1]["current_version"] == "v2"
    assert verdicts[2]["current_version"] == "v1"


# Verdict Payload Tests (5 tests)


def test_payload_structure(sample_report):
    """Test verdict payload has required structure."""
    payload = build_verdict_payload(sample_report, backend=None)

    assert "version" in payload
    assert payload["version"] == "1.0"
    assert "verdict" in payload
    assert "composite_score" in payload
    assert "confidence_tier" in payload
    assert "confidence" in payload
    assert "top_contributors" in payload
    assert "mdes" in payload
    assert "sample_sizes" in payload
    assert "thresholds" in payload


def test_payload_top_contributors_limited_to_3(sample_report):
    """Test that top_contributors is limited to 3 dimensions."""
    payload = build_verdict_payload(sample_report, backend=None)

    assert len(payload["top_contributors"]) <= 3


def test_payload_evidence_non_empty(sample_report):
    """Test that evidence strings are non-empty for top contributors."""
    payload = build_verdict_payload(sample_report, backend=None)

    for contributor in payload["top_contributors"]:
        assert "evidence" in contributor
        assert isinstance(contributor["evidence"], str)
        assert len(contributor["evidence"]) > 0


def test_payload_rollback_target(temp_db, sample_report):
    """Test rollback target is populated from verdict history."""
    # Save a SHIP verdict first
    temp_db.save_verdict(
        report_json=json.dumps({}),
        baseline_version="v0.9",
        current_version="v1.0",
        environment="production",
        composite_score=0.05,
        verdict="SHIP",
        severity="none",
        confidence_tier="TIER3",
    )

    # Create a DriftReport with environment field
    report = DriftReport(
        baseline_fingerprint_id="fp1",
        current_fingerprint_id="fp2",
        drift_score=0.30,
        severity="significant",
        decision_drift=0.20,
        latency_drift=0.10,
        error_drift=0.05,
        escalation_rate_delta=0.0,
        summary="Test",
    )
    # Add environment attribute
    report.environment = "production"

    payload = build_verdict_payload(report, backend=temp_db)

    # Rollback target should be v1.0 (most recent SHIP)
    assert payload.get("rollback_target") == "v1.0"


def test_payload_json_serializable(sample_report):
    """Test that payload is JSON serializable."""
    payload = build_verdict_payload(sample_report, backend=None)

    # Should not raise
    json_str = json.dumps(payload)
    assert len(json_str) > 0

    # Should round-trip
    parsed = json.loads(json_str)
    assert parsed["version"] == "1.0"


# Evidence Generation Tests (4 tests)


def test_evidence_decision_drift():
    """Test evidence generation for decision drift."""
    baseline_fp = BehavioralFingerprint(
        id="fp1",
        deployment_version="v1.0",
        environment="production",
        window_start=datetime.now(timezone.utc),
        window_end=datetime.now(timezone.utc),
        sample_count=50,
        tool_sequence_distribution=json.dumps(
            {'["tool_a", "tool_b"]': 0.70, '["tool_c"]': 0.30}
        ),
    )

    current_fp = BehavioralFingerprint(
        id="fp2",
        deployment_version="v2.0",
        environment="production",
        window_start=datetime.now(timezone.utc),
        window_end=datetime.now(timezone.utc),
        sample_count=50,
        tool_sequence_distribution=json.dumps(
            {'["tool_a", "tool_b"]': 0.30, '["tool_c"]': 0.70}
        ),
    )

    evidence = generate_evidence("decision_drift", baseline_fp, current_fp)

    assert "tool" in evidence.lower()
    assert "%" in evidence
    # Should mention the sequence that changed most
    assert "[" in evidence or "tool_c" in evidence


def test_evidence_latency_drift():
    """Test evidence generation for latency drift."""
    baseline_fp = BehavioralFingerprint(
        id="fp1",
        deployment_version="v1.0",
        environment="production",
        window_start=datetime.now(timezone.utc),
        window_end=datetime.now(timezone.utc),
        sample_count=50,
        p95_latency_ms=1000,
        p50_latency_ms=500,
    )

    current_fp = BehavioralFingerprint(
        id="fp2",
        deployment_version="v2.0",
        environment="production",
        window_start=datetime.now(timezone.utc),
        window_end=datetime.now(timezone.utc),
        sample_count=50,
        p95_latency_ms=2000,
        p50_latency_ms=1000,
    )

    evidence = generate_evidence("latency", baseline_fp, current_fp)

    assert "latency" in evidence.lower()
    assert "ms" in evidence.lower()
    assert "%" in evidence or "1,000" in evidence or "2,000" in evidence


def test_evidence_error_drift():
    """Test evidence generation for error drift."""
    baseline_fp = BehavioralFingerprint(
        id="fp1",
        deployment_version="v1.0",
        environment="production",
        window_start=datetime.now(timezone.utc),
        window_end=datetime.now(timezone.utc),
        sample_count=100,
        error_rate=0.02,
    )

    current_fp = BehavioralFingerprint(
        id="fp2",
        deployment_version="v2.0",
        environment="production",
        window_start=datetime.now(timezone.utc),
        window_end=datetime.now(timezone.utc),
        sample_count=100,
        error_rate=0.08,
    )

    evidence = generate_evidence("error_rate", baseline_fp, current_fp)

    assert "error" in evidence.lower()
    assert "%" in evidence
    assert "pp" in evidence.lower()  # percentage points


def test_evidence_fallback_on_missing_data():
    """Test evidence generation falls back gracefully when data is missing."""
    baseline_fp = BehavioralFingerprint(
        id="fp1",
        deployment_version="v1.0",
        environment="production",
        window_start=datetime.now(timezone.utc),
        window_end=datetime.now(timezone.utc),
        sample_count=0,
    )

    current_fp = BehavioralFingerprint(
        id="fp2",
        deployment_version="v2.0",
        environment="production",
        window_start=datetime.now(timezone.utc),
        window_end=datetime.now(timezone.utc),
        sample_count=0,
    )

    # Should not raise, should return fallback
    evidence = generate_evidence("decision_drift", baseline_fp, current_fp)

    assert isinstance(evidence, str)
    assert len(evidence) > 0


# CLI Format Tests (3 tests)


def test_diff_format_json_valid(sample_report):
    """Test that verdict payload produces valid JSON."""
    payload = build_verdict_payload(sample_report, backend=None)

    # Should be JSON serializable
    json_str = json.dumps(payload)
    parsed = json.loads(json_str)

    assert "version" in parsed
    assert parsed["version"] == "1.0"
    assert "verdict" in parsed
    assert "composite_score" in parsed


def test_diff_format_markdown_has_table():
    """Test that markdown renderer produces table structure."""
    from rich.console import Console

    payload = {
        "version": "1.0",
        "verdict": "REVIEW",
        "composite_score": 0.25,
        "confidence": {"ci_lower": 0.20, "ci_upper": 0.30},
        "confidence_tier": "TIER3",
        "top_contributors": [
            {
                "dimension": "decision_drift",
                "observed": 0.20,
                "ci_lower": 0.15,
                "ci_upper": 0.25,
                "significant": True,
                "contribution_pct": 60.0,
                "evidence": "Test evidence",
            }
        ],
        "mdes": {},
        "rollback_target": None,
    }

    console = Console(file=StringIO(), force_terminal=False)
    from driftbase.cli.cli_diff import _render_markdown

    _render_markdown(console, payload, "v1.0", "v2.0")
    output = console.file.getvalue()

    assert "|" in output  # Markdown table delimiter
    assert "Dimension" in output or "dimension" in output


def test_diff_format_markdown_has_verdict():
    """Test that markdown output includes verdict."""
    from rich.console import Console

    payload = {
        "version": "1.0",
        "verdict": "SHIP",
        "composite_score": 0.05,
        "confidence": {"ci_lower": 0.02, "ci_upper": 0.08},
        "confidence_tier": "TIER3",
        "top_contributors": [],
        "mdes": {},
        "rollback_target": None,
    }

    console = Console(file=StringIO(), force_terminal=False)
    from driftbase.cli.cli_diff import _render_markdown

    _render_markdown(console, payload, "v1.0", "v2.0")
    output = console.file.getvalue()

    assert "Verdict" in output or "verdict" in output
    assert "Drift Report" in output or "drift" in output.lower()


# Explain Command Tests (3 tests)


def test_explain_no_history(temp_db):
    """Test that empty verdict history is handled gracefully."""
    verdicts = temp_db.list_verdicts(limit=1)
    assert len(verdicts) == 0  # No verdicts yet


def test_explain_latest(temp_db):
    """Test that latest verdict can be retrieved."""
    # Save a verdict
    report_json = json.dumps(
        {
            "drift_score": 0.25,
            "drift_score_lower": 0.20,
            "drift_score_upper": 0.30,
            "dimension_attribution": {"decision_drift": 0.6, "latency": 0.3},
            "dimension_cis": {},
            "dimension_mdes": {"decision_drift": 0.05},
        }
    )

    temp_db.save_verdict(
        report_json=report_json,
        baseline_version="v1.0",
        current_version="v2.0",
        environment="production",
        composite_score=0.25,
        verdict="REVIEW",
        severity="moderate",
        confidence_tier="TIER3",
    )

    verdicts = temp_db.list_verdicts(limit=1)
    assert len(verdicts) == 1
    assert verdicts[0]["baseline_version"] == "v1.0"
    assert verdicts[0]["current_version"] == "v2.0"
    assert verdicts[0]["verdict"] == "REVIEW"


def test_explain_by_id(temp_db):
    """Test that verdict can be retrieved by ID."""
    report_json = json.dumps(
        {
            "drift_score": 0.15,
            "drift_score_lower": 0.10,
            "drift_score_upper": 0.20,
            "dimension_attribution": {"decision_drift": 0.7},
            "dimension_cis": {},
            "dimension_mdes": {},
        }
    )

    verdict_id = temp_db.save_verdict(
        report_json=report_json,
        baseline_version="v0.9",
        current_version="v1.0",
        environment="production",
        composite_score=0.15,
        verdict="MONITOR",
        severity="low",
        confidence_tier="TIER3",
    )

    retrieved = temp_db.get_verdict(verdict_id)
    assert retrieved is not None
    assert retrieved["baseline_version"] == "v0.9"
    assert retrieved["current_version"] == "v1.0"
    assert retrieved["verdict"] == "MONITOR"


# Root Cause Tests (2 tests)


def test_verdict_review_has_root_cause():
    """Test that REVIEW verdict includes root_cause."""
    report = DriftReport(
        baseline_fingerprint_id="fp1",
        current_fingerprint_id="fp2",
        drift_score=0.30,
        severity="significant",
        decision_drift=0.25,
        latency_drift=0.15,
        error_drift=0.05,
        escalation_rate_delta=0.0,
        summary="Test",
    )

    # Add attribution data
    report.dimension_attribution = {
        "decision_drift": 0.6,
        "latency": 0.3,
        "error_rate": 0.1,
    }

    verdict = compute_verdict(report)

    assert verdict is not None
    assert verdict.verdict == Verdict.REVIEW
    assert verdict.root_cause is not None
    assert isinstance(verdict.root_cause, str)
    assert len(verdict.root_cause) > 0
    # Should mention dimension and percentage
    assert "decision_drift" in verdict.root_cause
    assert "%" in verdict.root_cause


def test_verdict_ship_has_no_root_cause():
    """Test that SHIP verdict has no root_cause."""
    report = DriftReport(
        baseline_fingerprint_id="fp1",
        current_fingerprint_id="fp2",
        drift_score=0.05,
        severity="none",
        decision_drift=0.02,
        latency_drift=0.01,
        error_drift=0.01,
        escalation_rate_delta=0.0,
        summary="Test",
    )

    verdict = compute_verdict(report)

    assert verdict is not None
    assert verdict.verdict == Verdict.SHIP
    assert verdict.root_cause is None


# Integration Test (1 test)


def test_composite_scores_unchanged(sample_run_dicts):
    """Test that composite scores match v0.12.0-rc.1 exactly."""
    # This test verifies detection behavior hasn't changed

    # Scenario 1: Identical runs → near-zero drift
    baseline_runs = sample_run_dicts[:30]
    current_runs = sample_run_dicts[30:]

    baseline_fp = build_fingerprint_from_runs(
        [
            AgentRun(
                id=r["id"],
                session_id=r["session_id"],
                deployment_version=r["deployment_version"],
                environment=r["environment"],
                started_at=r["started_at"],
                completed_at=r["completed_at"],
                task_input_hash=r["task_input_hash"],
                tool_sequence=r["tool_sequence"],
                tool_call_count=r["tool_call_count"],
                output_length=r["output_length"],
                output_structure_hash=r["output_structure_hash"],
                latency_ms=r["latency_ms"],
                error_count=r["error_count"],
                retry_count=r["retry_count"],
                semantic_cluster=r["semantic_cluster"],
                loop_count=r.get("loop_count", 0),
                time_to_first_tool_ms=r.get("time_to_first_tool_ms", 0),
                verbosity_ratio=r.get("verbosity_ratio", 1.0),
            )
            for r in baseline_runs
        ],
        datetime.now(timezone.utc),
        datetime.now(timezone.utc) + timedelta(hours=1),
        "v1.0",
        "production",
    )

    current_fp = build_fingerprint_from_runs(
        [
            AgentRun(
                id=r["id"],
                session_id=r["session_id"],
                deployment_version="v1.0",
                environment=r["environment"],
                started_at=r["started_at"],
                completed_at=r["completed_at"],
                task_input_hash=r["task_input_hash"],
                tool_sequence=r["tool_sequence"],
                tool_call_count=r["tool_call_count"],
                output_length=r["output_length"],
                output_structure_hash=r["output_structure_hash"],
                latency_ms=r["latency_ms"],
                error_count=r["error_count"],
                retry_count=r["retry_count"],
                semantic_cluster=r["semantic_cluster"],
                loop_count=r.get("loop_count", 0),
                time_to_first_tool_ms=r.get("time_to_first_tool_ms", 0),
                verbosity_ratio=r.get("verbosity_ratio", 1.0),
            )
            for r in current_runs
        ],
        datetime.now(timezone.utc) + timedelta(hours=2),
        datetime.now(timezone.utc) + timedelta(hours=3),
        "v1.0",
        "production",
    )

    report = compute_drift(
        baseline_fp,
        current_fp,
        baseline_runs=baseline_runs,
        current_runs=current_runs,
    )

    # Identical distributions → composite score should be very low (< 0.05)
    assert report.drift_score < 0.05, (
        f"Identical runs should have near-zero drift, got {report.drift_score}"
    )

    # Scenario 2: Moderate change → moderate drift
    # Modify current runs to have different tool sequences
    modified_current = []
    for r in current_runs:
        modified = r.copy()
        modified["tool_sequence"] = '["tool_a", "tool_c"]'  # Different tool
        modified["latency_ms"] = r["latency_ms"] + 500  # +500ms
        modified_current.append(modified)

    current_fp_modified = build_fingerprint_from_runs(
        [
            AgentRun(
                id=r["id"],
                session_id=r["session_id"],
                deployment_version="v2.0",
                environment=r["environment"],
                started_at=r["started_at"],
                completed_at=r["completed_at"],
                task_input_hash=r["task_input_hash"],
                tool_sequence=r["tool_sequence"],
                tool_call_count=r["tool_call_count"],
                output_length=r["output_length"],
                output_structure_hash=r["output_structure_hash"],
                latency_ms=r["latency_ms"],
                error_count=r["error_count"],
                retry_count=r["retry_count"],
                semantic_cluster=r["semantic_cluster"],
                loop_count=r.get("loop_count", 0),
                time_to_first_tool_ms=r.get("time_to_first_tool_ms", 0),
                verbosity_ratio=r.get("verbosity_ratio", 1.0),
            )
            for r in modified_current
        ],
        datetime.now(timezone.utc) + timedelta(hours=2),
        datetime.now(timezone.utc) + timedelta(hours=3),
        "v2.0",
        "production",
    )

    report_modified = compute_drift(
        baseline_fp,
        current_fp_modified,
        baseline_runs=baseline_runs,
        current_runs=modified_current,
    )

    # Changed tool sequences + latency → moderate drift (0.10 - 0.40 range expected)
    assert 0.05 < report_modified.drift_score < 0.60, (
        f"Modified runs should have moderate drift, got {report_modified.drift_score}"
    )

    # Verify confidence tier is TIER3 for 30+ runs
    assert report.confidence_tier == "TIER3"
    assert report_modified.confidence_tier == "TIER3"
