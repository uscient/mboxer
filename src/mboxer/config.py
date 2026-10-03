from __future__ import annotations

from importlib.resources import files
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
