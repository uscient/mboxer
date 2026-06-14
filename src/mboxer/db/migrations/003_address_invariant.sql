-- Migration 003: enforce JSON-array invariants for message address columns.
-- SQLite cannot add NOT NULL/CHECK constraints to existing columns in place,
-- so rebuild messages and recreate its indexes.

PRAGMA foreign_keys = OFF;

CREATE TABLE messages_new (
    id INTEGER PRIMARY KEY,
    source_id INTEGER NOT NULL,
    mbox_key TEXT NOT NULL,
    message_id TEXT,
    thread_key TEXT,
    subject TEXT,
    sender TEXT,
    recipients_json TEXT NOT NULL DEFAULT '[]' CHECK (json_type(recipients_json) = 'array'),
    cc_json TEXT NOT NULL DEFAULT '[]' CHECK (json_type(cc_json) = 'array'),
    bcc_json TEXT NOT NULL DEFAULT '[]' CHECK (json_type(bcc_json) = 'array'),
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
    account_id INTEGER REFERENCES accounts(id),
    FOREIGN KEY(source_id) REFERENCES mbox_sources(id),
    UNIQUE(source_id, mbox_key)
);

INSERT INTO messages_new (
    id,
    source_id,
    mbox_key,
    message_id,
    thread_key,
    subject,
    sender,
    recipients_json,
    cc_json,
    bcc_json,
    date_header,
    date_utc,
    body_text,
    body_html,
    body_hash,
    body_chars,
    body_word_count,
    attachment_count,
    raw_headers_json,
    created_at,
    updated_at,
    account_id
)
SELECT
    id,
    source_id,
    mbox_key,
    message_id,
    thread_key,
    subject,
    sender,
    recipients_json,
    cc_json,
    bcc_json,
    date_header,
    date_utc,
    body_text,
    body_html,
    body_hash,
    body_chars,
    body_word_count,
    attachment_count,
    raw_headers_json,
    created_at,
    updated_at,
    account_id
FROM messages;

DROP TABLE messages;
ALTER TABLE messages_new RENAME TO messages;

CREATE INDEX IF NOT EXISTS idx_messages_message_id ON messages(message_id);
CREATE INDEX IF NOT EXISTS idx_messages_thread_key ON messages(thread_key);
CREATE INDEX IF NOT EXISTS idx_messages_date_utc ON messages(date_utc);
CREATE INDEX IF NOT EXISTS idx_messages_body_hash ON messages(body_hash);
CREATE INDEX IF NOT EXISTS idx_messages_account ON messages(account_id);
CREATE INDEX IF NOT EXISTS idx_messages_account_message_id ON messages(account_id, message_id);
CREATE INDEX IF NOT EXISTS idx_messages_account_thread_key ON messages(account_id, thread_key);
CREATE UNIQUE INDEX IF NOT EXISTS idx_messages_account_source_mbox_key
ON messages(account_id, source_id, mbox_key) WHERE account_id IS NOT NULL;

PRAGMA foreign_keys = ON;
