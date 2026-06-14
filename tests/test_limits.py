"""Pure-unit tests for NotebookLM limit resolution and validation.

``resolve_notebooklm_limits`` and ``validate_notebooklm_limits`` are the export
safety guardrails (source budget, the 200 MB per-source ceiling, override math).
These are table-driven and need no DB or filesystem.
"""
from __future__ import annotations

import pytest

from mboxer.config import ConfigError, load_config
from mboxer.limits import (
    MB,
    NotebookLMLimits,
    mb_to_bytes,
    resolve_notebooklm_limits,
    validate_notebooklm_limits,
)

PROFILE_KEYS = (
    "max_sources", "reserved_sources", "target_sources",
    "max_words_per_source", "target_words_per_source",
    "max_bytes_per_source", "target_bytes_per_source", "max_messages_per_source",
)


def _profile(**over):
    p = dict(
        max_sources=100, reserved_sources=10, target_sources=50,
        max_words_per_source=300_000, target_words_per_source=200_000,
        max_bytes_per_source=100_000_000, target_bytes_per_source=50_000_000,
        max_messages_per_source=1000,
    )
    p.update(over)
    return p


def _config(profile_name="p", profile=None):
    return {"exports": {"notebooklm": {
        "profile": profile_name,
        "profiles": {profile_name: profile if profile is not None else _profile()},
    }}}


def _limits(**over) -> NotebookLMLimits:
    base = dict(profile_name="t", **_profile())
    base.update(over)
    return NotebookLMLimits(**base)


# ── resolve_notebooklm_limits ─────────────────────────────────────────────────

@pytest.mark.unit
def test_resolve_uses_config_default_profile_when_name_is_none():
    limits = resolve_notebooklm_limits(_config(profile_name="p"), None)
    assert limits.profile_name == "p"
    assert limits.max_sources == 100


@pytest.mark.unit
def test_resolve_unknown_profile_raises_and_lists_available():
    with pytest.raises(ConfigError) as exc:
        resolve_notebooklm_limits(_config(profile_name="p"), "nope")
    assert "Unknown NotebookLM profile" in str(exc.value)
    assert "p" in str(exc.value)  # available profiles listed


@pytest.mark.unit
def test_resolve_missing_required_key_raises():
    bad = _profile()
    del bad["max_sources"]
    with pytest.raises(ConfigError, match="missing required key: max_sources"):
        resolve_notebooklm_limits(_config(profile=bad), "p")


@pytest.mark.unit
def test_resolve_non_integer_key_raises():
    with pytest.raises(ConfigError, match="must be an integer"):
        resolve_notebooklm_limits(_config(profile=_profile(max_sources="lots")), "p")


@pytest.mark.unit
@pytest.mark.parametrize("kwarg, field, value", [
    ("max_sources", "max_sources", 222),
    ("reserved_sources", "reserved_sources", 33),
    ("target_sources", "target_sources", 44),
    ("max_words", "max_words_per_source", 123_456),
    ("target_words", "target_words_per_source", 99_000),
])
def test_resolve_applies_scalar_overrides(kwarg, field, value):
    limits = resolve_notebooklm_limits(_config(), "p", **{kwarg: value})
    assert getattr(limits, field) == value


@pytest.mark.unit
@pytest.mark.parametrize("kwarg, field", [("max_mb", "max_bytes_per_source"),
                                          ("target_mb", "target_bytes_per_source")])
def test_resolve_converts_mb_overrides_to_bytes(kwarg, field):
    limits = resolve_notebooklm_limits(_config(), "p", **{kwarg: 200})
    assert getattr(limits, field) == 200 * MB


@pytest.mark.unit
def test_mb_to_bytes():
    assert mb_to_bytes(1) == 1024 * 1024
    assert mb_to_bytes(0) == 0


# ── validate_notebooklm_limits: hard failures (raise) ─────────────────────────

@pytest.mark.unit
def test_validate_clean_limits_has_no_warnings():
    assert validate_notebooklm_limits(_limits()) == []


@pytest.mark.unit
def test_validate_non_positive_max_sources_raises():
    with pytest.raises(ConfigError, match="max_sources must be positive"):
        validate_notebooklm_limits(_limits(max_sources=0))


@pytest.mark.unit
def test_validate_negative_reserved_raises():
    with pytest.raises(ConfigError, match="reserved_sources cannot be negative"):
        validate_notebooklm_limits(_limits(reserved_sources=-1))


@pytest.mark.unit
def test_validate_zero_effective_budget_raises_unless_allowed():
    z = _limits(max_sources=10, reserved_sources=10)  # budget == 0
    with pytest.raises(ConfigError, match="effective source budget is zero"):
        validate_notebooklm_limits(z)
    # ...but the escape hatch suppresses it
    assert isinstance(validate_notebooklm_limits(z, allow_full_source_budget=True), list)


@pytest.mark.unit
def test_validate_over_200mb_raises_unless_forced():
    big = _limits(max_bytes_per_source=300 * MB)
    with pytest.raises(ConfigError, match="200 MB"):
        validate_notebooklm_limits(big)
    assert isinstance(validate_notebooklm_limits(big, force=True), list)


# ── validate_notebooklm_limits: soft warnings (returned, not raised) ──────────

@pytest.mark.unit
def test_validate_warns_when_words_exceed_500k():
    warnings = validate_notebooklm_limits(_limits(max_words_per_source=600_000))
    assert any("500,000" in w for w in warnings)


@pytest.mark.unit
def test_validate_warns_when_target_sources_exceed_budget():
    # budget = 100 - 10 = 90; target 95 > 90
    warnings = validate_notebooklm_limits(_limits(target_sources=95))
    assert any("target_sources" in w for w in warnings)


@pytest.mark.unit
def test_validate_warns_when_target_words_exceed_max():
    warnings = validate_notebooklm_limits(
        _limits(target_words_per_source=400_000, max_words_per_source=300_000)
    )
    assert any("target_words_per_source" in w for w in warnings)


@pytest.mark.unit
def test_validate_warns_when_target_bytes_exceed_max():
    warnings = validate_notebooklm_limits(
        _limits(target_bytes_per_source=150 * MB, max_bytes_per_source=100 * MB)
    )
    assert any("target_bytes_per_source" in w for w in warnings)


# ── effective_source_budget property ──────────────────────────────────────────

@pytest.mark.unit
@pytest.mark.parametrize("max_s, reserved, expected", [
    (100, 25, 75),
    (10, 20, 0),   # never negative
    (600, 100, 500),
])
def test_effective_source_budget(max_s, reserved, expected):
    assert _limits(max_sources=max_s, reserved_sources=reserved).effective_source_budget == expected


# ── real shipped profile (smoke) ──────────────────────────────────────────────

@pytest.mark.integration
def test_example_config_ultra_safe_profile_resolves():
    config = load_config("config/mboxer.example.yaml")
    limits = resolve_notebooklm_limits(config, "ultra_safe")
    assert limits.max_sources == 600
    assert limits.reserved_sources == 100
    assert limits.effective_source_budget == 500
    assert validate_notebooklm_limits(limits) == []
