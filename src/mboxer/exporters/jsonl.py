from __future__ import annotations

import json
import sqlite3
import tempfile
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..accounts import validate_account_key
from ..records import decode_address_fields
from ..security.findings import ResidualFindingsBlocked, merge_counts
from ..security.policy import default_export_profile, resolve_export_profile, resolve_findings_policy
from .classification import resolve_message_classification
from .projection import prepare_projection
from .publication import publish_files


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
    """Project a consistent archive snapshot with memory bounded by one message.

    Payloads stay in a private staging directory until every message passes the
    residual policy. Unique thread identities use disposable, disk-backed SQLite
    so even archives containing only distinct threads do not grow a Python set.
    """
    validate_account_key(account_key)
    jsonl_config = (config.get("exports") or {}).get("jsonl") or {}
    include_classification = jsonl_config.get("include_classification", True)
    security = config.get("security") or {}
    security_profile = default_export_profile(security.get("default_export_profile"))
    effective_profile = resolve_export_profile(export_profile, security_profile)
    policy = resolve_findings_policy(security.get("on_residual_findings"), override=findings_policy)
    # Sort identifiers, not bodies: a SQLite sort must not materialize every
    # payload even when the account filter makes it prefer an account index.
    query = "SELECT m.id FROM messages m JOIN mbox_sources s ON s.id = m.source_id"
    record_query = """
        SELECT m.id, m.message_id, m.thread_key, m.subject, m.sender,
               m.recipients_json, m.cc_json, m.bcc_json, m.date_utc,
               m.body_text, m.body_hash, m.body_chars, m.body_word_count,
               m.attachment_count, s.source_name, s.source_slug
        FROM messages m JOIN mbox_sources s ON s.id = m.source_id WHERE m.id = ?
    """
    params: tuple[int, ...] = ()
    if account_id is not None:
        query += " WHERE m.account_id = ?"
        params = (account_id,)
    query += " ORDER BY m.date_utc NULLS LAST, m.id"
    cols = [
        "id", "message_id", "thread_key", "subject", "sender",
        "recipients_json", "cc_json", "bcc_json", "date_utc",
        "body_text", "body_hash", "body_chars", "body_word_count",
        "attachment_count", "source_name", "source_slug",
    ]
    candidate_message_count = excluded_message_count = written = word_count = 0
    any_scrubbed = False
    residual_total: dict[str, int] = {}
    date_min: str | None = None
    date_max: str | None = None
    manifest_path = out_path.with_suffix(".manifest.json")

    # An explicit read transaction keeps message bodies and classifications from
    # different source generations out of the same export. The existing API
    # commits pending caller writes on successful export; failure rolls back.
    conn.execute("SAVEPOINT mboxer_jsonl_export")
    try:
        with tempfile.TemporaryDirectory(prefix="mboxer-jsonl-") as directory:
            staging = Path(directory)
            staged_output = staging / "payload" / out_path.name
            staged_output.parent.mkdir()
            with closing(sqlite3.connect(staging / "threads.sqlite")) as threads:
                threads.execute("PRAGMA cache_size = -1024")
                threads.execute("CREATE TABLE threads (thread_key TEXT PRIMARY KEY) WITHOUT ROWID")
                with closing(conn.execute(query, params)) as rows, staged_output.open(
                    "w", encoding="utf-8"
                ) as handle:
                    for (message_id,) in rows:
                        candidate_message_count += 1
                        row = conn.execute(record_query, (message_id,)).fetchone()
                        record = dict(zip(cols, row))
                        classification = resolve_message_classification(
                            conn, record["id"], security_profile, override_profile=export_profile,
                        )
                        projected = prepare_projection(
                            record, config,
                            override_profile=export_profile,
                            record_profile=(classification or {}).get("export_profile"),
                            clear_body_word_count_for_metadata_only=True,
                        )
                        if projected is None:
                            excluded_message_count += 1
                            continue
                        record = projected.record
                        merge_counts(residual_total, projected.residual)
                        any_scrubbed = any_scrubbed or projected.was_scrubbed
                        record["account_key"] = account_key
                        record = decode_address_fields(record)
                        if include_classification and classification is not None:
                            record["classification"] = classification
                        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
                        written += 1
                        thread_key = record.get("thread_key")
                        if thread_key:
                            threads.execute(
                                "INSERT OR IGNORE INTO threads (thread_key) VALUES (?)", (thread_key,)
                            )
                        date = record.get("date_utc")
                        if date:
                            date_min = min(date_min, date) if date_min else date
                            date_max = max(date_max, date) if date_max else date
                        word_count += record.get("body_word_count") or 0
                thread_count = threads.execute("SELECT COUNT(*) FROM threads").fetchone()[0]

            if policy == "block" and residual_total:
                raise ResidualFindingsBlocked(residual_total)
            warnings = (
                [f"residual detected-sensitive items in export: {residual_total}"]
                if policy == "warn" and residual_total else []
            )
            byte_count = staged_output.stat().st_size
            now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            from .manifest import (
                build_jsonl_manifest_rows, safe_lineage_path,
                security_manifest_posture, write_jsonl_manifest,
            )
            manifest_scrub_enabled, redaction_policy = security_manifest_posture(config)
            manifest_rows = build_jsonl_manifest_rows(
                account_key=account_key,
                account_display_name=account_display_name,
                account_email_address=account_email_address,
                out_path=staged_output,
                message_count=written,
                thread_count=thread_count,
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
            for manifest_row in manifest_rows:
                manifest_row["source_path"] = safe_lineage_path(out_path)
                manifest_row["generated_path"] = safe_lineage_path(out_path)
            staged_manifest = write_jsonl_manifest(staged_output, manifest_rows)
            export_id = _start_export_run(conn, "jsonl", str(out_path), effective_profile, account_id)
            # Local operational references retain final paths, never staging paths.
            conn.execute(
                "INSERT INTO export_items (account_id, export_id, output_file, category_path, sequence) "
                "VALUES (?, ?, ?, '', 1)",
                (account_id, export_id, str(out_path)),
            )
            conn.execute(
                "UPDATE exports SET status = 'completed', finished_at = CURRENT_TIMESTAMP, "
                "source_count = 1, message_count = ?, metadata_json = ? WHERE id = ?",
                (written, _jsonl_export_metadata_json(
                    config=config, db_path=db_path, config_path=config_path,
                    out_path=out_path, account_key=account_key,
                    account_display_name=account_display_name,
                    account_email_address=account_email_address,
                    export_profile=export_profile, effective_profile=effective_profile,
                    candidate_message_count=candidate_message_count,
                    excluded_message_count=excluded_message_count, source_count=1,
                    message_count=written, contains_scrubbed_content=any_scrubbed,
                    generated_sha256=manifest_rows[0]["generated_sha256"], warnings=warnings,
                    residual_scan_performed=True, residual_findings_total=sum(residual_total.values()),
                    residual_findings_by_type=residual_total, residual_findings_policy=policy,
                ), export_id),
            )
            publish_files(out_path.parent, {
                out_path.name: staged_output, manifest_path.name: staged_manifest,
            }, commit=conn.commit)
    except BaseException:
        conn.rollback()
        raise

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
