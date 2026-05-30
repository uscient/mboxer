"""Manifest generation for NotebookLM and JSONL exports."""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any

from .. import __version__

MANIFEST_SCHEMA_VERSION = "1"
TOOL_NAME = "mboxer"
REDACTION_POLICY_KEYS = (
    "redact_email_addresses",
    "redact_phone_numbers",
    "redact_ssn_like_numbers",
    "redact_credit_card_like_numbers",
    "redact_physical_addresses",
)

MANIFEST_FIELDS = [
    "manifest_schema_version",
    "tool_name",
    "tool_version",
    "export_kind",
    "account_key",
    "account_display_name",
    "account_email_address",
    "account_email_address_present",
    "source_database_present",
    "source_config_present",
    "source_database_path",
    "source_config_path",
    "source_file",
    "source_path",
    "generated_file",
    "generated_path",
    "generated_sha256",
    "category_path",
    "date_band",
    "source_pack",
    "message_count",
    "thread_count",
    "item_count",
    "candidate_message_count",
    "excluded_message_count",
    "total_message_count",
    "total_file_count",
    "date_min",
    "date_max",
    "word_count",
    "byte_count",
    "export_profile",
    "export_profile_override",
    "security_profile",
    "effective_default_export_profile",
    "scrub_enabled",
    "contains_scrubbed_content",
    "redaction_policy_json",
    "limit_profile",
    "limit_settings_json",
    "split_strategy_json",
    "export_format_json",
    "warnings_json",
    "created_at",
]


def _compact_json(value: Any) -> str:
    return json.dumps(value or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_manifest_path(path: str | Path | None) -> str:
    """Return a manifest-safe path reference without absolute local directories."""
    if not path:
        return ""
    p = Path(path)
    if p.is_absolute() or (p.parts and p.parts[0] == ".."):
        return p.name
    return p.as_posix()


def security_manifest_posture(config: dict[str, Any]) -> tuple[bool, dict[str, bool]]:
    security = config.get("security") or {}
    return (
        bool(security.get("scrub_enabled", True)),
        {key: bool(security.get(key, False)) for key in REDACTION_POLICY_KEYS},
    )


def _base_lineage_fields(
    *,
    export_kind: str,
    account_key: str,
    account_display_name: str | None,
    account_email_address: str | None,
    source_database_path: str | None,
    source_config_path: str | None,
    export_profile: str | None,
    security_profile: str | None,
    scrub_enabled: bool | None,
    redaction_policy: dict[str, Any] | None,
    limit_profile: str | None,
    limit_settings: dict[str, Any] | None,
    split_strategy: dict[str, Any] | None,
    export_format: dict[str, Any] | None,
    warnings: list[str] | None,
    created_at: str,
) -> dict[str, Any]:
    effective_default = export_profile or security_profile or "raw"
    return {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "tool_name": TOOL_NAME,
        "tool_version": __version__,
        "export_kind": export_kind,
        "account_key": account_key,
        "account_display_name": account_display_name or "",
        "account_email_address": "",
        "account_email_address_present": bool(account_email_address),
        "source_database_present": bool(source_database_path),
        "source_config_present": bool(source_config_path),
        "source_database_path": _safe_manifest_path(source_database_path),
        "source_config_path": _safe_manifest_path(source_config_path),
        "export_profile": export_profile or "",
        "export_profile_override": export_profile or "",
        "security_profile": security_profile or "",
        "effective_default_export_profile": effective_default,
        "scrub_enabled": "" if scrub_enabled is None else bool(scrub_enabled),
        "redaction_policy_json": _compact_json(redaction_policy),
        "limit_profile": limit_profile or "",
        "limit_settings_json": _compact_json(limit_settings),
        "split_strategy_json": _compact_json(split_strategy),
        "export_format_json": _compact_json(export_format),
        "warnings_json": json.dumps(warnings or [], ensure_ascii=False, sort_keys=True),
        "created_at": created_at,
    }


def build_notebooklm_manifest_rows(
    file_stats: list[dict[str, Any]],
    *,
    account_key: str,
    account_display_name: str | None,
    account_email_address: str | None,
    export_profile: str | None,
    security_profile: str | None,
    created_at: str,
    source_database_path: str | None = None,
    source_config_path: str | None = None,
    scrub_enabled: bool | None = None,
    redaction_policy: dict[str, Any] | None = None,
    limit_profile: str | None = None,
    limit_settings: dict[str, Any] | None = None,
    split_strategy: dict[str, Any] | None = None,
    export_format: dict[str, Any] | None = None,
    candidate_message_count: int = 0,
    excluded_message_count: int = 0,
    warnings: list[str] | None = None,
) -> list[dict[str, Any]]:
    base_fields = _base_lineage_fields(
        export_kind="notebooklm",
        account_key=account_key,
        account_display_name=account_display_name,
        account_email_address=account_email_address,
        source_database_path=source_database_path,
        source_config_path=source_config_path,
        export_profile=export_profile,
        security_profile=security_profile,
        scrub_enabled=scrub_enabled,
        redaction_policy=redaction_policy,
        limit_profile=limit_profile,
        limit_settings=limit_settings,
        split_strategy=split_strategy,
        export_format=export_format,
        warnings=warnings,
        created_at=created_at,
    )
    total_message_count = sum(int(stat.get("message_count", 0)) for stat in file_stats)
    total_file_count = len(file_stats)
    rows = []
    for stat in file_stats:
        fpath: Path = stat["path"]
        rows.append({
            **base_fields,
            "source_file": fpath.name,
            "source_path": _safe_manifest_path(fpath),
            "generated_file": fpath.name,
            "generated_path": _safe_manifest_path(fpath),
            "generated_sha256": stat.get("sha256") or _sha256_file(fpath),
            "category_path": stat.get("category_path", ""),
            "date_band": stat.get("date_band", ""),
            "source_pack": fpath.name,
            "message_count": stat.get("message_count", 0),
            "thread_count": stat.get("thread_count", 0),
            "item_count": stat.get("message_count", 0),
            "candidate_message_count": candidate_message_count,
            "excluded_message_count": excluded_message_count,
            "total_message_count": total_message_count,
            "total_file_count": total_file_count,
            "date_min": stat.get("date_min") or "",
            "date_max": stat.get("date_max") or "",
            "word_count": stat.get("word_count", 0),
            "byte_count": stat.get("byte_count", 0),
            "contains_scrubbed_content": bool(stat.get("contains_scrubbed_content", False)),
        })
    return rows


def build_jsonl_manifest_rows(
    *,
    account_key: str,
    account_display_name: str | None,
    account_email_address: str | None,
    out_path: Path,
    message_count: int,
    thread_count: int,
    date_min: str | None,
    date_max: str | None,
    word_count: int,
    byte_count: int,
    export_profile: str | None,
    security_profile: str | None,
    contains_scrubbed_content: bool = False,
    created_at: str = "",
    source_database_path: str | None = None,
    source_config_path: str | None = None,
    scrub_enabled: bool | None = None,
    redaction_policy: dict[str, Any] | None = None,
    export_format: dict[str, Any] | None = None,
    candidate_message_count: int = 0,
    excluded_message_count: int = 0,
    warnings: list[str] | None = None,
) -> list[dict[str, Any]]:
    base_fields = _base_lineage_fields(
        export_kind="jsonl",
        account_key=account_key,
        account_display_name=account_display_name,
        account_email_address=account_email_address,
        source_database_path=source_database_path,
        source_config_path=source_config_path,
        export_profile=export_profile,
        security_profile=security_profile,
        scrub_enabled=scrub_enabled,
        redaction_policy=redaction_policy,
        limit_profile=None,
        limit_settings=None,
        split_strategy=None,
        export_format=export_format,
        warnings=warnings,
        created_at=created_at,
    )
    return [{
        **base_fields,
        "source_file": out_path.name,
        "source_path": _safe_manifest_path(out_path),
        "generated_file": out_path.name,
        "generated_path": _safe_manifest_path(out_path),
        "generated_sha256": _sha256_file(out_path) if out_path.exists() else "",
        "category_path": "",
        "date_band": "",
        "source_pack": out_path.name,
        "message_count": message_count,
        "thread_count": thread_count,
        "item_count": message_count,
        "candidate_message_count": candidate_message_count,
        "excluded_message_count": excluded_message_count,
        "total_message_count": message_count,
        "total_file_count": 1 if out_path.exists() else 0,
        "date_min": date_min or "",
        "date_max": date_max or "",
        "word_count": word_count,
        "byte_count": byte_count,
        "contains_scrubbed_content": contains_scrubbed_content,
    }]


def write_notebooklm_manifest(
    out_dir: Path,
    account_key: str,
    rows: list[dict[str, Any]],
) -> tuple[Path, Path]:
    """Write manifest.csv and manifest.json under out_dir/<account_key>/."""
    acct_dir = out_dir / account_key
    acct_dir.mkdir(parents=True, exist_ok=True)
    csv_path = acct_dir / "manifest.csv"
    json_path = acct_dir / "manifest.json"

    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=MANIFEST_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    json_path.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")

    return csv_path, json_path


def write_jsonl_manifest(
    out_path: Path,
    rows: list[dict[str, Any]],
) -> Path:
    """Write <stem>.manifest.json alongside the JSONL output file."""
    manifest_path = out_path.with_suffix("").with_suffix(".manifest.json")
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifest_path
