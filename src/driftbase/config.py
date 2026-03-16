"""
Lightweight config via os.environ with automatic .env loading and multi-source precedence.

Config Precedence (highest to lowest):
1. Environment variables (highest priority - CI/production overrides)
2. ./.driftbase/config (project-local, git-committed)
3. ./pyproject.toml [tool.driftbase] (if .driftbase/config doesn't exist)
4. ~/.driftbase/config.yml or ~/.driftbase/config (user-global)
5. Defaults (lowest priority)

Security best practices:
- Auto-loads .env file if present (for local development)
- Production environments should use real environment variables
- Sensible defaults for local developers (SQLite, no DATABASE_URL required)
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# Load .env file if present (idempotent - safe to call multiple times)
def _load_dotenv():
    """Load .env file for local development (production uses real env vars)."""
    try:
        from dotenv import load_dotenv

        env_path = Path.cwd() / ".env"
        if env_path.exists():
            load_dotenv(dotenv_path=env_path, override=False)
            logger.debug("Loaded environment from .env file")
    except ImportError:
        logger.debug("python-dotenv not available, skipping .env load")
    except Exception as e:
        logger.debug("Failed to load .env: %s", e)


# Load .env on module import (idempotent)
_load_dotenv()


def _env_bool(key: str, default: bool) -> bool:
    raw = os.environ.get(key)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _env_int(key: str, default: int, min_val: int | None = None) -> int:
    raw = os.environ.get(key)
    if raw is None:
        return default
    try:
        val = int(raw.strip())
        if min_val is not None and val < min_val:
            return min_val
        return val
    except ValueError:
        return default


def _env_float(key: str, default: float) -> float:
    raw = os.environ.get(key)
    if raw is None:
        return default
    try:
        return float(raw.strip())
    except ValueError:
        return default


def _resolve_db_path_with_fallbacks() -> str:
    """
    Resolve the database path with a robust fallback chain for environments
    where Path.home() fails (Docker, CI, restricted environments, etc.).

    Fallback chain:
    1. Try ~/.driftbase/runs.db (Path.home())
    2. Fall back to /tmp/driftbase/runs.db
    3. Fall back to ./.driftbase/runs.db (current working directory)

    This ensures the SDK works in restricted environments without requiring
    explicit DRIFTBASE_DB_PATH configuration.
    """
    # 1. Try Path.home() first (most common case)
    try:
        home_path = Path.home() / ".driftbase" / "runs.db"
        return str(home_path)
    except Exception as e:
        logger.debug("Path.home() failed (%s), trying /tmp fallback", e)

    # 2. Fall back to /tmp
    try:
        tmp_path = Path("/tmp") / "driftbase" / "runs.db"
        return str(tmp_path)
    except Exception as e:
        logger.debug("/tmp fallback failed (%s), trying cwd fallback", e)

    # 3. Final fallback to current working directory
    try:
        cwd_path = Path.cwd() / ".driftbase" / "runs.db"
        return str(cwd_path)
    except Exception as e:
        logger.error("All database path fallbacks failed: %s", e)
        raise RuntimeError(
            "Could not resolve a writable database path. "
            "Please set DRIFTBASE_DB_PATH explicitly to a writable location."
        ) from e


def _load_keyvalue_config(path: Path) -> dict[str, str]:
    """Load config from KEY=value format file (supports comments with #)."""
    config = {}
    if not path.exists():
        return config

    try:
        with path.open("r") as f:
            for line in f:
                line = line.strip()
                # Skip empty lines and comments
                if not line or line.startswith("#"):
                    continue
                # Parse KEY=value
                if "=" in line:
                    key, value = line.split("=", 1)
                    config[key.strip()] = value.strip()
    except Exception as e:
        logger.debug(f"Failed to load config from {path}: {e}")

    return config


def _load_yaml_config(path: Path) -> dict[str, Any]:
    """Load config from YAML file."""
    config = {}
    if not path.exists():
        return config

    try:
        import yaml

        with path.open("r") as f:
            data = yaml.safe_load(f) or {}
            # Convert to uppercase keys with DRIFTBASE_ prefix if not present
            for key, value in data.items():
                if not key.startswith("DRIFTBASE_"):
                    key = f"DRIFTBASE_{key.upper()}"
                config[key] = str(value)
    except ImportError:
        logger.debug("PyYAML not available, skipping YAML config")
    except Exception as e:
        logger.debug(f"Failed to load YAML config from {path}: {e}")

    return config


def _load_toml_config(path: Path) -> dict[str, Any]:
    """Load config from pyproject.toml [tool.driftbase] section."""
    config = {}
    if not path.exists():
        return config

    try:
        # Use tomllib (Python 3.11+) or tomli (3.9-3.10)
        if sys.version_info >= (3, 11):
            import tomllib
        else:
            try:
                import tomli as tomllib
            except ImportError:
                logger.debug("tomli not available, skipping TOML config")
                return config

        with path.open("rb") as f:
            data = tomllib.load(f)
            tool_config = data.get("tool", {}).get("driftbase", {})
            # Convert to uppercase keys with DRIFTBASE_ prefix if not present
            for key, value in tool_config.items():
                if not key.startswith("DRIFTBASE_"):
                    key = f"DRIFTBASE_{key.upper()}"
                config[key] = str(value)
    except Exception as e:
        logger.debug(f"Failed to load TOML config from {path}: {e}")

    return config


def _load_config_with_precedence() -> dict[str, str]:
    """
    Load configuration from multiple sources with precedence.

    Precedence (highest to lowest):
    1. Environment variables (already in os.environ)
    2. ./.driftbase/config (project-local)
    3. ./pyproject.toml [tool.driftbase] (if .driftbase/config doesn't exist)
    4. ~/.driftbase/config.yml or ~/.driftbase/config (user-global)
    5. Defaults (handled by Settings properties)

    Returns a merged dict of all non-env config sources.
    """
    merged = {}

    # 4. Load from user-global config (lowest precedence)
    try:
        home = Path.home() / ".driftbase"
        # Try YAML first, then KEY=value format
        if (home / "config.yml").exists():
            merged.update(_load_yaml_config(home / "config.yml"))
        elif (home / "config").exists():
            merged.update(_load_keyvalue_config(home / "config"))
    except Exception as e:
        logger.debug(f"Failed to load global config: {e}")

    # 3. Load from pyproject.toml if no local .driftbase/config
    cwd = Path.cwd()
    local_config_path = cwd / ".driftbase" / "config"
    pyproject_path = cwd / "pyproject.toml"

    if not local_config_path.exists() and pyproject_path.exists():
        merged.update(_load_toml_config(pyproject_path))

    # 2. Load from project-local config (higher precedence)
    if local_config_path.exists():
        merged.update(_load_keyvalue_config(local_config_path))

    # 1. Environment variables have highest precedence (handled in Settings)

    return merged


class Settings:
    """
    Read-only settings from environment with multi-source config precedence.
    All defaults are tuned for local dev.
    """

    def __init__(self) -> None:
        # Load config from all sources (precedence handled internally)
        self._config = _load_config_with_precedence()

        # Local SQLite path with fallback chain for restricted environments
        env_path = os.environ.get("DRIFTBASE_DB_PATH")
        if env_path:
            # User explicitly set the path, use it as-is (expand ~ if present)
            self._db_path = os.path.expanduser(env_path)
        elif "DRIFTBASE_DB_PATH" in self._config:
            self._db_path = os.path.expanduser(self._config["DRIFTBASE_DB_PATH"])
        else:
            # Use fallback chain for default path
            self._db_path = _resolve_db_path_with_fallbacks()

    def _get(self, key: str, default: Any = None) -> Any:
        """Get value from env or config file with precedence."""
        # Environment variables have highest precedence
        env_val = os.environ.get(key)
        if env_val is not None:
            return env_val
        # Fall back to config files
        return self._config.get(key, default)

    def _get_bool(self, key: str, default: bool) -> bool:
        """Get boolean value from env or config with precedence."""
        raw = self._get(key)
        if raw is None:
            return default
        return str(raw).strip().lower() in ("1", "true", "yes", "on")

    def _get_int(self, key: str, default: int, min_val: int | None = None) -> int:
        """Get integer value from env or config with precedence."""
        raw = self._get(key)
        if raw is None:
            return default
        try:
            val = int(str(raw).strip())
            if min_val is not None and val < min_val:
                return min_val
            return val
        except ValueError:
            return default

    def _get_float(self, key: str, default: float) -> float:
        """Get float value from env or config with precedence."""
        raw = self._get(key)
        if raw is None:
            return default
        try:
            return float(str(raw).strip())
        except ValueError:
            return default

    @property
    def DRIFTBASE_DB_PATH(self) -> str:
        """Path to the local SQLite database. Default: ~/.driftbase/runs.db"""
        return self._db_path

    @property
    def DRIFTBASE_OUTPUT_COLOR(self) -> bool:
        """Whether CLI output uses color. Default: True. Set DRIFTBASE_OUTPUT_COLOR=0 to disable."""
        return self._get_bool("DRIFTBASE_OUTPUT_COLOR", True)

    @property
    def DRIFTBASE_MIN_SAMPLES(self) -> int:
        """Minimum number of runs required to compute a fingerprint. Default: 10."""
        return self._get_int("DRIFTBASE_MIN_SAMPLES", 10, min_val=1)

    @property
    def DRIFTBASE_BASELINE_DAYS(self) -> int:
        """Number of days for temporal baseline window. Default: 7."""
        return self._get_int("DRIFTBASE_BASELINE_DAYS", 7, min_val=1)

    @property
    def DRIFTBASE_CURRENT_HOURS(self) -> int:
        """Number of hours for current window in temporal drift. Default: 24."""
        return self._get_int("DRIFTBASE_CURRENT_HOURS", 24, min_val=1)

    @property
    def DRIFTBASE_LOCAL_RETENTION_LIMIT(self) -> int:
        """Maximum number of runs to keep in the local SQLite database. Default: 10000."""
        return self._get_int("DRIFTBASE_LOCAL_RETENTION_LIMIT", 10000, min_val=1)

    @property
    def DRIFTBASE_SCRUB_PII(self) -> bool:
        """
        Enable PII scrubbing by default.
        Critical for EU AI Act and GDPR compliance.
        Set DRIFTBASE_SCRUB_PII=0 to disable.
        """
        return self._get_bool("DRIFTBASE_SCRUB_PII", True)

    # New config keys for CLI improvements
    @property
    def DRIFTBASE_BASELINE_VERSION(self) -> str | None:
        """Pinned baseline version for drift comparison. Default: None."""
        return self._get("DRIFTBASE_BASELINE_VERSION")

    @property
    def DRIFTBASE_DRIFT_THRESHOLD(self) -> float:
        """Default drift threshold for diff/report/watch commands. Default: 0.20."""
        return self._get_float("DRIFTBASE_DRIFT_THRESHOLD", 0.20)

    @property
    def DRIFTBASE_WATCH_INTERVAL(self) -> int:
        """Default watch poll interval in seconds. Default: 5."""
        return self._get_int("DRIFTBASE_WATCH_INTERVAL", 5, min_val=1)

    @property
    def DRIFTBASE_WATCH_THRESHOLD(self) -> float:
        """Default watch drift threshold. Default: 0.20."""
        return self._get_float("DRIFTBASE_WATCH_THRESHOLD", 0.20)

    @property
    def DRIFTBASE_GIT_TAGGING(self) -> bool:
        """Enable automatic git metadata tagging for runs. Default: False."""
        return self._get_bool("DRIFTBASE_GIT_TAGGING", False)

    @property
    def DRIFTBASE_WATCH_WEBHOOK_URL(self) -> str | None:
        """Webhook URL for watch alerts. Default: None."""
        return self._get("DRIFTBASE_WATCH_WEBHOOK_URL")

    @property
    def DRIFTBASE_ENVIRONMENT(self) -> str:
        """Default environment for runs. Default: production."""
        return self._get("DRIFTBASE_ENVIRONMENT", "production")


_settings: Settings | None = None


def get_settings() -> Settings:
    """Return the singleton Settings instance (reads from os.environ, no .env file)."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


# Known config keys and their types for validation
KNOWN_CONFIG_KEYS = {
    "DRIFTBASE_DB_PATH": str,
    "DRIFTBASE_OUTPUT_COLOR": bool,
    "DRIFTBASE_MIN_SAMPLES": int,
    "DRIFTBASE_BASELINE_DAYS": int,
    "DRIFTBASE_CURRENT_HOURS": int,
    "DRIFTBASE_LOCAL_RETENTION_LIMIT": int,
    "DRIFTBASE_SCRUB_PII": bool,
    "DRIFTBASE_BASELINE_VERSION": str,
    "DRIFTBASE_DRIFT_THRESHOLD": float,
    "DRIFTBASE_WATCH_INTERVAL": int,
    "DRIFTBASE_WATCH_THRESHOLD": float,
    "DRIFTBASE_WATCH_WEBHOOK_URL": str,
    "DRIFTBASE_ENVIRONMENT": str,
    "DRIFTBASE_GIT_TAGGING": bool,
}


def validate_config_key(key: str, value: str) -> tuple[bool, str]:
    """
    Validate a config key and value.

    Returns (is_valid, error_message). If valid, error_message is empty.
    """
    if key not in KNOWN_CONFIG_KEYS:
        return False, f"Unknown config key: {key}"

    expected_type = KNOWN_CONFIG_KEYS[key]

    try:
        if expected_type == bool:
            # Validate boolean format
            if value.lower() not in ("0", "1", "true", "false", "yes", "no", "on", "off"):
                return False, f"Invalid boolean value for {key}: {value}"
        elif expected_type == int:
            # Validate integer format
            int(value)
        elif expected_type == float:
            # Validate float format
            float(value)
        # str needs no validation
    except ValueError as e:
        return False, f"Invalid value for {key}: {e}"

    return True, ""


def save_config(key: str, value: str, scope: str = "global") -> Path:
    """
    Save a config key-value pair to the appropriate config file.

    Args:
        key: Config key (e.g., "DRIFTBASE_BASELINE_VERSION")
        value: Config value as string
        scope: "global" for ~/.driftbase/config, "local" for ./.driftbase/config

    Returns:
        Path to the config file that was written

    Raises:
        ValueError: If validation fails
    """
    # Validate first
    is_valid, error = validate_config_key(key, value)
    if not is_valid:
        raise ValueError(error)

    # Determine config path
    if scope == "global":
        try:
            config_dir = Path.home() / ".driftbase"
        except Exception as e:
            raise RuntimeError(f"Cannot access home directory: {e}")
    else:  # local
        config_dir = Path.cwd() / ".driftbase"

    # Ensure directory exists
    config_dir.mkdir(parents=True, exist_ok=True)

    # Detect which format to use (prefer existing format)
    yaml_path = config_dir / "config.yml"
    keyvalue_path = config_dir / "config"

    if yaml_path.exists():
        # Load existing YAML and update
        existing = _load_yaml_config(yaml_path)
        # Convert key from DRIFTBASE_FOO to foo for YAML format
        yaml_key = key.replace("DRIFTBASE_", "").lower()
        existing[yaml_key] = value

        # Write back as YAML
        try:
            import yaml

            with yaml_path.open("w") as f:
                f.write("# Driftbase configuration (generated by driftbase init)\n")
                yaml.safe_dump(existing, f, default_flow_style=False, sort_keys=True)
            return yaml_path
        except ImportError:
            # Fall back to keyvalue format if PyYAML not available
            pass

    # Use KEY=value format
    existing = _load_keyvalue_config(keyvalue_path)
    existing[key] = value

    with keyvalue_path.open("w") as f:
        f.write("# Driftbase configuration\n")
        f.write("# Auto-generated by driftbase config set\n\n")
        for k, v in sorted(existing.items()):
            f.write(f"{k}={v}\n")

    return keyvalue_path


def delete_config_key(key: str, scope: str = "global") -> bool:
    """
    Delete a config key from the config file.

    Args:
        key: Config key to delete
        scope: "global" or "local"

    Returns:
        True if key was found and deleted, False if key was not found
    """
    # Determine config path
    if scope == "global":
        try:
            config_path = Path.home() / ".driftbase" / "config"
        except Exception:
            return False
    else:  # local
        config_path = Path.cwd() / ".driftbase" / "config"

    if not config_path.exists():
        return False

    # Read existing config
    existing = _load_keyvalue_config(config_path)

    # Check if key exists
    if key not in existing:
        return False

    # Remove key
    del existing[key]

    # Write back
    with config_path.open("w") as f:
        f.write("# Driftbase configuration\n")
        f.write("# Auto-generated by driftbase config set\n\n")
        for k, v in sorted(existing.items()):
            f.write(f"{k}={v}\n")

    return True


def get_config_source(key: str) -> str:
    """
    Determine where a config value is coming from.

    Returns: "env", "local", "pyproject.toml", "global", or "default"
    """
    # Check environment
    if key in os.environ:
        return "env"

    # Check local config
    local_path = Path.cwd() / ".driftbase" / "config"
    if local_path.exists():
        local_config = _load_keyvalue_config(local_path)
        if key in local_config:
            return "local"

    # Check pyproject.toml (only if local config doesn't exist)
    if not local_path.exists():
        pyproject_path = Path.cwd() / "pyproject.toml"
        if pyproject_path.exists():
            toml_config = _load_toml_config(pyproject_path)
            if key in toml_config:
                return "pyproject.toml"

    # Check global config
    try:
        home = Path.home() / ".driftbase"
        if (home / "config.yml").exists():
            global_config = _load_yaml_config(home / "config.yml")
            if key in global_config:
                return "global"
        elif (home / "config").exists():
            global_config = _load_keyvalue_config(home / "config")
            if key in global_config:
                return "global"
    except Exception:
        pass

    return "default"
