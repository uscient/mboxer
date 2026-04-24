from mboxer.config import load_config
from mboxer.limits import resolve_notebooklm_limits, validate_notebooklm_limits


def test_ultra_safe_effective_budget():
    config = load_config("config/mboxer.example.yaml")
    limits = resolve_notebooklm_limits(config, "ultra_safe")
    assert limits.max_sources == 600
    assert limits.reserved_sources == 100
    assert limits.effective_source_budget == 500


def test_override_precedence():
    config = load_config("config/mboxer.example.yaml")
    limits = resolve_notebooklm_limits(config, "ultra_safe", max_sources=123, reserved_sources=23)
    assert limits.max_sources == 123
    assert limits.reserved_sources == 23
    assert limits.effective_source_budget == 100


def test_validation_returns_warnings():
    config = load_config("config/mboxer.example.yaml")
    limits = resolve_notebooklm_limits(config, "ultra_safe")
    warnings = validate_notebooklm_limits(limits)
    assert isinstance(warnings, list)
