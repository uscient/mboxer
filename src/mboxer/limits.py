from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from .config import ConfigError, deep_get, get_setting

MB = 1024 * 1024
NOTEBOOKLM_SAFETY_MAX_BYTES = 200 * MB
NOTEBOOKLM_WARN_MAX_WORDS = 500_000


class ExportLimitError(ConfigError):
    """Raised when a complete export cannot satisfy its configured hard limits."""


@dataclass(frozen=True)
class NotebookLMLimits:
    profile_name: str
    max_sources: int
    reserved_sources: int
    target_sources: int
    max_words_per_source: int
    target_words_per_source: int
    max_bytes_per_source: int
    target_bytes_per_source: int
    max_messages_per_source: int

    @property
    def effective_source_budget(self) -> int:
        return max(0, self.max_sources - self.reserved_sources)


def mb_to_bytes(value: int | float) -> int:
    return int(value * MB)


def _require_int(profile: dict[str, Any], key: str) -> int:
    value = profile.get(key)
    if value is None:
        raise ConfigError(f"NotebookLM profile missing required key: {key}")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"NotebookLM profile key must be an integer: {key}") from exc


def resolve_notebooklm_limits(
    config: dict[str, Any],
    profile_name: str | None = None,
    *,
    max_sources: int | None = None,
    reserved_sources: int | None = None,
    target_sources: int | None = None,
    max_words: int | None = None,
    target_words: int | None = None,
    max_mb: int | None = None,
    target_mb: int | None = None,
) -> NotebookLMLimits:
    """Resolve NotebookLM profile from config, then apply CLI overrides."""
    default_profile = get_setting(config, "exports.notebooklm.profile")
    selected_name = profile_name or default_profile
    profiles = deep_get(config, "exports.notebooklm.profiles", {})
    if not isinstance(profiles, dict) or any(not isinstance(name, str) for name in profiles):
        raise ConfigError("exports.notebooklm.profiles must be a mapping of profile names")
    if not isinstance(selected_name, str) or selected_name not in profiles:
        available = ", ".join(sorted(profiles)) or "<none>"
        raise ConfigError(f"Unknown NotebookLM profile '{selected_name}'. Available: {available}")

    profile = profiles[selected_name]
    if not isinstance(profile, dict):
        raise ConfigError(f"NotebookLM profile must be a mapping: {selected_name}")
    limits = NotebookLMLimits(
        profile_name=selected_name,
        max_sources=_require_int(profile, "max_sources"),
        reserved_sources=_require_int(profile, "reserved_sources"),
        target_sources=_require_int(profile, "target_sources"),
        max_words_per_source=_require_int(profile, "max_words_per_source"),
        target_words_per_source=_require_int(profile, "target_words_per_source"),
        max_bytes_per_source=_require_int(profile, "max_bytes_per_source"),
        target_bytes_per_source=_require_int(profile, "target_bytes_per_source"),
        max_messages_per_source=_require_int(profile, "max_messages_per_source"),
    )

    overrides: dict[str, Any] = {
        "max_sources": max_sources,
        "reserved_sources": reserved_sources,
        "target_sources": target_sources,
        "max_words_per_source": max_words,
        "target_words_per_source": target_words,
        "max_bytes_per_source": mb_to_bytes(max_mb) if max_mb is not None else None,
        "target_bytes_per_source": mb_to_bytes(target_mb) if target_mb is not None else None,
    }
    return replace(limits, **{key: value for key, value in overrides.items() if value is not None})


def validate_notebooklm_limits(
    limits: NotebookLMLimits,
    *,
    allow_full_source_budget: bool = False,
    force: bool = False,
) -> list[str]:
    """Validate limits and return warnings. Raise ConfigError for hard failures."""
    warnings: list[str] = []

    if limits.max_sources <= 0:
        raise ConfigError("max_sources must be positive")
    if limits.reserved_sources < 0:
        raise ConfigError("reserved_sources cannot be negative")
    for key in (
        "target_sources", "max_words_per_source", "target_words_per_source",
        "max_bytes_per_source", "target_bytes_per_source", "max_messages_per_source",
    ):
        if getattr(limits, key) <= 0:
            raise ConfigError(f"{key} must be positive")
    if limits.effective_source_budget <= 0 and not allow_full_source_budget:
        raise ConfigError("effective source budget is zero; reduce reserved_sources")

    if limits.max_bytes_per_source > NOTEBOOKLM_SAFETY_MAX_BYTES and not force:
        raise ConfigError(
            "max_bytes_per_source exceeds 200 MB safety limit; pass --force to override"
        )

    if limits.max_words_per_source > NOTEBOOKLM_WARN_MAX_WORDS:
        warnings.append("max_words_per_source exceeds 500,000; NotebookLM may reject the source")

    if limits.target_sources > limits.effective_source_budget and not allow_full_source_budget:
        warnings.append(
            "target_sources exceeds max_sources - reserved_sources; exporter should cap at effective budget"
        )

    if limits.target_words_per_source > limits.max_words_per_source:
        warnings.append("target_words_per_source exceeds max_words_per_source")

    if limits.target_bytes_per_source > limits.max_bytes_per_source:
        warnings.append("target_bytes_per_source exceeds max_bytes_per_source")

    return warnings
