from __future__ import annotations

from copy import deepcopy
from functools import cache
from importlib.resources import files
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG_PATH = Path("config/mboxer.example.yaml")
_MISSING = object()


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


def example_config_text() -> str:
    """Return the single bundled configuration example, also used as defaults."""
    return files("mboxer").joinpath("defaults.yaml").read_text(encoding="utf-8")


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    """Load an explicit file, a legacy local example, or bundled defaults.

    Explicit paths never fall back. A local config/mboxer.example.yaml retains
    precedence for existing checkouts; config/mboxer.yaml requires --config.
    """
    config_path = Path(path) if path is not None else DEFAULT_CONFIG_PATH
    if path is not None or config_path.exists():
        if not config_path.is_file():
            raise ConfigError(f"Config file not found: {config_path}")
        source = str(config_path)
        text = config_path.read_text(encoding="utf-8")
    else:
        source = "bundled defaults.yaml"
        text = example_config_text()

    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        # Do not echo configuration values in an error (they may contain secrets).
        raise ConfigError(f"Invalid YAML config: {source}") from exc
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ConfigError(f"Config root must be a mapping: {source}")
    return data


@cache
def _bundled_config() -> dict[str, Any]:
    """Parse packaged settings once; never expose this mutable cache to callers."""
    return yaml.safe_load(example_config_text())


def get_setting(config: dict[str, Any], dotted_path: str) -> Any:
    """Read one setting, using its bundled default only when the key is absent.

    This does not merge configurations or introduce bundled rules/profiles into
    a user config. Explicit false, zero, empty and null values remain explicit.
    """
    value = deep_get(config, dotted_path, _MISSING)
    if value is not _MISSING:
        return value
    default = deep_get(_bundled_config(), dotted_path, _MISSING)
    if default is _MISSING:
        raise ConfigError(f"No bundled default for setting: {dotted_path}")
    return deepcopy(default)


def get_path(
    config: dict[str, Any],
    dotted_path: str,
    override: str | Path | None = None,
    *,
    legacy_path: str | None = None,
    fallback_on_empty: bool = True,
) -> Path:
    """Resolve a path: CLI override, configured key, legacy key, bundled default.

    Attachment paths historically accept an empty string as the current directory;
    callers preserve that behavior with fallback_on_empty=False.
    """
    value = override or deep_get(config, dotted_path, _MISSING)
    if (value is _MISSING or (fallback_on_empty and not value)) and legacy_path:
        value = deep_get(config, legacy_path, _MISSING)
    if value is _MISSING or (fallback_on_empty and not value):
        value = get_setting({}, dotted_path)
    if not isinstance(value, (str, Path)):
        raise ConfigError(f"Config path must be a string: {dotted_path}")
    return Path(value)


def get_database_path(config: dict[str, Any], override: str | None = None) -> Path:
    """Resolve SQLite DB path, retaining the legacy project.default_database key."""
    return get_path(config, "paths.database", override, legacy_path="project.default_database")


def ensure_parent_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
