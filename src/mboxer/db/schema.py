from __future__ import annotations

import sqlite3
from pathlib import Path

from mboxer.config import ensure_parent_dir

_MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def _list_migration_files() -> list[Path]:
    if not _MIGRATIONS_DIR.exists():
        return []
    return sorted(p for p in _MIGRATIONS_DIR.glob("*.sql") if p.stem[0].isdigit())


def _existing_tables(conn: sqlite3.Connection) -> set[str]:
    return {
        r[0]
        for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }


def _execute_statements(conn: sqlite3.Connection, sql: str) -> None:
    """Execute migration SQL without executescript's implicit transaction commit."""
    statement = ""
    for fragment in sql.split(";"):
        statement += fragment + ";"
        if sqlite3.complete_statement(statement):
            conn.execute(statement)
            statement = ""
    if statement.strip():
        conn.execute(statement)


def _prepare_address_migration(conn: sqlite3.Connection) -> None:
    # Older schemas used NULL for an absent address list. Preserve that meaning
    # as an empty array; malformed non-NULL values must still fail validation.
    conn.execute("UPDATE messages SET recipients_json = '[]' WHERE recipients_json IS NULL")
    conn.execute("UPDATE messages SET cc_json = '[]' WHERE cc_json IS NULL")
    conn.execute("UPDATE messages SET bcc_json = '[]' WHERE bcc_json IS NULL")
    # The previous migration runner could leave this empty staging table after
    # a failed 003 copy. Only remove the known empty artifact, never evidence.
    if "messages_new" in _existing_tables(conn):
        if conn.execute("SELECT 1 FROM messages_new LIMIT 1").fetchone():
            raise RuntimeError("Nonempty messages_new requires manual migration recovery")
        conn.execute("DROP TABLE messages_new")


def apply_migrations(db_path: Path) -> list[str]:
    """Apply all pending migrations. Returns list of applied version strings."""
    db_path = Path(db_path)
    ensure_parent_dir(db_path)

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode = WAL")

    try:
        tables_before = _existing_tables(conn)
        is_legacy = "messages" in tables_before and "schema_migrations" not in tables_before

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version TEXT PRIMARY KEY,
                applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.commit()

        if is_legacy:
            conn.execute(
                "INSERT OR IGNORE INTO schema_migrations (version) VALUES ('001_initial')"
            )
            conn.commit()

        applied: list[str] = []
        for mig_path in _list_migration_files():
            version = mig_path.stem
            sql = mig_path.read_text(encoding="utf-8")
            # Table rebuilds need FK enforcement disabled before BEGIN; the
            # complete database is checked before committing each migration.
            conn.execute("PRAGMA foreign_keys = OFF")
            conn.execute("BEGIN IMMEDIATE")
            try:
                already = conn.execute(
                    "SELECT 1 FROM schema_migrations WHERE version = ?", (version,)
                ).fetchone()
                if already:
                    conn.rollback()
                    continue
                if version == "003_address_invariant":
                    _prepare_address_migration(conn)
                _execute_statements(conn, sql)
                if conn.execute("PRAGMA foreign_key_check").fetchone():
                    raise sqlite3.IntegrityError("Migration would leave invalid foreign keys")
                conn.execute(
                    "INSERT INTO schema_migrations (version) VALUES (?)", (version,)
                )
                conn.commit()
                applied.append(version)
            except BaseException:
                conn.rollback()
                raise
            finally:
                conn.execute("PRAGMA foreign_keys = ON")

        return applied
    finally:
        conn.close()


def init_db(path: str | Path) -> Path:
    db_path = Path(path)
    applied = apply_migrations(db_path)
    for v in applied:
        print(f"  [migration] Applied: {v}")
    return db_path
