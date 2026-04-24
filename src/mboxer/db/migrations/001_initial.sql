-- Migration 001: initial schema (pre-multi-account)
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS mbox_sources (
    id INTEGER PRIMARY KEY,
    source_name TEXT NOT NULL,
    source_slug TEXT NOT NULL,
    file_path TEXT NOT NULL UNIQUE,
    file_size INTEGER,
    file_sha256 TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS ingest_runs (
    id INTEGER PRIMARY KEY,
    source_id INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'running',
    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TEXT,
    last_mbox_key TEXT,
    messages_seen INTEGER DEFAULT 0,
    messages_inserted INTEGER DEFAULT 0,
    messages_skipped INTEGER DEFAULT 0,
    errors_count INTEGER DEFAULT 0,
    FOREIGN KEY(source_id) REFERENCES mbox_sources(id)
);

CREATE TABLE IF NOT EXISTS ingest_errors (
    id INTEGER PRIMARY KEY,
    ingest_run_id INTEGER NOT NULL,
    source_id INTEGER NOT NULL,
    mbox_key TEXT,
    error_type TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(ingest_run_id) REFERENCES ingest_runs(id),
    FOREIGN KEY(source_id) REFERENCES mbox_sources(id)
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY,
    source_id INTEGER NOT NULL,
    mbox_key TEXT NOT NULL,
    message_id TEXT,
    thread_key TEXT,
    subject TEXT,
    sender TEXT,
    recipients_json TEXT,
    cc_json TEXT,
    bcc_json TEXT,
    date_header TEXT,
    date_utc TEXT,
    body_text TEXT,
    body_html TEXT,
    body_hash TEXT,
    body_chars INTEGER DEFAULT 0,
    body_word_count INTEGER DEFAULT 0,
    attachment_count INTEGER DEFAULT 0,
    raw_headers_json TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(source_id) REFERENCES mbox_sources(id),
    UNIQUE(source_id, mbox_key)
);

CREATE INDEX IF NOT EXISTS idx_messages_message_id ON messages(message_id);
CREATE INDEX IF NOT EXISTS idx_messages_thread_key ON messages(thread_key);
CREATE INDEX IF NOT EXISTS idx_messages_date_utc ON messages(date_utc);
CREATE INDEX IF NOT EXISTS idx_messages_body_hash ON messages(body_hash);

CREATE TABLE IF NOT EXISTS attachments (
    id INTEGER PRIMARY KEY,
    message_db_id INTEGER NOT NULL,
    source_id INTEGER NOT NULL,
    original_filename TEXT,
    safe_filename TEXT NOT NULL,
    content_type TEXT,
    content_disposition TEXT,
    size_bytes INTEGER,
    sha256 TEXT,
    storage_path TEXT,
    extraction_status TEXT NOT NULL DEFAULT 'pending',
    error_message TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(message_db_id) REFERENCES messages(id),
    FOREIGN KEY(source_id) REFERENCES mbox_sources(id)
);

CREATE TABLE IF NOT EXISTS threads (
    id INTEGER PRIMARY KEY,
    thread_key TEXT NOT NULL,
    source_id INTEGER NOT NULL,
    subject TEXT,
    message_count INTEGER DEFAULT 0,
    first_date_utc TEXT,
    last_date_utc TEXT,
    participants_json TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(source_id) REFERENCES mbox_sources(id),
    UNIQUE(thread_key, source_id)
);

CREATE INDEX IF NOT EXISTS idx_threads_source ON threads(source_id);
CREATE INDEX IF NOT EXISTS idx_threads_key ON threads(thread_key);
CREATE INDEX IF NOT EXISTS idx_attachments_message ON attachments(message_db_id);
CREATE INDEX IF NOT EXISTS idx_attachments_sha256 ON attachments(sha256);

CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY,
    path TEXT NOT NULL UNIQUE,
    display_name TEXT,
    description TEXT,
    parent_path TEXT,
    is_locked INTEGER NOT NULL DEFAULT 0,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS category_aliases (
    id INTEGER PRIMARY KEY,
    alias TEXT NOT NULL UNIQUE,
    category_path TEXT NOT NULL,
    FOREIGN KEY(category_path) REFERENCES categories(path)
);

CREATE TABLE IF NOT EXISTS category_rules (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    description TEXT,
    rule_json TEXT NOT NULL,
    category_path TEXT,
    priority INTEGER DEFAULT 100,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS classifications (
    id INTEGER PRIMARY KEY,
    target_type TEXT NOT NULL DEFAULT 'message',
    message_db_id INTEGER,
    thread_key TEXT,
    category_path TEXT NOT NULL,
    secondary_paths_json TEXT,
    specific_topic TEXT,
    summary TEXT,
    people_json TEXT,
    organizations_json TEXT,
    sensitivity TEXT,
    notebooklm_priority TEXT,
    export_profile TEXT,
    confidence REAL,
    needs_review INTEGER NOT NULL DEFAULT 0,
    classifier_type TEXT NOT NULL,
    classifier_name TEXT,
    model_name TEXT,
    prompt_version TEXT,
    raw_output_json TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(message_db_id) REFERENCES messages(id)
);

CREATE INDEX IF NOT EXISTS idx_classifications_message ON classifications(message_db_id);
CREATE INDEX IF NOT EXISTS idx_classifications_thread ON classifications(thread_key);
CREATE INDEX IF NOT EXISTS idx_classifications_category ON classifications(category_path);

CREATE TABLE IF NOT EXISTS category_proposals (
    id INTEGER PRIMARY KEY,
    proposed_path TEXT NOT NULL,
    display_name TEXT,
    reason TEXT,
    example_message_ids_json TEXT,
    confidence REAL,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    reviewed_at TEXT,
    reviewed_note TEXT
);

CREATE TABLE IF NOT EXISTS security_findings (
    id INTEGER PRIMARY KEY,
    target_type TEXT NOT NULL,
    message_db_id INTEGER,
    attachment_id INTEGER,
    finding_type TEXT NOT NULL,
    severity TEXT NOT NULL,
    detector TEXT NOT NULL,
    excerpt TEXT,
    metadata_json TEXT,
    status TEXT NOT NULL DEFAULT 'open',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(message_db_id) REFERENCES messages(id),
    FOREIGN KEY(attachment_id) REFERENCES attachments(id)
);

CREATE INDEX IF NOT EXISTS idx_security_message ON security_findings(message_db_id);
CREATE INDEX IF NOT EXISTS idx_security_attachment ON security_findings(attachment_id);
CREATE INDEX IF NOT EXISTS idx_security_type ON security_findings(finding_type);

CREATE TABLE IF NOT EXISTS exports (
    id INTEGER PRIMARY KEY,
    export_type TEXT NOT NULL,
    export_profile TEXT NOT NULL,
    output_path TEXT NOT NULL,
    notebooklm_limit_profile TEXT,
    source_count INTEGER DEFAULT 0,
    message_count INTEGER DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'running',
    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TEXT,
    metadata_json TEXT
);

CREATE TABLE IF NOT EXISTS export_items (
    id INTEGER PRIMARY KEY,
    export_id INTEGER NOT NULL,
    output_file TEXT NOT NULL,
    message_db_id INTEGER,
    category_path TEXT,
    sequence INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(export_id) REFERENCES exports(id),
    FOREIGN KEY(message_db_id) REFERENCES messages(id)
);
