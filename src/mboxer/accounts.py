from __future__ import annotations

import sqlite3
from typing import Any


class AccountError(RuntimeError):
    """Raised when account resolution or validation fails."""


def create_account(
    conn: sqlite3.Connection,
    account_key: str,
    *,
    display_name: str | None = None,
    email_address: str | None = None,
    provider: str = "gmail",
    notes: str | None = None,
) -> int:
    conn.execute(
        """
        INSERT INTO accounts (account_key, display_name, email_address, provider, notes)
        VALUES (?, ?, ?, ?, ?)
        """,
        (account_key, display_name, email_address, provider, notes),
    )
    conn.commit()
    return conn.execute("SELECT id FROM accounts WHERE account_key = ?", (account_key,)).fetchone()[0]


def update_account(
    conn: sqlite3.Connection,
    account_key: str,
    *,
    display_name: str | None = None,
    email_address: str | None = None,
    notes: str | None = None,
) -> bool:
    updates: dict[str, Any] = {}
    if display_name is not None:
        updates["display_name"] = display_name
    if email_address is not None:
        updates["email_address"] = email_address
    if notes is not None:
        updates["notes"] = notes
    if not updates:
        return False
    updates["updated_at"] = "CURRENT_TIMESTAMP"
    sets = ", ".join(f"{k} = :{k}" for k in updates if k != "updated_at")
    sets += ", updated_at = CURRENT_TIMESTAMP"
    params = {k: v for k, v in updates.items() if k != "updated_at"}
    params["_key"] = account_key
    cursor = conn.execute(f"UPDATE accounts SET {sets} WHERE account_key = :_key", params)
    conn.commit()
    return cursor.rowcount > 0


def get_account(conn: sqlite3.Connection, account_key: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT id, account_key, display_name, email_address, provider, notes, created_at, updated_at "
        "FROM accounts WHERE account_key = ?",
        (account_key,),
    ).fetchone()
    if not row:
        return None
    return _row_to_dict(row)


def get_account_by_id(conn: sqlite3.Connection, account_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT id, account_key, display_name, email_address, provider, notes, created_at, updated_at "
        "FROM accounts WHERE id = ?",
        (account_id,),
    ).fetchone()
    return _row_to_dict(row) if row else None


def list_accounts(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT id, account_key, display_name, email_address, provider, notes, created_at, updated_at "
        "FROM accounts ORDER BY account_key"
    ).fetchall()
    return [_row_to_dict(r) for r in rows]


def _row_to_dict(row: tuple) -> dict[str, Any]:
    return {
        "id": row[0],
        "account_key": row[1],
        "display_name": row[2],
        "email_address": row[3],
        "provider": row[4],
        "notes": row[5],
        "created_at": row[6],
        "updated_at": row[7],
    }


def resolve_account(
    conn: sqlite3.Connection,
    account_key: str | None,
    *,
    command: str = "this command",
) -> dict[str, Any]:
    """Resolve an account for a command.

    - If account_key is given: look it up; raise if not found.
    - If account_key is None and exactly one account exists: use it with a notice.
    - If account_key is None and zero accounts: raise with helpful add hint.
    - If account_key is None and multiple accounts: raise asking for --account.
    """
    if account_key is not None:
        account = get_account(conn, account_key)
        if not account:
            all_keys = [a["account_key"] for a in list_accounts(conn)]
            hint = f"  Known accounts: {', '.join(all_keys)}" if all_keys else "  No accounts exist yet."
            raise AccountError(
                f"Account '{account_key}' not found.\n{hint}\n"
                f"To add it: mboxer account add {account_key}"
            )
        return account

    accounts = list_accounts(conn)
    if len(accounts) == 0:
        raise AccountError(
            f"{command} requires an account but none exist.\n"
            "Add one first: mboxer account add <account-key> --email <address>"
        )
    if len(accounts) == 1:
        print(f"[mboxer] Using account: {accounts[0]['account_key']}")
        return accounts[0]
    keys = ", ".join(a["account_key"] for a in accounts)
    raise AccountError(
        f"{command} requires --account when multiple accounts exist.\n"
        f"Available: {keys}"
    )


def ensure_default_account(conn: sqlite3.Connection, account_key: str = "default") -> dict[str, Any]:
    """Create a default account for legacy data migration if it doesn't exist."""
    existing = get_account(conn, account_key)
    if existing:
        return existing
    create_account(conn, account_key, display_name="Default (legacy migration)")
    return get_account(conn, account_key)  # type: ignore[return-value]
