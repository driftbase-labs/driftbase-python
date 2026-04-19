"""
Driftbase - Behavioral drift detection for AI agents using Langfuse traces.

This package provides a CLI for detecting drift in AI agent behavior by analyzing
traces from Langfuse. All functionality is accessed via the `driftbase` command-line tool.

Usage:
    $ driftbase connect      # Connect to Langfuse and import traces
    $ driftbase diagnose     # Detect behavioral drift
    $ driftbase diff v1 v2   # Compare two versions
    $ driftbase history      # View behavioral history

For more information, run:
    $ driftbase --help

Or visit: https://driftbase.io/docs
"""

__version__ = "0.9.1"
__all__ = []  # All functionality accessed via CLI
