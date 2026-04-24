import sqlite3
from mboxer.db import init_db


def test_init_db_idempotent(tmp_path):
    db = tmp_path / "mboxer.sqlite"
    init_db(db)
    init_db(db)
    assert db.exists()


def test_init_db_creates_all_tables(tmp_path):
    db = tmp_path / "mboxer.sqlite"
    init_db(db)
    conn = sqlite3.connect(db)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    conn.close()
    required = {
        "accounts", "mbox_sources", "ingest_runs", "ingest_errors",
        "messages", "threads", "attachments", "labels", "message_labels",
        "categories", "category_aliases", "category_rules",
        "classifications", "category_proposals",
        "security_findings", "exports", "export_items",
        "schema_migrations",
    }
    assert required.issubset(tables)


def test_schema_migrations_tracked(tmp_path):
    db = tmp_path / "mboxer.sqlite"
    init_db(db)
    conn = sqlite3.connect(db)
    versions = {r[0] for r in conn.execute("SELECT version FROM schema_migrations").fetchall()}
    conn.close()
    assert "001_initial" in versions
    assert "002_multi_account" in versions
