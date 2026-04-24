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


class OllamaConfigError(ConfigError):
    """Raised when Ollama model resolution fails."""


def resolve_ollama_model(config: dict[str, Any], role: str = "classifier", cli_model: str | None = None) -> str:
    """Resolve the Ollama model name for a given role.

    Precedence (highest to lowest):
    1. cli_model — explicit --model flag
    2. classification.ollama.models.<role>
    3. classification.ollama.default_model
    4. Raise OllamaConfigError
    """
    if cli_model:
        return cli_model

    role_model = deep_get(config, f"classification.ollama.models.{role}")
    if role_model:
        return role_model

    default = deep_get(config, "classification.ollama.default_model")
    if default:
        return default

    raise OllamaConfigError(
        f"No Ollama model configured for role '{role}'. "
        "Set classification.ollama.models.{role} or classification.ollama.default_model in config."
    )
