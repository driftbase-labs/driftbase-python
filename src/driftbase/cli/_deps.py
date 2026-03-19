"""
Lazy import helpers for optional [analyze] dependencies.
Provides graceful error messages when heavy deps are missing.
"""

import sys


def check_analyze_deps() -> None:
    """Check if [analyze] dependencies are installed. Exit with helpful message if missing."""
    missing = []

    try:
        import numpy  # noqa: F401
    except ImportError:
        missing.append("numpy")

    try:
        import scipy  # noqa: F401
    except ImportError:
        missing.append("scipy")

    try:
        import rich  # noqa: F401
    except ImportError:
        missing.append("rich")

    if missing:
        print("\n❌ Missing required dependencies for drift analysis:", file=sys.stderr)
        print(f"   {', '.join(missing)}", file=sys.stderr)
        print("\nℹ️  Install the analysis dependencies with:", file=sys.stderr)
        print("   pip install 'driftbase[analyze]'", file=sys.stderr)
        print(
            "\n💡 The base install provides @track() decorator only.", file=sys.stderr
        )
        print(
            "   Use [analyze] for CLI commands (diff, demo, inspect, etc.).\n",
            file=sys.stderr,
        )
        sys.exit(1)


def safe_import_rich():
    """Import rich with graceful error if missing."""
    try:
        from rich.console import Console
        from rich.panel import Panel
        from rich.table import Table

        return Console, Panel, Table
    except ImportError:
        check_analyze_deps()  # Will exit with helpful message


def safe_import_rich_extended():
    """Import additional rich components with graceful error if missing."""
    try:
        from rich.console import Console
        from rich.panel import Panel
        from rich.table import Table
        from rich.markdown import Markdown
        from rich.prompt import Prompt, Confirm

        return Console, Panel, Table, Markdown, Prompt, Confirm
    except ImportError:
        check_analyze_deps()  # Will exit with helpful message


def safe_import_numpy():
    """Import numpy with graceful error if missing."""
    try:
        import numpy as np

        return np
    except ImportError:
        check_analyze_deps()  # Will exit with helpful message
