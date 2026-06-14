from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..security.findings import ResidualFindingsBlocked, merge_counts
from ..security.policy import default_export_profile, resolve_export_profile, resolve_findings_policy
from .projection import prepare_projection


def export_jsonl(
    conn: sqlite3.Connection,
    config: dict[str, Any],
    out_path: Path,
    *,
    account_id: int | None = None,
    account_key: str = "default",
    account_display_name: str | None = None,
    account_email_address: str | None = None,
    export_profile: str | None = None,
    db_path: str | None = None,
    config_path: str | None = None,
    findings_policy: str | None = None,
) -> dict[str, Any]:
    jsonl_config = (config.get("exports") or {}).get("jsonl") or {}
    include_classification = jsonl_config.get("include_classification", True)
    security = config.get("security") or {}
    config_default = default_export_profile(security.get("default_export_profile"))
    security_profile = config_default
    effective_profile = resolve_export_profile(export_profile, config_default)
    policy = resolve_findings_policy(security.get("on_residual_findings"), override=findings_policy)

    if account_id is not None:
        rows = conn.execute(
            """
            SELECT m.id, m.message_id, m.thread_key, m.subject, m.sender,
                   m.recipients_json, m.cc_json, m.date_utc,
                   m.body_text, m.body_hash, m.body_chars, m.body_word_count,
                   m.attachment_count, s.source_name, s.source_slug
            FROM messages m
            JOIN mbox_sources s ON s.id = m.source_id
            WHERE m.account_id = ?
            ORDER BY m.date_utc NULLS LAST, m.id
            """,
            (account_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT m.id, m.message_id, m.thread_key, m.subject, m.sender,
                   m.recipients_json, m.cc_json, m.date_utc,
                   m.body_text, m.body_hash, m.body_chars, m.body_word_count,
                   m.attachment_count, s.source_name, s.source_slug
            FROM messages m
            JOIN mbox_sources s ON s.id = m.source_id
            ORDER BY m.date_utc NULLS LAST, m.id
            """
        ).fetchall()

    cols = [
        "id", "message_id", "thread_key", "subject", "sender",
        "recipients_json", "cc_json", "date_utc",
        "body_text", "body_hash", "body_chars", "body_word_count",
        "attachment_count", "source_name", "source_slug",
    ]

    classifications: dict[int, dict[str, Any]] = {}
    if include_classification:
        if account_id is not None:
            crows = conn.execute(
                "SELECT message_db_id, category_path, sensitivity, export_profile, confidence, classifier_type "
                "FROM classifications WHERE target_type = 'message' AND account_id = ?",
                (account_id,),
            ).fetchall()
        else:
            crows = conn.execute(
                "SELECT message_db_id, category_path, sensitivity, export_profile, confidence, classifier_type "
                "FROM classifications WHERE target_type = 'message'"
            ).fetchall()
        for cr in crows:
            mid = cr[0]
            if mid not in classifications:
                classifications[mid] = {
                    "category_path": cr[1],
                    "sensitivity": cr[2],
                    "export_profile": cr[3],
                    "confidence": cr[4],
                    "classifier_type": cr[5],
                }

    candidate_message_count = len(rows)
    excluded_message_count = 0
    any_scrubbed = False
    residual_total: dict[str, int] = {}
    projected_records: list[dict[str, Any]] = []

    for row in rows:
        record = dict(zip(cols, row))

        per_record_profile = (classifications.get(record["id"]) or {}).get("export_profile")
        projected = prepare_projection(
            record,
            config,
            override_profile=export_profile,
            record_profile=per_record_profile,
            clear_body_word_count_for_metadata_only=True,
        )
        if projected is None:
            excluded_message_count += 1
            continue

        record = projected.record
        merge_counts(residual_total, projected.residual)
        if projected.was_scrubbed:
            any_scrubbed = True

        record["account_key"] = account_key
        try:
            record["recipients"] = json.loads(record.pop("recipients_json") or "[]")
            record["cc"] = json.loads(record.pop("cc_json") or "[]")
        except Exception:
            record["recipients"] = []
            record["cc"] = []

        if include_classification and record["id"] in classifications:
            record["classification"] = classifications[record["id"]]

        projected_records.append(record)

    if policy == "block" and residual_total:
        raise ResidualFindingsBlocked(residual_total)

    warnings: list[str] = []
    if policy == "warn" and residual_total:
        warnings.append(f"residual detected-sensitive items in export: {residual_total}")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    thread_keys: set[str] = set()
    date_min: str | None = None
    date_max: str | None = None
    word_count = 0
    export_id = _start_export_run(conn, "jsonl", str(out_path), effective_profile, account_id)

    with out_path.open("w", encoding="utf-8") as f:
        for record in projected_records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            written += 1

            tk = record.get("thread_key")
            if tk:
                thread_keys.add(tk)
            d = record.get("date_utc")
            if d:
                if date_min is None or d < date_min:
                    date_min = d
                if date_max is None or d > date_max:
                    date_max = d
            word_count += record.get("body_word_count") or 0

    byte_count = out_path.stat().st_size if written else 0
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    from .manifest import build_jsonl_manifest_rows, security_manifest_posture, write_jsonl_manifest
    manifest_scrub_enabled, redaction_policy = security_manifest_posture(config)
    manifest_rows = build_jsonl_manifest_rows(
        account_key=account_key,
        account_display_name=account_display_name,
        account_email_address=account_email_address,
        out_path=out_path,
        message_count=written,
        thread_count=len(thread_keys),
        date_min=date_min,
        date_max=date_max,
        word_count=word_count,
        byte_count=byte_count,
        export_profile=export_profile,
        security_profile=security_profile,
        contains_scrubbed_content=any_scrubbed,
        created_at=now,
        source_database_path=db_path,
        source_config_path=config_path,
        scrub_enabled=manifest_scrub_enabled,
        redaction_policy=redaction_policy,
        export_format=jsonl_config,
        candidate_message_count=candidate_message_count,
        excluded_message_count=excluded_message_count,
        warnings=warnings,
        residual_scan_performed=True,
        residual_findings_total=sum(residual_total.values()),
        residual_findings_by_type=residual_total,
        residual_findings_policy=policy,
    )
    manifest_path = write_jsonl_manifest(out_path, manifest_rows)
    source_count = 1 if out_path.exists() else 0
    # Local operational reference, not safe lineage/event metadata.
    conn.execute(
        """
        INSERT INTO export_items (account_id, export_id, output_file, category_path, sequence)
        VALUES (?, ?, ?, ?, ?)
        """,
        (account_id, export_id, str(out_path), "", 1),
    )
    conn.execute(
        """
        UPDATE exports
        SET status = 'completed',
            finished_at = CURRENT_TIMESTAMP,
            source_count = ?,
            message_count = ?,
            metadata_json = ?
        WHERE id = ?
        """,
        (
            source_count,
            written,
            _jsonl_export_metadata_json(
                config=config,
                db_path=db_path,
                config_path=config_path,
                out_path=out_path,
                account_key=account_key,
                account_display_name=account_display_name,
                account_email_address=account_email_address,
                export_profile=export_profile,
                effective_profile=effective_profile,
                candidate_message_count=candidate_message_count,
                excluded_message_count=excluded_message_count,
                source_count=source_count,
                message_count=written,
                contains_scrubbed_content=any_scrubbed,
                generated_sha256=manifest_rows[0]["generated_sha256"],
                warnings=warnings,
                residual_scan_performed=True,
                residual_findings_total=sum(residual_total.values()),
                residual_findings_by_type=residual_total,
                residual_findings_policy=policy,
            ),
            export_id,
        ),
    )
    conn.commit()

    return {
        "export_id": export_id,
        "messages_written": written,
        "manifest_path": str(manifest_path),
        "contains_scrubbed_content": any_scrubbed,
        "candidate_message_count": candidate_message_count,
        "excluded_message_count": excluded_message_count,
        "residual_findings": residual_total,
        "residual_findings_total": sum(residual_total.values()),
        "residual_findings_policy": policy,
        "warnings": warnings,
    }


def _start_export_run(
    conn: sqlite3.Connection,
    export_type: str,
    output_path: str,
    export_profile: str,
    account_id: int | None,
) -> int:
    conn.execute(
        """
        INSERT INTO exports (account_id, export_type, export_profile, output_path)
        VALUES (?, ?, ?, ?)
        """,
        (account_id, export_type, export_profile, output_path),
    )
    conn.commit()
    return conn.execute("SELECT last_insert_rowid()").fetchone()[0]


def _jsonl_export_metadata_json(
    *,
    config: dict[str, Any],
    db_path: str | None,
    config_path: str | None,
    out_path: Path,
    account_key: str,
    account_display_name: str | None,
    account_email_address: str | None,
    export_profile: str | None,
    effective_profile: str,
    candidate_message_count: int,
    excluded_message_count: int,
    source_count: int,
    message_count: int,
    contains_scrubbed_content: bool,
    generated_sha256: str,
    warnings: list[str] | None,
    residual_scan_performed: bool,
    residual_findings_total: int,
    residual_findings_by_type: dict[str, int],
    residual_findings_policy: str,
) -> str:
    from .manifest import build_safe_export_run_metadata, security_manifest_posture

    scrub_enabled, redaction_policy = security_manifest_posture(config)
    jsonl_config = (config.get("exports") or {}).get("jsonl") or {}
    metadata = build_safe_export_run_metadata(
        export_kind="jsonl",
        account_key=account_key,
        account_display_name=account_display_name,
        account_email_address=account_email_address,
        source_database_path=db_path,
        source_config_path=config_path,
        output_path=out_path,
        export_profile=export_profile,
        effective_profile=effective_profile,
        security_profile=default_export_profile(
            (config.get("security") or {}).get("default_export_profile")
        ),
        scrub_enabled=scrub_enabled,
        redaction_policy=redaction_policy,
        export_format=jsonl_config,
        candidate_message_count=candidate_message_count,
        excluded_message_count=excluded_message_count,
        source_count=source_count,
        message_count=message_count,
        contains_scrubbed_content=contains_scrubbed_content,
        generated_sha256=generated_sha256,
        warnings=warnings,
        residual_scan_performed=residual_scan_performed,
        residual_findings_total=residual_findings_total,
        residual_findings_by_type=residual_findings_by_type,
        residual_findings_policy=residual_findings_policy,
    )
    return json.dumps(metadata, ensure_ascii=False, sort_keys=True)
