import sqlite3
import pytest
from mboxer.db import init_db
from mboxer.db.schema import apply_migrations


def test_fresh_db_applies_both_migrations(tmp_path):
    db_path = tmp_path / "fresh.sqlite"
    applied = apply_migrations(db_path)
    assert "001_initial" in applied
    assert "002_multi_account" in applied

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
