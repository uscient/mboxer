import sqlite3
from pathlib import Path

import pytest

from mboxer.db import schema


def _legacy_db(path, *, recipient=None):
    with sqlite3.connect(path) as conn:
        conn.executescript((schema._MIGRATIONS_DIR / "001_initial.sql").read_text())
        conn.execute("INSERT INTO mbox_sources(id,source_name,source_slug,file_path) VALUES(41,'synthetic','synthetic','/synthetic.mbox')")
        conn.execute("INSERT INTO messages(id,source_id,mbox_key,recipients_json) VALUES(51,41,'0',?)", (recipient,))


def test_legacy_null_addresses_upgrade_without_losing_ids(tmp_path):
    path = tmp_path / "legacy.sqlite"
    _legacy_db(path)
    schema.apply_migrations(path)
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT id,source_id,recipients_json,cc_json,bcc_json FROM messages").fetchall() == [(51, 41, "[]", "[]", "[]")]
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    assert schema.apply_migrations(path) == []


def test_failed_address_migration_is_atomic_and_retryable(tmp_path):
    path = tmp_path / "legacy.sqlite"
    _legacy_db(path, recipient="not JSON")
    with pytest.raises(sqlite3.DatabaseError):
        schema.apply_migrations(path)
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT name FROM sqlite_master WHERE name='messages_new'").fetchall() == []
        assert conn.execute("SELECT recipients_json,cc_json FROM messages").fetchall() == [("not JSON", None)]
        conn.execute("UPDATE messages SET recipients_json='[]'")
    assert "003_address_invariant" in schema.apply_migrations(path)


def test_recovers_empty_shadow_left_by_previous_migration_runner(tmp_path):
    path = tmp_path / "legacy.sqlite"
    _legacy_db(path)
    # Reproduce the old runner's committed CREATE before failing to copy rows.
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE messages_new (id INTEGER)")
    schema.apply_migrations(path)
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM messages").fetchone() == (1,)


def test_nonempty_shadow_requires_recovery_without_discarding_it(tmp_path):
    path = tmp_path / "legacy.sqlite"
    _legacy_db(path)
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE messages_new (id INTEGER)")
        conn.execute("INSERT INTO messages_new VALUES (999)")
    with pytest.raises(RuntimeError, match="manual migration recovery"):
        schema.apply_migrations(path)
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT id FROM messages_new").fetchall() == [(999,)]


@pytest.mark.parametrize("invalid_sql", [
    "INSERT INTO no_such_table VALUES (1);",
    "CREATE TABLE child (parent INTEGER REFERENCES accounts(id)); INSERT INTO child VALUES (999);",
])
def test_migration_ddl_data_and_ledger_roll_back_together(tmp_path, monkeypatch, invalid_sql):
    path = tmp_path / "evidence.sqlite"
    schema.apply_migrations(path)
    migration = tmp_path / "006_injected.sql"
    migration.write_text("CREATE TABLE probe (id INTEGER); INSERT INTO probe VALUES (1);" + invalid_sql)
    monkeypatch.setattr(schema, "_list_migration_files", lambda: [migration])
    with pytest.raises(sqlite3.DatabaseError):
        schema.apply_migrations(path)
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT name FROM sqlite_master WHERE name IN ('probe','child')").fetchall() == []
        assert conn.execute("SELECT version FROM schema_migrations WHERE version='006_injected'").fetchall() == []
    migration.write_text("CREATE TABLE probe (id INTEGER); INSERT INTO probe VALUES (1);")
    assert schema.apply_migrations(path) == ["006_injected"]


def test_reference_schema_matches_migrated_constraints_and_indexes(tmp_path):
    path = tmp_path / "migrated.sqlite"
    schema.apply_migrations(path)
    migrated = sqlite3.connect(path)
    reference = sqlite3.connect(":memory:")
    reference.executescript((Path(schema.__file__).parent / "schema.sql").read_text())

    def signature(conn):
        result = {}
        for (table,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table'"):
            columns = {row[1]: row[2:] for row in conn.execute(f"PRAGMA table_info({table})")}
            foreign_keys = {row[2:] for row in conn.execute(f"PRAGMA foreign_key_list({table})")}
            indexes = {
                (tuple(row[2] for row in conn.execute(f"PRAGMA index_info({index[1]})")), index[2], index[4])
                for index in conn.execute(f"PRAGMA index_list({table})")
            }
            result[table] = (columns, foreign_keys, indexes)
        return result

    try:
        assert signature(migrated) == signature(reference)
        expected = {
            "idx_classifications_account_message_type", "idx_classifications_account_thread_type",
            "idx_security_account_message",
        }
        actual = {row[0] for row in migrated.execute("SELECT name FROM sqlite_master WHERE type='index'")}
        assert expected <= actual
    finally:
        migrated.close()
        reference.close()
