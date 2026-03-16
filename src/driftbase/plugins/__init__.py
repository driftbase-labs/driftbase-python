"""
Driftbase plugin system.

Allows users to extend Driftbase with custom checks, reports, and integrations.
"""

from __future__ import annotations

import importlib
import logging
import sys
from pathlib import Path
from typing import Any, Callable, Protocol

logger = logging.getLogger(__name__)


class PluginHook(Protocol):
    """Protocol for plugin hook functions."""

    def __call__(self, context: dict[str, Any]) -> dict[str, Any] | None:
        """
        Execute plugin hook with given context.

        Args:
            context: Hook context data

        Returns:
            Modified context or None to continue unchanged
        """
        ...


class Plugin:
    """Base class for Driftbase plugins."""

    name: str = "unnamed"
    version: str = "0.0.0"
    description: str = ""
    author: str = ""

    def on_pre_diff(self, context: dict[str, Any]) -> dict[str, Any] | None:
        """
        Hook called before diff computation.

        Context contains:
            - baseline_runs: list[dict]
            - current_runs: list[dict]
            - baseline_version: str
            - current_version: str

        Return modified context or None to continue unchanged.
        """
        return None

    def on_post_diff(self, context: dict[str, Any]) -> dict[str, Any] | None:
        """
        Hook called after diff computation.

        Context contains:
            - drift_report: DriftReport
            - drift_score: float
            - baseline_version: str
            - current_version: str
        """
        return None

    def on_pre_report(self, context: dict[str, Any]) -> dict[str, Any] | None:
        """
        Hook called before report generation.

        Context contains:
            - drift_report: DriftReport
            - output_format: str (markdown, json, html)
            - output_path: Path | None
        """
        return None

    def on_post_report(self, context: dict[str, Any]) -> dict[str, Any] | None:
        """
        Hook called after report generation.

        Context contains:
            - report_content: str
            - output_format: str
            - output_path: Path | None
        """
        return None

    def on_drift_detected(self, context: dict[str, Any]) -> dict[str, Any] | None:
        """
        Hook called when drift exceeds threshold.

        Context contains:
            - drift_score: float
            - threshold: float
            - baseline_version: str
            - current_version: str
            - drift_report: DriftReport
        """
        return None

    def custom_check(self, context: dict[str, Any]) -> dict[str, Any]:
        """
        Custom check function for 'driftbase doctor' command.

        Context contains:
            - backend: Backend
            - config: Settings

        Return:
            {
                "status": "pass" | "warn" | "fail",
                "message": "Check description",
                "details": "Detailed information"
            }
        """
        return {
            "status": "pass",
            "message": f"{self.name} check",
            "details": "No issues found",
        }


class PluginManager:
    """Manages plugin loading and hook execution."""

    def __init__(self):
        self.plugins: list[Plugin] = []
        self._hooks: dict[str, list[PluginHook]] = {
            "pre_diff": [],
            "post_diff": [],
            "pre_report": [],
            "post_report": [],
            "drift_detected": [],
        }

    def load_plugins(self, plugin_dir: Path | None = None) -> None:
        """
        Load plugins from plugin directory.

        Plugins are Python files in ~/.driftbase/plugins/ that define a Plugin class.
        """
        if plugin_dir is None:
            try:
                plugin_dir = Path.home() / ".driftbase" / "plugins"
            except Exception:
                plugin_dir = Path(".driftbase") / "plugins"

        if not plugin_dir.exists():
            logger.debug(f"Plugin directory not found: {plugin_dir}")
            return

        # Add plugin directory to sys.path
        plugin_dir_str = str(plugin_dir)
        if plugin_dir_str not in sys.path:
            sys.path.insert(0, plugin_dir_str)

        # Load all Python files in plugin directory
        for plugin_file in plugin_dir.glob("*.py"):
            if plugin_file.name.startswith("_"):
                continue  # Skip private modules

            try:
                module_name = plugin_file.stem
                module = importlib.import_module(module_name)

                # Look for Plugin class
                for attr_name in dir(module):
                    attr = getattr(module, attr_name)
                    if (
                        isinstance(attr, type)
                        and issubclass(attr, Plugin)
                        and attr != Plugin
                    ):
                        plugin_instance = attr()
                        self.plugins.append(plugin_instance)
                        logger.info(
                            f"Loaded plugin: {plugin_instance.name} v{plugin_instance.version}"
                        )

                        # Register hooks
                        self._register_plugin_hooks(plugin_instance)

            except Exception as e:
                logger.warning(f"Failed to load plugin {plugin_file.name}: {e}")

    def _register_plugin_hooks(self, plugin: Plugin) -> None:
        """Register plugin hooks with the manager."""
        # Check which hooks are implemented
        if plugin.on_pre_diff.__func__ != Plugin.on_pre_diff:  # type: ignore
            self._hooks["pre_diff"].append(plugin.on_pre_diff)

        if plugin.on_post_diff.__func__ != Plugin.on_post_diff:  # type: ignore
            self._hooks["post_diff"].append(plugin.on_post_diff)

        if plugin.on_pre_report.__func__ != Plugin.on_pre_report:  # type: ignore
            self._hooks["pre_report"].append(plugin.on_pre_report)

        if plugin.on_post_report.__func__ != Plugin.on_post_report:  # type: ignore
            self._hooks["post_report"].append(plugin.on_post_report)

        if plugin.on_drift_detected.__func__ != Plugin.on_drift_detected:  # type: ignore
            self._hooks["drift_detected"].append(plugin.on_drift_detected)

    def execute_hook(self, hook_name: str, context: dict[str, Any]) -> dict[str, Any]:
        """
        Execute all registered hooks for a given hook point.

        Args:
            hook_name: Name of hook (pre_diff, post_diff, etc.)
            context: Hook context data

        Returns:
            Modified context (or original if no modifications)
        """
        hooks = self._hooks.get(hook_name, [])

        for hook in hooks:
            try:
                result = hook(context)
                if result is not None:
                    context.update(result)
            except Exception as e:
                logger.warning(f"Plugin hook {hook_name} failed: {e}")

        return context

    def get_custom_checks(self) -> list[tuple[str, Callable]]:
        """Get all custom check functions from plugins."""
        checks = []
        for plugin in self.plugins:
            if plugin.custom_check.__func__ != Plugin.custom_check:  # type: ignore
                checks.append((plugin.name, plugin.custom_check))
        return checks


# Global plugin manager instance
_plugin_manager: PluginManager | None = None


def get_plugin_manager() -> PluginManager:
    """Get the global plugin manager instance."""
    global _plugin_manager
    if _plugin_manager is None:
        _plugin_manager = PluginManager()
        # Auto-load plugins on first access
        try:
            _plugin_manager.load_plugins()
        except Exception as e:
            logger.debug(f"Failed to auto-load plugins: {e}")
    return _plugin_manager
