from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


def export_jsonl(
    conn: sqlite3.Connection,
    config: dict[str, Any],
    out_path: Path,
    *,
    account_id: int | None = None,
    account_key: str = "default",
) -> dict[str, int]:
    include_classification = config.get("exports", {}).get("jsonl", {}).get("include_classification", True)

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

    return {"messages_written": written}
