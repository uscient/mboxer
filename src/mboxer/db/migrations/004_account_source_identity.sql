-- The initial schema made file_path globally unique. A source belongs to an
-- account, so the same archive path must be independently usable per account.
-- Keep nullable account IDs for existing unassigned legacy evidence.
PRAGMA foreign_keys = OFF;

CREATE TABLE mbox_sources_new (
    id INTEGER PRIMARY KEY,
    source_name TEXT NOT NULL,
    source_slug TEXT NOT NULL,
    file_path TEXT NOT NULL,
    file_size INTEGER,
    file_sha256 TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    account_id INTEGER REFERENCES accounts(id),
    source_mtime REAL,
    provider TEXT DEFAULT 'gmail',
    imported_label_hint TEXT,
    UNIQUE(account_id, file_path)
);

INSERT INTO mbox_sources_new
    (id, source_name, source_slug, file_path, file_size, file_sha256, created_at,
     account_id, source_mtime, provider, imported_label_hint)
SELECT id, source_name, source_slug, file_path, file_size, file_sha256, created_at,
       account_id, source_mtime, provider, imported_label_hint
FROM mbox_sources;

DROP TABLE mbox_sources;
ALTER TABLE mbox_sources_new RENAME TO mbox_sources;
CREATE INDEX idx_mbox_sources_account ON mbox_sources(account_id);
CREATE UNIQUE INDEX idx_mbox_sources_legacy_path ON mbox_sources(file_path)
    WHERE account_id IS NULL;

PRAGMA foreign_keys = ON;
