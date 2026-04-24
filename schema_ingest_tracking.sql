-- Schema extension for resumable multi-MBOX ingest and normalized attachment tracking.
-- Intended for use with the existing mbox_manager_v0.py SQLite schema.

CREATE TABLE IF NOT EXISTS mbox_sources (
    id INTEGER PRIMARY KEY,
    path TEXT UNIQUE NOT NULL,
    filename TEXT,
    path_sha256 TEXT UNIQUE NOT NULL,
    size_bytes INTEGER DEFAULT 0,
    mtime_ns INTEGER DEFAULT 0,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT,
    last_ingested_at TEXT,
    last_status TEXT,
    last_run_id INTEGER,
    message_count INTEGER DEFAULT 0,
    inserted_count INTEGER DEFAULT 0,
    skipped_count INTEGER DEFAULT 0,
    failed_count INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_mbox_sources_path_sha ON mbox_sources(path_sha256);
CREATE INDEX IF NOT EXISTS idx_mbox_sources_last_status ON mbox_sources(last_status);

CREATE TABLE IF NOT EXISTS ingest_runs (
    id INTEGER PRIMARY KEY,
    mbox_source_id INTEGER NOT NULL,
    mbox_path TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'running',
    started_at TEXT NOT NULL,
    updated_at TEXT,
    finished_at TEXT,
    command_json TEXT DEFAULT '{}',
    total_scanned INTEGER DEFAULT 0,
    inserted_count INTEGER DEFAULT 0,
    skipped_count INTEGER DEFAULT 0,
    failed_count INTEGER DEFAULT 0,
    last_mbox_key TEXT,
    last_error TEXT,
    process_id INTEGER,
    host TEXT,
    extract_attachments INTEGER DEFAULT 0,
    attachments_dir TEXT,
    FOREIGN KEY(mbox_source_id) REFERENCES mbox_sources(id)
);

CREATE INDEX IF NOT EXISTS idx_ingest_runs_source ON ingest_runs(mbox_source_id);
CREATE INDEX IF NOT EXISTS idx_ingest_runs_status ON ingest_runs(status);
CREATE INDEX IF NOT EXISTS idx_ingest_runs_started ON ingest_runs(started_at);

CREATE TABLE IF NOT EXISTS ingest_errors (
    id INTEGER PRIMARY KEY,
    ingest_run_id INTEGER,
    mbox_source_id INTEGER,
    mbox_key TEXT,
    error_type TEXT,
    error_message TEXT,
    traceback TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(ingest_run_id) REFERENCES ingest_runs(id),
    FOREIGN KEY(mbox_source_id) REFERENCES mbox_sources(id)
);

CREATE INDEX IF NOT EXISTS idx_ingest_errors_run ON ingest_errors(ingest_run_id);
CREATE INDEX IF NOT EXISTS idx_ingest_errors_source ON ingest_errors(mbox_source_id);
CREATE INDEX IF NOT EXISTS idx_ingest_errors_key ON ingest_errors(mbox_key);

CREATE TABLE IF NOT EXISTS attachments (
    id INTEGER PRIMARY KEY,
    message_db_id INTEGER NOT NULL,
    mbox_source_id INTEGER,
    ingest_run_id INTEGER,
    filename_original TEXT,
    filename_safe TEXT,
    content_type TEXT,
    size_bytes INTEGER DEFAULT 0,
    sha256 TEXT,
    storage_path TEXT DEFAULT '',
    extraction_status TEXT DEFAULT 'metadata_only',
    created_at TEXT NOT NULL,
    FOREIGN KEY(message_db_id) REFERENCES messages(id),
    FOREIGN KEY(mbox_source_id) REFERENCES mbox_sources(id),
    FOREIGN KEY(ingest_run_id) REFERENCES ingest_runs(id),
    UNIQUE(message_db_id, sha256, filename_safe)
);

CREATE INDEX IF NOT EXISTS idx_attachments_message ON attachments(message_db_id);
CREATE INDEX IF NOT EXISTS idx_attachments_source ON attachments(mbox_source_id);
CREATE INDEX IF NOT EXISTS idx_attachments_run ON attachments(ingest_run_id);
CREATE INDEX IF NOT EXISTS idx_attachments_sha ON attachments(sha256);
CREATE INDEX IF NOT EXISTS idx_attachments_status ON attachments(extraction_status);
CREATE INDEX IF NOT EXISTS idx_attachments_content_type ON attachments(content_type);

-- Existing messages table should be migrated by Python helper functions:
-- ALTER TABLE messages ADD COLUMN mbox_source_id INTEGER;
-- ALTER TABLE messages ADD COLUMN ingest_run_id INTEGER;
-- CREATE INDEX IF NOT EXISTS idx_messages_source ON messages(mbox_source_id);
-- CREATE INDEX IF NOT EXISTS idx_messages_source_key ON messages(mbox_source_id, mbox_key);
