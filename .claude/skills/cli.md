# CLI Skill

**Read this skill before adding CLI commands or modifying cli/ modules.**

## CLI Structure

```
cli/
  main.py          — Entry point (imports cli from cli.py)
  cli.py           — Main CLI group + command registration
  cli_diff.py      — diff command
  cli_demo.py      — demo command
  cli_diagnose.py  — diagnose command
  cli_compare.py   — compare command
  cli_baseline.py  — baseline group (set, show, clear)
  cli_budget.py    — budgets command
  cli_changes.py   — changes command
  cli_chart.py     — chart command
  cli_cost.py      — cost command
  cli_deploy.py    — deploy command
  cli_doctor.py    — doctor command
  cli_export.py    — export/import commands
  cli_init.py      — init command
  cli_inspect.py   — inspect command
  cli_prune.py     — prune command
```

## Framework

Uses **Click** for argument parsing + **Rich** for terminal output.

```python
import click
from rich.console import Console
from rich.table import Table

console = Console()

@click.command()
@click.argument("version")
@click.option("--verbose", is_flag=True, help="Show detailed output")
def my_command(version: str, verbose: bool) -> None:
    """Command description (shows in --help)."""
    console.print(f"Running on version: {version}")
```

## Command Registration Pattern

All commands are registered in `cli.py`:

```python
from driftbase.cli.cli_diff import cmd_diff
from driftbase.cli.cli_demo import cmd_demo

@click.group()
@click.version_option()
def cli():
    """Pre-production analysis for AI agents — diff, diagnose, gate on budgets."""
    pass

# Register commands
cli.add_command(cmd_diff, name="diff")
cli.add_command(cmd_demo, name="demo")
```

**Never register commands anywhere except cli.py.**

## Command Aliases

Some commands have aliases defined in `cli.py`:

```python
cli.add_command(cmd_inspect, name="inspect")
cli.add_command(cmd_inspect, name="cat")  # Alias

cli.add_command(cmd_prune, name="prune")
cli.add_command(cmd_prune, name="clean")  # Alias
```

Aliases are registered as separate commands pointing to the same function.

## Adding a New Command

1. **Create `cli_mycommand.py`:**
   ```python
   import click
   from rich.console import Console

   console = Console()

   @click.command()
   @click.argument("arg1")
   @click.option("--flag", is_flag=True, help="Optional flag")
   def cmd_mycommand(arg1: str, flag: bool) -> None:
       """Short description of what this command does."""
       console.print(f"Running mycommand with arg1={arg1}")
       # ... implementation
   ```

2. **Register in `cli.py`:**
   ```python
   from driftbase.cli.cli_mycommand import cmd_mycommand

   # Inside cli() function or at module level
   cli.add_command(cmd_mycommand, name="mycommand")
   ```

3. **Update CLAUDE.md** to list the new command in the CLI commands section

4. **Update README.md** CLI reference table to include the new command

## Rich Markup Escaping

Rich interprets `[text]` as markup. To print literal brackets:

```python
# Wrong - Rich will try to interpret [v1.0] as markup
console.print("[v1.0]")

# Right - Escape brackets or use markup=False
console.print("\\[v1.0\\]")
# OR
console.print("[v1.0]", markup=False)
```

**Always escape brackets in version strings, file paths, or any user-provided text.**

## Exit Code Conventions

CLI commands should exit with meaningful codes:

```python
# Success
sys.exit(0)

# General error
sys.exit(1)

# Verdict-based exit codes (from verdict.py)
SHIP = 0
MONITOR = 10
REVIEW = 20
BLOCK = 30
```

Verdict commands should use `sys.exit(report.exit_code)` to propagate the verdict.

## Error Handling Pattern

```python
@click.command()
def cmd_something():
    try:
        # ... main logic
        console.print("[green]✓[/green] Success")
    except FileNotFoundError as e:
        console.print(f"[red]Error:[/red] File not found: {e}")
        sys.exit(1)
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        if verbose:
            console.print_exception()
        sys.exit(1)
```

**Never let exceptions propagate to the user without a friendly message.**

## Table Output Pattern

```python
from rich.table import Table

table = Table(title="Drift Report", show_header=True)
table.add_column("Dimension", style="cyan")
table.add_column("Score", justify="right", style="yellow")

table.add_row("decision_drift", f"{report.decision_drift:.3f}")
table.add_row("latency_drift", f"{report.latency_drift:.3f}")

console.print(table)
```

Use Rich tables for structured output. Use `console.print()` for simple output.

## Progress Indicators

```python
from rich.progress import track

for item in track(items, description="Processing..."):
    # ... process item
```

Use `track()` for loops with known length. Avoid for < 5 iterations (noise).

## Context Passing

Click context can pass data between commands:

```python
@click.group()
@click.pass_context
def cli(ctx: click.Context):
    ctx.ensure_object(dict)
    ctx.obj["backend"] = get_backend()

@click.command()
@click.pass_context
def subcommand(ctx: click.Context):
    backend = ctx.obj["backend"]
```

**Currently not used in driftbase CLI. Keep commands self-contained.**

## Configuration Access

```python
from driftbase.config import get_settings

settings = get_settings()
db_path = settings.DRIFTBASE_DB_PATH
sensitivity = settings.DRIFTBASE_SENSITIVITY
```

All config should flow through `get_settings()`, never read env vars directly in CLI code.

## Backend Access

```python
from driftbase.backends.factory import get_backend

backend = get_backend()
runs = backend.get_runs(deployment_version=version)
```

Always use the factory. Never instantiate backends directly.

## Doctor Command Pattern

`cli_doctor.py` is the health check command. It verifies:
- Database connectivity
- Required dependencies
- Configuration validity

When adding new features, update `doctor` if they have dependencies or config requirements.

## Formatting Guidelines

- Use `console.print()` for all output (not `print()`)
- Use Rich markup for colors: `[green]`, `[red]`, `[yellow]`, `[cyan]`, `[bold]`
- Use emoji sparingly (✓, ✗ for success/failure only)
- Use tables for structured data
- Use progress bars for long operations
- Escape brackets in user-provided strings

## Command Groups

Some commands are organized into groups:

```python
@click.group()
def baseline_group():
    """Baseline management commands."""
    pass

@baseline_group.command(name="set")
def baseline_set(version: str):
    """Set baseline version."""
    pass

# Register group
cli.add_command(baseline_group, name="baseline")
```

Results in: `driftbase baseline set <version>`

## Testing CLI Commands

Use Click's `CliRunner` for testing:

```python
from click.testing import CliRunner
from driftbase.cli.cli import cli

def test_diff_command():
    runner = CliRunner()
    result = runner.invoke(cli, ["diff", "v1.0", "v2.0"])
    assert result.exit_code == 0
    assert "drift_score" in result.output
```

**Never test CLI commands by shelling out. Always use CliRunner.**

## Never Do

- Don't use `print()` — always use `console.print()`
- Don't register commands outside `cli.py`
- Don't add logic to `cli.py` — keep it thin (registration only)
- Don't forget to escape Rich markup in dynamic strings
- Don't use `async` functions (Click commands are synchronous)
- Don't add commands without updating README.md

## Summary

- Click for parsing, Rich for output
- Register commands in `cli.py` only
- Escape `[brackets]` in Rich output
- Use exit codes: 0 (success), 1 (error), 10/20/30 (verdicts)
- Get config via `get_settings()`, backend via `get_backend()`
- Use CliRunner for testing, never shell out
