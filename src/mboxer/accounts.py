from __future__ import annotations

import re
import sqlite3
from typing import Any


class AccountError(RuntimeError):
    """Raised when account resolution or validation fails."""


def validate_account_key(account_key: str) -> None:
    """Require an unchanged, portable single directory component.

    Account keys are durable identities as well as output directory names.
    Reject unsafe keys instead of normalizing them into another account's key.
    Existing rows remain readable so their identity can be repaired explicitly.
    """
    reserved = re.fullmatch(
        r"(?:CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³])",
        account_key.split(".", 1)[0].rstrip(" "),
        flags=re.IGNORECASE,
    )
    if (
        not account_key
        or account_key in (".", "..")
        or account_key.endswith((".", " "))
        or any(char in '<>:"/\\|?*' or not char.isprintable() for char in account_key)
        or reserved
        or len(account_key.encode("utf-8")) > 255
    ):
        raise AccountError(
            "Unsafe account key: use one directory name without path separators, "
            "reserved filenames, or trailing dots/spaces; existing keys are not renamed."
        )


def create_account(
    conn: sqlite3.Connection,
    account_key: str,
    *,
    display_name: str | None = None,
    email_address: str | None = None,
    provider: str = "gmail",
    notes: str | None = None,
) -> int:
    validate_account_key(account_key)
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
    if display_name is None and email_address is None and notes is None:
        return False
    cursor = conn.execute(
        """
        UPDATE accounts
        SET display_name = COALESCE(?, display_name),
            email_address = COALESCE(?, email_address),
            notes = COALESCE(?, notes),
            updated_at = CURRENT_TIMESTAMP
        WHERE account_key = ?
        """,
        (display_name, email_address, notes, account_key),
    )
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
