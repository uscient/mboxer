-- Authoritative full schema (fresh install target).
-- Migrations in db/migrations/ produce this same state incrementally.
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY,
    account_key TEXT UNIQUE NOT NULL,
    display_name TEXT,
    email_address TEXT,
    provider TEXT DEFAULT 'gmail',
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS mbox_sources (
    id INTEGER PRIMARY KEY,
    account_id INTEGER NOT NULL,
    source_name TEXT NOT NULL,
    source_slug TEXT NOT NULL,
    file_path TEXT NOT NULL,
    file_size INTEGER,
    file_sha256 TEXT,
    source_mtime REAL,
    provider TEXT DEFAULT 'gmail',
    imported_label_hint TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(account_id) REFERENCES accounts(id),
    UNIQUE(account_id, file_path)
);

CREATE TABLE IF NOT EXISTS ingest_runs (
    id INTEGER PRIMARY KEY,
    account_id INTEGER,
    source_id INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'running',
    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TEXT,
    last_mbox_key TEXT,
    messages_seen INTEGER DEFAULT 0,
    messages_inserted INTEGER DEFAULT 0,
    messages_skipped INTEGER DEFAULT 0,
    errors_count INTEGER DEFAULT 0,
    FOREIGN KEY(account_id) REFERENCES accounts(id),
    FOREIGN KEY(source_id) REFERENCES mbox_sources(id)
);

CREATE TABLE IF NOT EXISTS ingest_errors (
    id INTEGER PRIMARY KEY,
    account_id INTEGER,
    ingest_run_id INTEGER NOT NULL,
    source_id INTEGER NOT NULL,
    mbox_key TEXT,
    error_type TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(account_id) REFERENCES accounts(id),
    FOREIGN KEY(ingest_run_id) REFERENCES ingest_runs(id),
    FOREIGN KEY(source_id) REFERENCES mbox_sources(id)
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY,
    account_id INTEGER NOT NULL,
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
    FOREIGN KEY(account_id) REFERENCES accounts(id),
    FOREIGN KEY(source_id) REFERENCES mbox_sources(id),
    UNIQUE(account_id, source_id, mbox_key)
);

CREATE INDEX IF NOT EXISTS idx_messages_account ON messages(account_id);
CREATE INDEX IF NOT EXISTS idx_messages_message_id ON messages(message_id);
CREATE INDEX IF NOT EXISTS idx_messages_account_message_id ON messages(account_id, message_id);
CREATE INDEX IF NOT EXISTS idx_messages_thread_key ON messages(thread_key);
CREATE INDEX IF NOT EXISTS idx_messages_account_thread_key ON messages(account_id, thread_key);
CREATE INDEX IF NOT EXISTS idx_messages_date_utc ON messages(date_utc);
CREATE INDEX IF NOT EXISTS idx_messages_body_hash ON messages(body_hash);

CREATE TABLE IF NOT EXISTS threads (
    id INTEGER PRIMARY KEY,
    account_id INTEGER,
    thread_key TEXT NOT NULL,
    source_id INTEGER NOT NULL,
    subject TEXT,
    message_count INTEGER DEFAULT 0,
    first_date_utc TEXT,
    last_date_utc TEXT,
    participants_json TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(account_id) REFERENCES accounts(id),
    FOREIGN KEY(source_id) REFERENCES mbox_sources(id),
    UNIQUE(account_id, thread_key, source_id)
);

CREATE INDEX IF NOT EXISTS idx_threads_source ON threads(source_id);
CREATE INDEX IF NOT EXISTS idx_threads_key ON threads(thread_key);
CREATE INDEX IF NOT EXISTS idx_threads_account ON threads(account_id);

CREATE TABLE IF NOT EXISTS attachments (
    id INTEGER PRIMARY KEY,
    account_id INTEGER,
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
    FOREIGN KEY(account_id) REFERENCES accounts(id),
    FOREIGN KEY(message_db_id) REFERENCES messages(id),
    FOREIGN KEY(source_id) REFERENCES mbox_sources(id)
);

CREATE INDEX IF NOT EXISTS idx_attachments_message ON attachments(message_db_id);
CREATE INDEX IF NOT EXISTS idx_attachments_sha256 ON attachments(sha256);
CREATE INDEX IF NOT EXISTS idx_attachments_account ON attachments(account_id);

CREATE TABLE IF NOT EXISTS labels (
    id INTEGER PRIMARY KEY,
    account_id INTEGER NOT NULL,
    label_name TEXT NOT NULL,
    normalized_name TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(account_id) REFERENCES accounts(id),
    UNIQUE(account_id, label_name)
);

CREATE INDEX IF NOT EXISTS idx_labels_account ON labels(account_id);

CREATE TABLE IF NOT EXISTS message_labels (
    id INTEGER PRIMARY KEY,
    account_id INTEGER NOT NULL,
    message_db_id INTEGER NOT NULL,
    label_id INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(account_id) REFERENCES accounts(id),
    FOREIGN KEY(message_db_id) REFERENCES messages(id),
    FOREIGN KEY(label_id) REFERENCES labels(id),
    UNIQUE(message_db_id, label_id)
);

CREATE INDEX IF NOT EXISTS idx_message_labels_account ON message_labels(account_id);
CREATE INDEX IF NOT EXISTS idx_message_labels_message ON message_labels(message_db_id);

-- account_id NULL = global category (visible to all accounts)
CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY,
    account_id INTEGER,
    path TEXT NOT NULL,
    display_name TEXT,
    description TEXT,
    parent_path TEXT,
    is_locked INTEGER NOT NULL DEFAULT 0,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(account_id) REFERENCES accounts(id)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_categories_account_path
ON categories(account_id, path) WHERE account_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_categories_global_path
ON categories(path) WHERE account_id IS NULL;

CREATE TABLE IF NOT EXISTS category_aliases (
    id INTEGER PRIMARY KEY,
    account_id INTEGER,
    alias TEXT NOT NULL,
    category_path TEXT NOT NULL,
    FOREIGN KEY(account_id) REFERENCES accounts(id)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_category_aliases_global
ON category_aliases(alias) WHERE account_id IS NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_category_aliases_account
ON category_aliases(account_id, alias) WHERE account_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS category_rules (
    id INTEGER PRIMARY KEY,
    account_id INTEGER,
    name TEXT NOT NULL,
    description TEXT,
    rule_json TEXT NOT NULL,
    category_path TEXT,
    priority INTEGER DEFAULT 100,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(account_id) REFERENCES accounts(id)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_category_rules_global
ON category_rules(name) WHERE account_id IS NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_category_rules_account
ON category_rules(account_id, name) WHERE account_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS classifications (
    id INTEGER PRIMARY KEY,
    account_id INTEGER,
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
    FOREIGN KEY(account_id) REFERENCES accounts(id),
    FOREIGN KEY(message_db_id) REFERENCES messages(id)
);

CREATE INDEX IF NOT EXISTS idx_classifications_message ON classifications(message_db_id);
CREATE INDEX IF NOT EXISTS idx_classifications_thread ON classifications(thread_key);
CREATE INDEX IF NOT EXISTS idx_classifications_category ON classifications(category_path);
CREATE INDEX IF NOT EXISTS idx_classifications_account ON classifications(account_id);

CREATE TABLE IF NOT EXISTS category_proposals (
    id INTEGER PRIMARY KEY,
    account_id INTEGER,
    proposed_path TEXT NOT NULL,
    display_name TEXT,
    reason TEXT,
    example_message_ids_json TEXT,
    confidence REAL,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    reviewed_at TEXT,
    reviewed_note TEXT,
    FOREIGN KEY(account_id) REFERENCES accounts(id)
);

CREATE TABLE IF NOT EXISTS security_findings (
    id INTEGER PRIMARY KEY,
    account_id INTEGER,
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
    FOREIGN KEY(account_id) REFERENCES accounts(id),
    FOREIGN KEY(message_db_id) REFERENCES messages(id),
    FOREIGN KEY(attachment_id) REFERENCES attachments(id)
);

CREATE INDEX IF NOT EXISTS idx_security_message ON security_findings(message_db_id);
CREATE INDEX IF NOT EXISTS idx_security_attachment ON security_findings(attachment_id);
CREATE INDEX IF NOT EXISTS idx_security_type ON security_findings(finding_type);
CREATE INDEX IF NOT EXISTS idx_security_account ON security_findings(account_id);

CREATE TABLE IF NOT EXISTS exports (
    id INTEGER PRIMARY KEY,
    account_id INTEGER,
    export_type TEXT NOT NULL,
    export_profile TEXT NOT NULL,
    output_path TEXT NOT NULL,
    notebooklm_limit_profile TEXT,
    source_count INTEGER DEFAULT 0,
    message_count INTEGER DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'running',
    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TEXT,
    metadata_json TEXT,
    FOREIGN KEY(account_id) REFERENCES accounts(id)
);

CREATE INDEX IF NOT EXISTS idx_exports_account ON exports(account_id);

CREATE TABLE IF NOT EXISTS export_items (
    id INTEGER PRIMARY KEY,
    account_id INTEGER,
    export_id INTEGER NOT NULL,
    output_file TEXT NOT NULL,
    message_db_id INTEGER,
    category_path TEXT,
    sequence INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(account_id) REFERENCES accounts(id),
    FOREIGN KEY(export_id) REFERENCES exports(id),
    FOREIGN KEY(message_db_id) REFERENCES messages(id)
);
