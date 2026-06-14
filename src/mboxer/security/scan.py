from __future__ import annotations

import sqlite3
from typing import Any

from .detectors import run_detectors


def scan_text(text: str) -> list[dict[str, Any]]:
    return run_detectors(text)


def _insert_finding_once(
    conn: sqlite3.Connection,
    *,
    account_id: int,
    message_db_id: int,
    finding: dict[str, Any],
) -> bool:
    existing = conn.execute(
        """
        SELECT 1
        FROM security_findings
        WHERE account_id = ?
          AND target_type = 'message'
          AND message_db_id = ?
          AND attachment_id IS NULL
          AND finding_type = ?
          AND detector = ?
          AND excerpt = ?
        LIMIT 1
        """,
        (
            account_id,
            message_db_id,
            finding["finding_type"],
            finding["detector"],
            finding["excerpt"],
        ),
    ).fetchone()
    if existing:
        return False

    conn.execute(
        "INSERT INTO security_findings "
        "(account_id, target_type, message_db_id, finding_type, severity, detector, excerpt) "
        "VALUES (?, 'message', ?, ?, ?, ?, ?)",
        (
            account_id,
            message_db_id,
            finding["finding_type"],
            finding["severity"],
            finding["detector"],
            finding["excerpt"],
        ),
    )
    return True


def run_security_scan(
    conn: sqlite3.Connection,
    config: dict[str, Any],
    *,
    account_id: int | None = None,
) -> dict[str, int]:
    scan_enabled = config.get("security", {}).get("scan_enabled", True)
    if not scan_enabled:
        print("Security scan disabled in config.")
        return {"scanned": 0, "findings": 0}

    query = "SELECT id, account_id, body_text FROM messages WHERE body_text IS NOT NULL"
    params: list[Any] = []
    if account_id is not None:
        query += " AND account_id = ?"
        params.append(account_id)

    rows = conn.execute(query, params).fetchall()
    total_findings = 0
    scanned = 0

    for msg_id, msg_account_id, body_text in rows:
        findings = scan_text(body_text)
        for finding in findings:
            if _insert_finding_once(
                conn,
                account_id=msg_account_id,
                message_db_id=msg_id,
                finding=finding,
            ):
                total_findings += 1
        scanned += 1

    conn.commit()
    return {"scanned": scanned, "findings": total_findings}
