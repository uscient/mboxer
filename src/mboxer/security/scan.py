from __future__ import annotations

import re
import sqlite3
from typing import Any

_PATTERNS = {
    "email_address": re.compile(r"\b[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}\b"),
    "phone_number": re.compile(r"\b(?:\+?1[\s\-.]?)?\(?\d{3}\)?[\s\-.]?\d{3}[\s\-.]?\d{4}\b"),
    "ssn_like": re.compile(r"\b\d{3}[-\s]\d{2}[-\s]\d{4}\b"),
    "credit_card_like": re.compile(r"\b(?:\d{4}[\s\-]){3}\d{4}\b"),
}


def scan_text(text: str) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for finding_type, pattern in _PATTERNS.items():
        matches = pattern.findall(text)
        if matches:
            findings.append({
                "finding_type": finding_type,
                "severity": "medium",
                "detector": "regex",
                "excerpt": matches[0][:100],
                "count": len(matches),
            })
    return findings


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
