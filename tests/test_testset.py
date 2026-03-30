"""
Tests for testset command and YAML loading.
"""

from __future__ import annotations

import importlib.resources
import tempfile
import unittest
from pathlib import Path

import yaml
from click.testing import CliRunner

from driftbase.cli.cli import cli
from driftbase.local.use_case_inference import USE_CASE_WEIGHTS


class TestTestsetYAMLFiles(unittest.TestCase):
    """Test that all testset YAML files are valid and complete."""

    def test_all_use_cases_have_yaml_files(self) -> None:
        """All 14 use cases in USE_CASE_WEIGHTS should have corresponding YAML files."""
        for use_case in USE_CASE_WEIGHTS:
            with self.subTest(use_case=use_case):
                files = importlib.resources.files("driftbase.testsets")
                # Convert uppercase to lowercase for filename
                use_case_lower = use_case.lower()
                testset_file = files / f"{use_case_lower}.yaml"
                self.assertTrue(
                    testset_file.is_file(),
                    f"Missing YAML file for use case: {use_case}",
                )

    def test_yaml_files_load_without_error(self) -> None:
        """All YAML files should load without errors."""
        for use_case in USE_CASE_WEIGHTS:
            with self.subTest(use_case=use_case):
                files = importlib.resources.files("driftbase.testsets")
                # Convert uppercase to lowercase for filename
                use_case_lower = use_case.lower()
                testset_file = files / f"{use_case_lower}.yaml"

                if testset_file.is_file():
                    content = testset_file.read_text()
                    data = yaml.safe_load(content)
                    self.assertIsNotNone(data, f"Failed to load {use_case}.yaml")

    def test_yaml_structure_is_valid(self) -> None:
        """Each YAML file should have the required structure."""
        required_fields = ["use_case", "description", "total", "categories"]
        required_categories = [
            "core",
            "edge_cases",
            "boundary_cases",
            "linguistic_variety",
            "stress",
        ]

        for use_case in USE_CASE_WEIGHTS:
            with self.subTest(use_case=use_case):
                files = importlib.resources.files("driftbase.testsets")
                # Convert uppercase to lowercase for filename
                use_case_lower = use_case.lower()
                testset_file = files / f"{use_case_lower}.yaml"

                if testset_file.is_file():
                    content = testset_file.read_text()
                    data = yaml.safe_load(content)

                    # Check required top-level fields
                    for field in required_fields:
                        self.assertIn(
                            field, data, f"{use_case}.yaml missing field: {field}"
                        )

                    # Check use_case matches filename (lowercase)
                    self.assertEqual(
                        data["use_case"],
                        use_case_lower,
                        f"use_case field does not match filename in {use_case}.yaml",
                    )

                    # Check all required categories exist
                    categories = data.get("categories", {})
                    for category in required_categories:
                        self.assertIn(
                            category,
                            categories,
                            f"{use_case}.yaml missing category: {category}",
                        )

                        # Each category should have count and queries
                        category_data = categories[category]
                        self.assertIn(
                            "count",
                            category_data,
                            f"{use_case}.yaml category {category} missing count",
                        )
                        self.assertIn(
                            "queries",
                            category_data,
                            f"{use_case}.yaml category {category} missing queries",
                        )

    def test_exactly_50_queries_per_use_case(self) -> None:
        """Each use case should have exactly 50 queries."""
        for use_case in USE_CASE_WEIGHTS:
            with self.subTest(use_case=use_case):
                files = importlib.resources.files("driftbase.testsets")
                # Convert uppercase to lowercase for filename
                use_case_lower = use_case.lower()
                testset_file = files / f"{use_case_lower}.yaml"

                if testset_file.is_file():
                    content = testset_file.read_text()
                    data = yaml.safe_load(content)

                    # Check total field
                    self.assertEqual(
                        data.get("total"),
                        50,
                        f"{use_case}.yaml should have total=50",
                    )

                    # Count actual queries
                    total_queries = 0
                    categories = data.get("categories", {})
                    for _category_name, category_data in categories.items():
                        queries = category_data.get("queries", [])
                        total_queries += len(queries)

                    self.assertEqual(
                        total_queries,
                        50,
                        f"{use_case}.yaml has {total_queries} queries, expected 50",
                    )

    def test_category_counts_match_actual_queries(self) -> None:
        """Each category's count field should match the number of queries."""
        for use_case in USE_CASE_WEIGHTS:
            with self.subTest(use_case=use_case):
                files = importlib.resources.files("driftbase.testsets")
                # Convert uppercase to lowercase for filename
                use_case_lower = use_case.lower()
                testset_file = files / f"{use_case_lower}.yaml"

                if testset_file.is_file():
                    content = testset_file.read_text()
                    data = yaml.safe_load(content)

                    categories = data.get("categories", {})
                    for category_name, category_data in categories.items():
                        count = category_data.get("count", 0)
                        queries = category_data.get("queries", [])
                        actual_count = len(queries)

                        self.assertEqual(
                            actual_count,
                            count,
                            f"{use_case}.yaml category {category_name} has {actual_count} queries but count={count}",
                        )

    def test_no_duplicate_queries_within_use_case(self) -> None:
        """Each use case should not have duplicate queries."""
        for use_case in USE_CASE_WEIGHTS:
            with self.subTest(use_case=use_case):
                files = importlib.resources.files("driftbase.testsets")
                # Convert uppercase to lowercase for filename
                use_case_lower = use_case.lower()
                testset_file = files / f"{use_case_lower}.yaml"

                if testset_file.is_file():
                    content = testset_file.read_text()
                    data = yaml.safe_load(content)

                    all_queries = []
                    categories = data.get("categories", {})
                    for category_data in categories.values():
                        queries = category_data.get("queries", [])
                        all_queries.extend(queries)

                    # Check for duplicates
                    unique_queries = set(all_queries)
                    self.assertEqual(
                        len(all_queries),
                        len(unique_queries),
                        f"{use_case}.yaml has duplicate queries",
                    )

    def test_expected_category_sizes(self) -> None:
        """Categories should have the expected number of queries."""
        expected_counts = {
            "core": 20,
            "edge_cases": 10,
            "boundary_cases": 10,
            "linguistic_variety": 5,
            "stress": 5,
        }

        for use_case in USE_CASE_WEIGHTS:
            with self.subTest(use_case=use_case):
                files = importlib.resources.files("driftbase.testsets")
                # Convert uppercase to lowercase for filename
                use_case_lower = use_case.lower()
                testset_file = files / f"{use_case_lower}.yaml"

                if testset_file.is_file():
                    content = testset_file.read_text()
                    data = yaml.safe_load(content)

                    categories = data.get("categories", {})
                    for category_name, expected_count in expected_counts.items():
                        category_data = categories.get(category_name, {})
                        queries = category_data.get("queries", [])
                        actual_count = len(queries)

                        self.assertEqual(
                            actual_count,
                            expected_count,
                            f"{use_case}.yaml category {category_name} should have {expected_count} queries, has {actual_count}",
                        )


class TestTestsetCLI(unittest.TestCase):
    """Test the testset CLI commands."""

    def setUp(self) -> None:
        """Set up test runner."""
        self.runner = CliRunner()

    def test_testset_list_command(self) -> None:
        """The 'testset list' command should show all use cases."""
        result = self.runner.invoke(cli, ["testset", "list"])
        self.assertEqual(result.exit_code, 0, f"Command failed: {result.output}")

        # Check that all use cases are listed (check for first 12 chars to handle truncation)
        for use_case in USE_CASE_WEIGHTS:
            # Check for at least the first part of the use case name
            use_case_prefix = use_case[:12] if len(use_case) > 12 else use_case
            self.assertIn(
                use_case_prefix,
                result.output,
                f"Use case {use_case} not found in output",
            )

    def test_testset_inspect_command(self) -> None:
        """The 'testset inspect' command should show queries."""
        # Test with a known use case
        result = self.runner.invoke(
            cli, ["testset", "inspect", "--use-case", "customer_support"]
        )
        self.assertEqual(result.exit_code, 0, f"Command failed: {result.output}")
        self.assertIn("customer_support", result.output.lower())

    def test_testset_inspect_invalid_use_case(self) -> None:
        """The 'testset inspect' command should fail for invalid use case."""
        result = self.runner.invoke(
            cli, ["testset", "inspect", "--use-case", "invalid_use_case"]
        )
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("not found", result.output.lower())

    def test_testset_generate_command(self) -> None:
        """The 'testset generate' command should create a Python script."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_file = Path(tmpdir) / "test_queries.py"

            result = self.runner.invoke(
                cli,
                [
                    "testset",
                    "generate",
                    "--use-case",
                    "code_generation",
                    "--output",
                    str(output_file),
                    "--version",
                    "test_version",
                ],
            )

            self.assertEqual(result.exit_code, 0, f"Command failed: {result.output}")

            # Check that file was created
            self.assertTrue(output_file.exists(), "Output file was not created")

            # Check that file contains expected content
            content = output_file.read_text()
            self.assertIn("def YOUR_AGENT_FUNCTION", content)
            self.assertIn("@track", content)
            self.assertIn("code_generation", content)
            self.assertIn("test_version", content)

            # Check that file is valid Python
            try:
                compile(content, str(output_file), "exec")
            except SyntaxError as e:
                self.fail(f"Generated file has syntax errors: {e}")

    def test_testset_generate_default_output(self) -> None:
        """The 'testset generate' command should use default output filename."""
        with tempfile.TemporaryDirectory() as tmpdir:
            import os

            original_cwd = os.getcwd()
            try:
                os.chdir(tmpdir)

                result = self.runner.invoke(
                    cli,
                    [
                        "testset",
                        "generate",
                        "--use-case",
                        "financial",
                        "--version",
                        "v1.0",
                    ],
                )

                self.assertEqual(
                    result.exit_code, 0, f"Command failed: {result.output}"
                )

                # Check that default file was created
                default_file = Path(tmpdir) / "test_queries.py"
                self.assertTrue(
                    default_file.exists(), "Default output file was not created"
                )

            finally:
                os.chdir(original_cwd)


if __name__ == "__main__":
    unittest.main()
