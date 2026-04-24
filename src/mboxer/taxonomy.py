from __future__ import annotations

import sqlite3
from typing import Any

from .naming import normalize_category_path


def seed_categories_from_config(
    conn: sqlite3.Connection,
    config: dict[str, Any],
    *,
    account_id: int | None = None,
) -> int:
    """Seed locked categories from config as global (account_id=None) or account-specific."""
    locked = config.get("taxonomy", {}).get("locked_categories", [])
    added = 0
    for raw_path in locked:
        path = normalize_category_path(raw_path)
        parts = path.split("/")
        display_name = parts[-1].replace("-", " ").title()
        parent_path = "/".join(parts[:-1]) if len(parts) > 1 else None

        if account_id is None:
            existing = conn.execute(
                "SELECT id FROM categories WHERE account_id IS NULL AND path = ?", (path,)
            ).fetchone()
        else:
            existing = conn.execute(
                "SELECT id FROM categories WHERE account_id = ? AND path = ?",
                (account_id, path),
            ).fetchone()

        if not existing:
            conn.execute(
                "INSERT INTO categories (account_id, path, display_name, parent_path, is_locked, is_active) "
                "VALUES (?, ?, ?, ?, 1, 1)",
                (account_id, path, display_name, parent_path),
            )
            added += 1

    conn.commit()
    return added


def ensure_category(
    conn: sqlite3.Connection,
    path: str,
    *,
    account_id: int | None = None,
    locked: bool = False,
) -> int:
    path = normalize_category_path(path)
    if account_id is None:
        row = conn.execute(
            "SELECT id FROM categories WHERE account_id IS NULL AND path = ?", (path,)
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT id FROM categories WHERE account_id = ? AND path = ?", (account_id, path)
        ).fetchone()

    if row:
        return row[0]

    parts = path.split("/")
    display_name = parts[-1].replace("-", " ").title()
    parent_path = "/".join(parts[:-1]) if len(parts) > 1 else None
    conn.execute(
        "INSERT OR IGNORE INTO categories (account_id, path, display_name, parent_path, is_locked, is_active) "
        "VALUES (?, ?, ?, ?, ?, 1)",
        (account_id, path, display_name, parent_path, 1 if locked else 0),
    )
    conn.commit()

    if account_id is None:
        return conn.execute(
            "SELECT id FROM categories WHERE account_id IS NULL AND path = ?", (path,)
        ).fetchone()[0]
    return conn.execute(
        "SELECT id FROM categories WHERE account_id = ? AND path = ?", (account_id, path)
    ).fetchone()[0]


def get_all_categories(
    conn: sqlite3.Connection,
    account_id: int | None = None,
    *,
    include_global: bool = True,
) -> list[dict[str, Any]]:
    if account_id is not None and include_global:
        rows = conn.execute(
            "SELECT id, account_id, path, display_name, parent_path, is_locked, is_active "
            "FROM categories WHERE account_id = ? OR account_id IS NULL ORDER BY path",
            (account_id,),
        ).fetchall()
    elif account_id is not None:
        rows = conn.execute(
            "SELECT id, account_id, path, display_name, parent_path, is_locked, is_active "
            "FROM categories WHERE account_id = ? ORDER BY path",
            (account_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, account_id, path, display_name, parent_path, is_locked, is_active "
            "FROM categories ORDER BY path"
        ).fetchall()
    return [
        {
            "id": r[0],
            "account_id": r[1],
            "path": r[2],
            "display_name": r[3],
            "parent_path": r[4],
            "is_locked": bool(r[5]),
            "is_active": bool(r[6]),
            "is_global": r[1] is None,
        }
        for r in rows
    ]


def get_category_message_counts(
    conn: sqlite3.Connection,
    account_id: int | None = None,
) -> dict[str, int]:
    if account_id is not None:
        rows = conn.execute(
            "SELECT category_path, COUNT(*) FROM classifications "
            "WHERE target_type = 'message' AND account_id = ? GROUP BY category_path",
            (account_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT category_path, COUNT(*) FROM classifications "
            "WHERE target_type = 'message' GROUP BY category_path"
        ).fetchall()
    return {r[0]: r[1] for r in rows}


def list_pending_proposals(
    conn: sqlite3.Connection,
    account_id: int | None = None,
) -> list[dict[str, Any]]:
    if account_id is not None:
        rows = conn.execute(
            "SELECT id, account_id, proposed_path, display_name, reason, confidence, created_at "
            "FROM category_proposals WHERE status = 'pending' AND account_id = ? "
            "ORDER BY confidence DESC, created_at",
            (account_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, account_id, proposed_path, display_name, reason, confidence, created_at "
            "FROM category_proposals WHERE status = 'pending' ORDER BY confidence DESC, created_at"
        ).fetchall()
    return [
        {
            "id": r[0], "account_id": r[1], "proposed_path": r[2],
            "display_name": r[3], "reason": r[4], "confidence": r[5], "created_at": r[6],
        }
        for r in rows
    ]


def approve_proposal(conn: sqlite3.Connection, proposal_id: int, note: str = "") -> str:
    row = conn.execute(
        "SELECT proposed_path, display_name, account_id FROM category_proposals "
        "WHERE id = ? AND status = 'pending'",
        (proposal_id,),
    ).fetchone()
    if not row:
        raise ValueError(f"No pending proposal with id {proposal_id}")
    path, display_name, account_id = row
    ensure_category(conn, path, account_id=account_id)
    conn.execute(
        "UPDATE category_proposals SET status = 'approved', reviewed_at = CURRENT_TIMESTAMP, "
        "reviewed_note = ? WHERE id = ?",
        (note, proposal_id),
    )
    conn.commit()
    return path


def reject_proposal(conn: sqlite3.Connection, proposal_id: int, note: str = "") -> None:
    conn.execute(
        "UPDATE category_proposals SET status = 'rejected', reviewed_at = CURRENT_TIMESTAMP, "
        "reviewed_note = ? WHERE id = ? AND status = 'pending'",
        (note, proposal_id),
    )
    conn.commit()
