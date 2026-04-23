"""
Tests for Phase 4: Ingestion Quality - Observation Trees and Blob Storage.

Covers:
- Blob storage (save, retrieve, size limits, truncation)
- Observation tree building (Langfuse and LangSmith)
- Tree-based tool extraction (additive behavior)
- Backward compatibility (runs without trees/blobs continue to work)
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from driftbase.backends.sqlite import RunBlob, SQLiteBackend
from driftbase.connectors.langfuse import _build_observation_tree as langfuse_build_tree
from driftbase.connectors.langsmith import (
    _build_observation_tree as langsmith_build_tree,
)
from driftbase.connectors.mapper import extract_tools_from_tree


class TestBlobStorage:
    """Tests for blob storage functionality."""

    def test_save_blob_basic(self, tmp_path: Path) -> None:
        """Test saving a blob with basic content."""
        db_path = tmp_path / "test.db"
        backend = SQLiteBackend(str(db_path))

        blob_id = backend.save_blob("run123", "input", "Hello, world!")

        assert blob_id != ""
        blob = backend.get_blob("run123", "input")
        assert blob is not None
        assert blob.content == "Hello, world!"
        assert blob.content_length == 13
        assert blob.truncated is False

    def test_save_blob_size_limit(self, tmp_path: Path) -> None:
        """Test blob truncation at size limit."""
        db_path = tmp_path / "test.db"

        # Set small size limit (must be >= 1024 due to min_val constraint)
        # and reset settings singleton
        with (
            patch.dict(os.environ, {"DRIFTBASE_BLOB_SIZE_LIMIT": "2048"}),
            patch("driftbase.config._settings", None),
        ):
            backend = SQLiteBackend(str(db_path))

            large_content = "x" * 5000
            blob_id = backend.save_blob("run123", "output", large_content)

            blob = backend.get_blob("run123", "output")
            assert blob is not None
            assert len(blob.content) == 2048  # Truncated to limit
            assert blob.content_length == 5000  # Original length preserved
            assert blob.truncated is True

    def test_save_blob_disabled(self, tmp_path: Path) -> None:
        """Test blob storage when disabled in config."""
        db_path = tmp_path / "test.db"

        with (
            patch.dict(os.environ, {"DRIFTBASE_BLOB_STORAGE": "false"}),
            patch("driftbase.config._settings", None),
        ):
            backend = SQLiteBackend(str(db_path))

            blob_id = backend.save_blob("run123", "input", "Test content")

            # Should return empty string when disabled
            assert blob_id == ""
            blob = backend.get_blob("run123", "input")
            assert blob is None

    def test_get_blobs_for_run(self, tmp_path: Path) -> None:
        """Test retrieving all blobs for a run."""
        db_path = tmp_path / "test.db"
        backend = SQLiteBackend(str(db_path))

        backend.save_blob("run123", "input", "Input text")
        backend.save_blob("run123", "output", "Output text")
        backend.save_blob("run456", "input", "Other run")

        blobs = backend.get_blobs_for_run("run123")
        assert len(blobs) == 2
        field_names = {b.field_name for b in blobs}
        assert field_names == {"input", "output"}

        blobs_456 = backend.get_blobs_for_run("run456")
        assert len(blobs_456) == 1

    def test_blob_hash_computation(self, tmp_path: Path) -> None:
        """Test that blob content hash is computed correctly."""
        db_path = tmp_path / "test.db"
        backend = SQLiteBackend(str(db_path))

        content = "Test content for hashing"
        backend.save_blob("run123", "input", content)

        blob = backend.get_blob("run123", "input")
        assert blob is not None
        assert blob.content_hash != ""
        assert len(blob.content_hash) == 64  # SHA-256 hex digest


class TestObservationTrees:
    """Tests for observation tree building."""

    def test_langfuse_tree_single_observation(self) -> None:
        """Test building tree from single Langfuse observation."""
        observations = [
            {
                "id": "obs1",
                "type": "generation",
                "name": "llm_call",
                "input": {"prompt": "Hello"},
                "output": {"text": "Hi"},
                "metadata": {},
            }
        ]

        tree = langfuse_build_tree(observations)

        assert tree is not None
        assert tree["id"] == "obs1"
        assert tree["type"] == "generation"
        assert tree["name"] == "llm_call"
        assert tree["children"] == []

    def test_langfuse_tree_parent_child(self) -> None:
        """Test building tree with parent-child relationships."""
        observations = [
            {
                "id": "obs1",
                "type": "span",
                "name": "root",
                "parent_observation_id": None,
            },
            {
                "id": "obs2",
                "type": "generation",
                "name": "child1",
                "parent_observation_id": "obs1",
            },
            {
                "id": "obs3",
                "type": "generation",
                "name": "child2",
                "parent_observation_id": "obs1",
            },
        ]

        tree = langfuse_build_tree(observations)

        assert tree is not None
        assert tree["id"] == "obs1"
        assert len(tree["children"]) == 2
        child_names = {c["name"] for c in tree["children"]}
        assert child_names == {"child1", "child2"}

    def test_langfuse_tree_empty_observations(self) -> None:
        """Test tree building with empty observations list."""
        tree = langfuse_build_tree([])
        assert tree is None

    def test_langsmith_tree_with_children(self) -> None:
        """Test building tree from LangSmith run with child runs."""
        root_run = {
            "id": "root1",
            "run_type": "chain",
            "name": "main_chain",
            "inputs": {},
            "outputs": {},
        }

        child_runs = [
            {
                "id": "child1",
                "run_type": "tool",
                "name": "search",
                "parent_run_id": "root1",
            },
            {
                "id": "child2",
                "run_type": "tool",
                "name": "write",
                "parent_run_id": "root1",
            },
        ]

        tree = langsmith_build_tree(root_run, child_runs)

        assert tree is not None
        assert tree["id"] == "root1"
        assert tree["type"] == "chain"
        assert len(tree["children"]) == 2
        child_names = {c["name"] for c in tree["children"]}
        assert child_names == {"search", "write"}


class TestTreeToolExtraction:
    """Tests for tree-based tool extraction."""

    def test_extract_tools_from_simple_tree(self) -> None:
        """Test extracting tools from simple tree."""
        tree = {
            "id": "root",
            "type": "span",
            "name": "search",
            "children": [
                {
                    "id": "child1",
                    "type": "tool",
                    "name": "google_search",
                    "children": [],
                },
                {"id": "child2", "type": "tool", "name": "write_file", "children": []},
            ],
        }

        tools = extract_tools_from_tree(tree)

        assert "search" in tools
        assert "google_search" in tools
        assert "write_file" in tools

    def test_extract_tools_additive_behavior(self) -> None:
        """Test that tree extraction finds MORE tools (additive)."""
        # Tree with span-type tools that legacy extraction would miss
        tree = {
            "id": "root",
            "type": "trace",
            "name": "trace_root",
            "children": [
                {"id": "gen1", "type": "generation", "name": "search", "children": []},
                {"id": "span1", "type": "span", "name": "bash", "children": []},
                {"id": "span2", "type": "span", "name": "write", "children": []},
            ],
        }

        tools = extract_tools_from_tree(tree)

        # Should find all 3 tools (generation + spans)
        assert "search" in tools
        assert "bash" in tools
        assert "write" in tools

    def test_extract_tools_skips_non_tools(self) -> None:
        """Test that tree extraction skips non-tool nodes."""
        tree = {
            "id": "root",
            "type": "span",
            "name": "llm",
            "children": [
                {"id": "child1", "type": "generation", "name": "chain", "children": []},
                {"id": "child2", "type": "tool", "name": "search", "children": []},
            ],
        }

        tools = extract_tools_from_tree(tree)

        # Should skip "llm" and "chain" but include "search"
        assert "llm" not in tools
        assert "chain" not in tools
        assert "search" in tools

    def test_extract_tools_empty_tree(self) -> None:
        """Test tool extraction with None tree."""
        tools = extract_tools_from_tree(None)
        assert tools == []


class TestBackwardCompatibility:
    """Tests for backward compatibility with existing runs."""

    def test_runs_without_trees_work(self, tmp_path: Path) -> None:
        """Test that runs without observation trees continue to work."""
        db_path = tmp_path / "test.db"
        backend = SQLiteBackend(str(db_path))

        # Write run without observation_tree_json
        run_data = {
            "id": "run123",
            "source": "test",
            "ingestion_source": "test",
            "session_id": "session1",
            "deployment_version": "v1.0",
            "version_source": "tag",
            "environment": "production",
            "model": "gpt-4",
            "started_at": datetime.now(tz=timezone.utc),
            "completed_at": datetime.now(tz=timezone.utc),
            "latency_ms": 100,
            "prompt_tokens": 10,
            "completion_tokens": 20,
            "error_count": 0,
            "tool_sequence": json.dumps(["search", "write"]),
            "tool_call_sequence": json.dumps(["search", "write"]),
            "tool_call_count": 2,
            "loop_count": 1,
            "time_to_first_tool_ms": 50,
            "output_length": 100,
            "semantic_cluster": "resolved",
            "verbosity_ratio": 2.0,
            "task_input_hash": "hash123",
            "output_structure_hash": "hash456",
            "raw_output": "Test output",
            "raw_prompt": "Test prompt",
            "retry_count": 0,
        }

        backend.write_runs([run_data])

        # Should retrieve run successfully
        retrieved = backend.get_run("run123")
        assert retrieved is not None
        assert retrieved["deployment_version"] == "v1.0"

    def test_runs_without_blobs_work(self, tmp_path: Path) -> None:
        """Test that runs without blobs continue to work."""
        db_path = tmp_path / "test.db"
        backend = SQLiteBackend(str(db_path))

        run_data = {
            "id": "run123",
            "source": "test",
            "ingestion_source": "test",
            "session_id": "session1",
            "deployment_version": "v1.0",
            "version_source": "tag",
            "environment": "production",
            "model": "gpt-4",
            "started_at": datetime.now(tz=timezone.utc),
            "completed_at": datetime.now(tz=timezone.utc),
            "latency_ms": 100,
            "prompt_tokens": 10,
            "completion_tokens": 20,
            "error_count": 0,
            "tool_sequence": json.dumps(["search"]),
            "tool_call_sequence": json.dumps(["search"]),
            "tool_call_count": 1,
            "loop_count": 1,
            "time_to_first_tool_ms": 50,
            "output_length": 100,
            "semantic_cluster": "resolved",
            "verbosity_ratio": 2.0,
            "task_input_hash": "hash123",
            "output_structure_hash": "hash456",
            "raw_output": "Output",
            "raw_prompt": "Prompt",
            "retry_count": 0,
        }

        backend.write_runs([run_data])

        # Get blobs (should be empty)
        blobs = backend.get_blobs_for_run("run123")
        assert blobs == []

        # Run should still be retrievable
        retrieved = backend.get_run("run123")
        assert retrieved is not None


class TestFullIngestionPipeline:
    """Integration tests for full ingestion pipeline."""

    def test_write_runs_with_blobs(self, tmp_path: Path) -> None:
        """Test that write_runs saves both run data and blobs."""
        db_path = tmp_path / "test.db"
        backend = SQLiteBackend(str(db_path))

        run_data = {
            "id": "run123",
            "source": "test",
            "ingestion_source": "connector",
            "session_id": "session1",
            "deployment_version": "v1.0",
            "version_source": "tag",
            "environment": "production",
            "model": "gpt-4",
            "started_at": datetime.now(tz=timezone.utc),
            "completed_at": datetime.now(tz=timezone.utc),
            "latency_ms": 100,
            "prompt_tokens": 10,
            "completion_tokens": 20,
            "error_count": 0,
            "tool_sequence": json.dumps(["search"]),
            "tool_call_sequence": json.dumps(["search"]),
            "tool_call_count": 1,
            "loop_count": 1,
            "time_to_first_tool_ms": 50,
            "output_length": 100,
            "semantic_cluster": "resolved",
            "verbosity_ratio": 2.0,
            "task_input_hash": "hash123",
            "output_structure_hash": "hash456",
            "raw_output": "Short output",
            "raw_prompt": "Short prompt",
            "raw_prompt_full": "This is the full input text that would be truncated",
            "raw_output_full": "This is the full output text that would be truncated",
            "retry_count": 0,
        }

        backend.write_runs([run_data])

        # Check run was saved
        run = backend.get_run("run123")
        assert run is not None

        # Check blobs were saved
        blobs = backend.get_blobs_for_run("run123")
        assert len(blobs) == 2
        field_names = {b.field_name for b in blobs}
        assert field_names == {"input", "output"}

        input_blob = backend.get_blob("run123", "input")
        assert input_blob is not None
        assert (
            input_blob.content == "This is the full input text that would be truncated"
        )

        output_blob = backend.get_blob("run123", "output")
        assert output_blob is not None
        assert (
            output_blob.content
            == "This is the full output text that would be truncated"
        )

    def test_write_runs_blob_failure_doesnt_block(self, tmp_path: Path) -> None:
        """Test that blob save failure doesn't block run ingestion."""
        db_path = tmp_path / "test.db"
        backend = SQLiteBackend(str(db_path))

        # Simulate blob save failure by using invalid data
        run_data = {
            "id": "run123",
            "source": "test",
            "ingestion_source": "connector",
            "session_id": "session1",
            "deployment_version": "v1.0",
            "version_source": "tag",
            "environment": "production",
            "model": "gpt-4",
            "started_at": datetime.now(tz=timezone.utc),
            "completed_at": datetime.now(tz=timezone.utc),
            "latency_ms": 100,
            "prompt_tokens": 10,
            "completion_tokens": 20,
            "error_count": 0,
            "tool_sequence": json.dumps(["search"]),
            "tool_call_sequence": json.dumps(["search"]),
            "tool_call_count": 1,
            "loop_count": 1,
            "time_to_first_tool_ms": 50,
            "output_length": 100,
            "semantic_cluster": "resolved",
            "verbosity_ratio": 2.0,
            "task_input_hash": "hash123",
            "output_structure_hash": "hash456",
            "raw_output": "Output",
            "raw_prompt": "Prompt",
            "raw_prompt_full": "Full prompt",
            "raw_output_full": "Full output",
            "retry_count": 0,
        }

        # Should not raise even if blob save fails
        backend.write_runs([run_data])

        # Run should still be saved
        run = backend.get_run("run123")
        assert run is not None
