from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def export_jsonl(
    conn: sqlite3.Connection,
    config: dict[str, Any],
    out_path: Path,
    *,
    account_id: int | None = None,
    account_key: str = "default",
    account_display_name: str | None = None,
    account_email_address: str | None = None,
) -> dict[str, Any]:
    include_classification = config.get("exports", {}).get("jsonl", {}).get("include_classification", True)
    security_profile = (config.get("security") or {}).get("default_export_profile")

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

    out_path.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    thread_keys: set[str] = set()
    date_min: str | None = None
    date_max: str | None = None
    word_count = 0

    with out_path.open("w", encoding="utf-8") as f:
        for row in rows:
            record = dict(zip(cols, row))
            record["account_key"] = account_key
            try:
                record["recipients"] = json.loads(record.pop("recipients_json") or "[]")
                record["cc"] = json.loads(record.pop("cc_json") or "[]")
            except Exception:
                record["recipients"] = []
                record["cc"] = []
            if include_classification and record["id"] in classifications:
                record["classification"] = classifications[record["id"]]
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

    from .manifest import build_jsonl_manifest_rows, write_jsonl_manifest
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
        export_profile=None,
        security_profile=security_profile,
        created_at=now,
    )
    manifest_path = write_jsonl_manifest(out_path, manifest_rows)

    return {
        "messages_written": written,
        "manifest_path": str(manifest_path),
    }
