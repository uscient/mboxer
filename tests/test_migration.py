import sqlite3
from itertools import product

import pytest

from mboxer.db.schema import apply_migrations


def test_fresh_db_applies_both_migrations(tmp_path):
    db_path = tmp_path / "fresh.sqlite"
    applied = apply_migrations(db_path)
    assert "001_initial" in applied
    assert "002_multi_account" in applied
    assert "003_address_invariant" in applied

    conn = sqlite3.connect(db_path)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    conn.close()

    assert "accounts" in tables
    assert "messages" in tables
    assert "labels" in tables
    assert "message_labels" in tables
    assert "schema_migrations" in tables


def test_fresh_db_idempotent(tmp_path):
    db_path = tmp_path / "fresh.sqlite"
    apply_migrations(db_path)
    applied2 = apply_migrations(db_path)
    assert applied2 == []


def test_legacy_db_upgrade(tmp_path):
    """Simulate a DB that was created before the migration system existed."""
    db_path = tmp_path / "legacy.sqlite"

    # Manually create the pre-002 schema (001 tables only)
    conn = sqlite3.connect(db_path)
    from mboxer.db.migrations import __file__ as mig_init
    from pathlib import Path
    mig_001 = Path(mig_init).parent / "001_initial.sql"
    conn.executescript(mig_001.read_text())
    conn.commit()
    conn.close()

    # Now apply migrations — should detect legacy and apply 002
    applied = apply_migrations(db_path)
    assert "001_initial" not in applied   # already existed
    assert "002_multi_account" in applied

    conn = sqlite3.connect(db_path)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    conn.close()
    assert "accounts" in tables
    assert "labels" in tables


def test_legacy_categories_preserved(tmp_path):
    """Categories from a legacy DB should survive the 002 migration."""
    db_path = tmp_path / "legacy.sqlite"

    from pathlib import Path
    from mboxer.db.migrations import __file__ as mig_init
    mig_001 = Path(mig_init).parent / "001_initial.sql"

    conn = sqlite3.connect(db_path)
    conn.executescript(mig_001.read_text())
    conn.execute("INSERT INTO categories (path, display_name, is_locked) VALUES ('medical', 'Medical', 1)")
    conn.execute("INSERT INTO categories (path, display_name, is_locked) VALUES ('legal', 'Legal', 1)")
    conn.commit()
    conn.close()

    apply_migrations(db_path)

    conn = sqlite3.connect(db_path)
    cats = {r[0] for r in conn.execute("SELECT path FROM categories").fetchall()}
    conn.close()
    assert "medical" in cats
    assert "legal" in cats


def test_messages_have_account_id_column(tmp_path):
    db_path = tmp_path / "test.sqlite"
    apply_migrations(db_path)
    conn = sqlite3.connect(db_path)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(messages)").fetchall()}
    conn.close()
    assert "account_id" in cols


def test_mbox_sources_have_account_id_column(tmp_path):
    db_path = tmp_path / "test.sqlite"
    apply_migrations(db_path)
    conn = sqlite3.connect(db_path)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(mbox_sources)").fetchall()}
    conn.close()
    assert "account_id" in cols
    assert "source_mtime" in cols
    assert "provider" in cols


def test_messages_address_columns_are_constrained(tmp_path):
    db_path = tmp_path / "test.sqlite"
    apply_migrations(db_path)
    conn = sqlite3.connect(db_path)
    try:
        columns = {
            row[1]: {
                "notnull": row[3],
                "default": row[4],
            }
            for row in conn.execute("PRAGMA table_info(messages)").fetchall()
        }
    finally:
        conn.close()

    for column in ("recipients_json", "cc_json", "bcc_json"):
        assert columns[column]["notnull"] == 1
        assert columns[column]["default"] == "'[]'"


def _insert_message_with_address_values(
    conn: sqlite3.Connection,
    *,
    mbox_key: str,
    recipients_json: str | None = "[]",
    cc_json: str | None = "[]",
    bcc_json: str | None = "[]",
) -> None:
    account_id = conn.execute(
        "INSERT INTO accounts (account_key) VALUES (?) RETURNING id",
        (f"account-{mbox_key}",),
    ).fetchone()[0]
    source_id = conn.execute(
        """
        INSERT INTO mbox_sources (account_id, source_name, source_slug, file_path)
        VALUES (?, ?, ?, ?)
        RETURNING id
        """,
        (account_id, f"source-{mbox_key}", f"source-{mbox_key}", f"/tmp/{mbox_key}.mbox"),
    ).fetchone()[0]
    conn.execute(
        """
        INSERT INTO messages
          (account_id, source_id, mbox_key, recipients_json, cc_json, bcc_json)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (account_id, source_id, mbox_key, recipients_json, cc_json, bcc_json),
    )


@pytest.mark.parametrize(
    ("column", "bad_value"),
    list(product(("recipients_json", "cc_json", "bcc_json"), (None, "{}", '"x"', "not json"))),
)
def test_messages_address_json_constraints_reject_invalid_values(
    tmp_path,
    column: str,
    bad_value: str | None,
):
    db_path = tmp_path / "test.sqlite"
    apply_migrations(db_path)
    conn = sqlite3.connect(db_path)
    values = {
        "recipients_json": "[]",
        "cc_json": "[]",
        "bcc_json": "[]",
        column: bad_value,
    }
    try:
        with pytest.raises(sqlite3.DatabaseError):
            _insert_message_with_address_values(
                conn,
                mbox_key=f"{column}-{bad_value!r}",
                **values,
            )
    finally:
        conn.close()


def test_messages_address_json_constraints_accept_arrays_and_defaults(tmp_path):
    db_path = tmp_path / "test.sqlite"
    apply_migrations(db_path)
    conn = sqlite3.connect(db_path)
    try:
        _insert_message_with_address_values(
            conn,
            mbox_key="arrays",
            recipients_json='["to@example.com"]',
            cc_json="[]",
            bcc_json='["hidden@example.com"]',
        )

        account_id = conn.execute(
            "INSERT INTO accounts (account_key) VALUES ('default-account') RETURNING id"
        ).fetchone()[0]
        source_id = conn.execute(
            """
            INSERT INTO mbox_sources (account_id, source_name, source_slug, file_path)
            VALUES (?, 'default-source', 'default-source', '/tmp/default.mbox')
            RETURNING id
            """,
            (account_id,),
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO messages (account_id, source_id, mbox_key) VALUES (?, ?, 'defaults')",
            (account_id, source_id),
        )

        rows = conn.execute(
            """
            SELECT mbox_key, recipients_json, cc_json, bcc_json
            FROM messages
            ORDER BY mbox_key
            """
        ).fetchall()
    finally:
        conn.close()

    assert rows == [
        ("arrays", '["to@example.com"]', "[]", '["hidden@example.com"]'),
        ("defaults", "[]", "[]", "[]"),
    ]


def test_address_invariant_migration_preserves_valid_messages(tmp_path):
    db_path = tmp_path / "pre003.sqlite"
    from pathlib import Path
    from mboxer.db.migrations import __file__ as mig_init

    migrations_dir = Path(mig_init).parent
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE schema_migrations (
            version TEXT PRIMARY KEY,
            applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.executescript((migrations_dir / "001_initial.sql").read_text())
    conn.execute("INSERT INTO schema_migrations (version) VALUES ('001_initial')")
    conn.executescript((migrations_dir / "002_multi_account.sql").read_text())
    conn.execute("INSERT INTO schema_migrations (version) VALUES ('002_multi_account')")
    account_id = conn.execute(
        "INSERT INTO accounts (account_key) VALUES ('pre003-account') RETURNING id"
    ).fetchone()[0]
    source_id = conn.execute(
        """
        INSERT INTO mbox_sources (account_id, source_name, source_slug, file_path)
        VALUES (?, 'pre003-source', 'pre003-source', '/tmp/pre003.mbox')
        RETURNING id
        """,
        (account_id,),
    ).fetchone()[0]
    conn.execute(
        """
        INSERT INTO messages
          (account_id, source_id, mbox_key, message_id, subject, sender,
           recipients_json, cc_json, bcc_json)
        VALUES (?, ?, '0', '<pre003@example.test>', 'Pre 003', 'sender@example.test',
                '["to@example.test"]', '[]', '["hidden@example.test"]')
        """,
        (account_id, source_id),
    )
    conn.commit()
    conn.close()

    assert apply_migrations(db_path) == ["003_address_invariant"]

    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            """
            SELECT account_id, source_id, mbox_key, recipients_json, cc_json, bcc_json
            FROM messages
            """
        ).fetchone()
        columns = {
            info[1]: {"notnull": info[3], "default": info[4]}
            for info in conn.execute("PRAGMA table_info(messages)").fetchall()
        }
    finally:
        conn.close()

    assert row == (
        account_id,
        source_id,
        "0",
        '["to@example.test"]',
        "[]",
        '["hidden@example.test"]',
    )
    for column in ("recipients_json", "cc_json", "bcc_json"):
        assert columns[column]["notnull"] == 1
        assert columns[column]["default"] == "'[]'"
