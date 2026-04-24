from __future__ import annotations

import json
import sqlite3
from typing import Any

from .naming import normalize_category_path


def _load_rules(config: dict[str, Any]) -> list[dict[str, Any]]:
    return config.get("rules", [])


def _match_rule(rule: dict[str, Any], record: dict[str, Any]) -> bool:
    match = rule.get("match", {})
    sender = (record.get("sender") or "").lower()
    subject = (record.get("subject") or "").lower()
    try:
        recipients = json.loads(record.get("recipients_json") or "[]")
    except Exception:
        recipients = []
    all_addrs = [sender] + [r.lower() for r in recipients]

    for domain in match.get("from_domain", []):
        if any(addr.endswith(f"@{domain.lower()}") for addr in all_addrs):
            return True

    for fragment in match.get("from_contains", []):
        if any(fragment.lower() in addr for addr in all_addrs):
            return True

    for phrase in match.get("subject_contains", []):
        if phrase.lower() in subject:
            return True

    return False


def _apply_assignment(
    conn: sqlite3.Connection,
    record: dict[str, Any],
    rule: dict[str, Any],
    assign_key: str,
    account_id: int | None,
) -> None:
    assign = rule.get(assign_key, {})
    if not assign:
        return
    category_path = assign.get("category_path")
    if not category_path:
        return
    category_path = normalize_category_path(category_path)
    classifier_type = "rule" if assign_key == "assign" else "rule_hint"

    conn.execute(
        """
        INSERT OR IGNORE INTO classifications
          (account_id, target_type, message_db_id, thread_key, category_path,
           sensitivity, notebooklm_priority, export_profile,
           classifier_type, classifier_name, confidence)
        VALUES
          (:account_id, 'message', :msg_id, :thread_key, :category_path,
           :sensitivity, :notebooklm_priority, :export_profile,
           :classifier_type, :classifier_name, :confidence)
        """,
        {
            "account_id": account_id,
            "msg_id": record["id"],
            "thread_key": record.get("thread_key"),
            "category_path": category_path,
            "sensitivity": assign.get("sensitivity"),
            "notebooklm_priority": assign.get("notebooklm_priority"),
            "export_profile": assign.get("export_profile"),
            "classifier_type": classifier_type,
            "classifier_name": rule.get("name"),
            "confidence": 1.0 if assign_key == "assign" else 0.75,
        },
    )


def run_rule_classification(
    conn: sqlite3.Connection,
    config: dict[str, Any],
    *,
    level: str = "message",
    account_id: int | None = None,
) -> dict[str, int]:
    rules = _load_rules(config)
    if not rules:
        print("No rules defined in config.")
        return {"classified": 0, "skipped": 0}

    query = """
        SELECT m.id, m.account_id, m.source_id, m.mbox_key, m.message_id, m.thread_key,
               m.subject, m.sender, m.recipients_json, m.date_utc
        FROM messages m
        LEFT JOIN classifications c
          ON c.message_db_id = m.id AND c.classifier_type IN ('rule', 'rule_hint')
        WHERE c.id IS NULL
    """
    params: list[Any] = []
    if account_id is not None:
        query += " AND m.account_id = ?"
        params.append(account_id)

    rows = conn.execute(query, params).fetchall()
    cols = ["id", "account_id", "source_id", "mbox_key", "message_id", "thread_key",
            "subject", "sender", "recipients_json", "date_utc"]
    records = [dict(zip(cols, row)) for row in rows]

    classified = 0
    skipped = 0

    for record in records:
        rec_account_id = record.get("account_id")
        matched = False
        for rule in rules:
            if _match_rule(rule, record):
                if "assign" in rule:
                    _apply_assignment(conn, record, rule, "assign", rec_account_id)
                    matched = True
                    break
                elif "assign_hint" in rule:
                    _apply_assignment(conn, record, rule, "assign_hint", rec_account_id)
                    matched = True
                    break
        if matched:
            classified += 1
        else:
            skipped += 1

    conn.commit()
    return {"classified": classified, "skipped": skipped}
