from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..security.policy import (
    default_export_profile,
    is_exportable,
    metadata_only,
    needs_scrub,
    resolve_export_profile,
)
from ..security.scrub import scrub_text


@dataclass
class ProjectionRecord:
    record: dict[str, Any]
    effective_profile: str
    was_scrubbed: bool


def prepare_projection(
    record: dict[str, Any],
    config: dict[str, Any],
    *,
    override_profile: str | None = None,
    record_profile: str | None = None,
    clear_body_word_count_for_metadata_only: bool = False,
) -> ProjectionRecord | None:
    """Prepare one exporter-ready message record according to export policy."""
    security = config.get("security") or {}
    config_default = default_export_profile(security.get("default_export_profile"))
    scrub_enabled = security.get("scrub_enabled", True)
    requested_profile = override_profile or record_profile or record.get("export_profile")
    effective = resolve_export_profile(requested_profile, config_default)
    if not is_exportable(effective):
        return None

    projected = dict(record)
    was_scrubbed = False
    if scrub_enabled and needs_scrub(effective):
        original = projected.get("body_text") or ""
        scrubbed = scrub_text(original, config)
        was_scrubbed = scrubbed != original
        projected["body_text"] = scrubbed
    elif metadata_only(effective):
        projected["body_text"] = None
        if clear_body_word_count_for_metadata_only:
            projected["body_word_count"] = None

    return ProjectionRecord(
        record=projected,
        effective_profile=effective,
        was_scrubbed=was_scrubbed,
    )
