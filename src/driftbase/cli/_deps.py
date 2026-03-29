"""
Lazy import helpers for optional [semantic] dependencies.
Provides graceful error messages when optional deps are missing.
"""

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table


def safe_import_rich():
    """Import rich components (now part of core dependencies)."""
    return Console, Panel, Table


def safe_import_rich_extended():
    """Import additional rich components (now part of core dependencies)."""
    return Console, Panel, Table, Markdown, Prompt, Confirm
