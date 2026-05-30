from __future__ import annotations

EXPORT_PROFILES = ("raw", "reviewed", "scrubbed", "metadata-only", "exclude")
SAFE_DEFAULT_EXPORT_PROFILE = "scrubbed"


def default_export_profile(config_default: str | None) -> str:
    if config_default in EXPORT_PROFILES:
        return config_default
    return SAFE_DEFAULT_EXPORT_PROFILE


def resolve_export_profile(
    record_profile: str | None,
    config_default: str | None,
) -> str:
    default = default_export_profile(config_default)
    profile = record_profile or default
    if profile not in EXPORT_PROFILES:
        return default
    return profile


def is_exportable(profile: str) -> bool:
    return profile != "exclude"


def needs_scrub(profile: str) -> bool:
    # "reviewed" is a profile label only. mboxer does not currently track
    # human review state, so it remains subject to the same scrubbing path.
    return profile in ("scrubbed", "reviewed")


def metadata_only(profile: str) -> bool:
    return profile == "metadata-only"
