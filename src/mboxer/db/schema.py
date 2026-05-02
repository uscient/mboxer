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
            already = conn.execute(
                "SELECT 1 FROM schema_migrations WHERE version = ?", (version,)
            ).fetchone()
            if already:
                continue
            sql = mig_path.read_text(encoding="utf-8")
            conn.executescript(sql)
            conn.execute(
                "INSERT INTO schema_migrations (version) VALUES (?)", (version,)
            )
            conn.commit()
            applied.append(version)

        return applied
    finally:
        conn.close()


def init_db(path: str | Path) -> Path:
    db_path = Path(path)
    applied = apply_migrations(db_path)
    for v in applied:
        print(f"  [migration] Applied: {v}")
    return db_path
