from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG_PATH = Path("config/mboxer.example.yaml")


class ConfigError(RuntimeError):
    """Raised when config loading or validation fails."""


def deep_get(data: dict[str, Any], dotted_path: str, default: Any = None) -> Any:
    """Read a nested dict value with a dotted path."""
    current: Any = data
    for part in dotted_path.split("."):
        if not isinstance(current, dict) or part not in current:
            return default
        current = current[part]
    return current


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    """Load YAML config.

    If no config path is provided, use config/mboxer.example.yaml.
    """
    config_path = Path(path) if path else DEFAULT_CONFIG_PATH
    if not config_path.exists():
        raise ConfigError(f"Config file not found: {config_path}")

    with config_path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}

    if not isinstance(data, dict):
        raise ConfigError(f"Config root must be a mapping: {config_path}")

    return data


def get_database_path(config: dict[str, Any], override: str | None = None) -> Path:
    """Resolve SQLite DB path from override or config."""
    if override:
        return Path(override)

    configured = deep_get(config, "paths.database") or deep_get(config, "project.default_database")
    if not configured:
        configured = "var/mboxer.sqlite"
    return Path(configured)


def ensure_parent_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
