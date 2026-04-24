-- Migration 002: multi-account support
-- Adds accounts table, labels, account_id on all core tables.
-- Recreates categories to drop the inline UNIQUE(path) constraint.
-- Foreign key enforcement is disabled during DDL to allow safe table recreation.

PRAGMA foreign_keys = OFF;

-- ── New tables ──────────────────────────────────────────────────────────────

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

CREATE TABLE IF NOT EXISTS labels (
    id INTEGER PRIMARY KEY,
    account_id INTEGER NOT NULL,
    label_name TEXT NOT NULL,
    normalized_name TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(account_id) REFERENCES accounts(id),
    UNIQUE(account_id, label_name)
);

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

-- ── Add account_id + extras to existing tables ───────────────────────────────
-- account_id is nullable to accommodate existing rows (NULL = legacy/unassigned)

ALTER TABLE mbox_sources ADD COLUMN account_id INTEGER REFERENCES accounts(id);
ALTER TABLE mbox_sources ADD COLUMN source_mtime REAL;
ALTER TABLE mbox_sources ADD COLUMN provider TEXT DEFAULT 'gmail';
ALTER TABLE mbox_sources ADD COLUMN imported_label_hint TEXT;

ALTER TABLE ingest_runs ADD COLUMN account_id INTEGER REFERENCES accounts(id);
ALTER TABLE ingest_errors ADD COLUMN account_id INTEGER REFERENCES accounts(id);

ALTER TABLE messages ADD COLUMN account_id INTEGER REFERENCES accounts(id);
ALTER TABLE threads ADD COLUMN account_id INTEGER REFERENCES accounts(id);
ALTER TABLE attachments ADD COLUMN account_id INTEGER REFERENCES accounts(id);

ALTER TABLE classifications ADD COLUMN account_id INTEGER REFERENCES accounts(id);
ALTER TABLE category_proposals ADD COLUMN account_id INTEGER REFERENCES accounts(id);
ALTER TABLE security_findings ADD COLUMN account_id INTEGER REFERENCES accounts(id);
ALTER TABLE exports ADD COLUMN account_id INTEGER REFERENCES accounts(id);
ALTER TABLE export_items ADD COLUMN account_id INTEGER REFERENCES accounts(id);

-- ── Recreate categories to drop inline UNIQUE(path) ─────────────────────────
-- account_id NULL = global category visible to all accounts

CREATE TABLE categories_v2 (
    id INTEGER PRIMARY KEY,
    account_id INTEGER REFERENCES accounts(id),
    path TEXT NOT NULL,
    display_name TEXT,
    description TEXT,
    parent_path TEXT,
    is_locked INTEGER NOT NULL DEFAULT 0,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO categories_v2 (id, account_id, path, display_name, description, parent_path, is_locked, is_active, created_at)
SELECT id, NULL, path, display_name, description, parent_path, is_locked, is_active, created_at
FROM categories;

DROP TABLE categories;
ALTER TABLE categories_v2 RENAME TO categories;

-- ── Recreate category_aliases to drop the FK to categories(path) ─────────────
-- The FK referenced UNIQUE(path) which no longer exists; enforce at app level

CREATE TABLE category_aliases_v2 (
    id INTEGER PRIMARY KEY,
    account_id INTEGER REFERENCES accounts(id),
    alias TEXT NOT NULL,
    category_path TEXT NOT NULL
);

INSERT INTO category_aliases_v2 (id, alias, category_path)
SELECT id, alias, category_path FROM category_aliases;

DROP TABLE category_aliases;
ALTER TABLE category_aliases_v2 RENAME TO category_aliases;

-- ── Recreate category_rules to drop inline UNIQUE(name) ──────────────────────
-- Allows per-account rules to share names with global rules

CREATE TABLE category_rules_v2 (
    id INTEGER PRIMARY KEY,
    account_id INTEGER REFERENCES accounts(id),
    name TEXT NOT NULL,
    description TEXT,
    rule_json TEXT NOT NULL,
    category_path TEXT,
    priority INTEGER DEFAULT 100,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO category_rules_v2 (id, account_id, name, description, rule_json, category_path, priority, is_active, created_at)
SELECT id, NULL, name, description, rule_json, category_path, priority, is_active, created_at
FROM category_rules;

DROP TABLE category_rules;
ALTER TABLE category_rules_v2 RENAME TO category_rules;

PRAGMA foreign_keys = ON;

-- ── New indexes ──────────────────────────────────────────────────────────────

CREATE INDEX IF NOT EXISTS idx_mbox_sources_account ON mbox_sources(account_id);
CREATE INDEX IF NOT EXISTS idx_messages_account ON messages(account_id);
CREATE INDEX IF NOT EXISTS idx_messages_account_message_id ON messages(account_id, message_id);
CREATE INDEX IF NOT EXISTS idx_messages_account_thread_key ON messages(account_id, thread_key);
CREATE INDEX IF NOT EXISTS idx_threads_account ON threads(account_id);
CREATE INDEX IF NOT EXISTS idx_attachments_account ON attachments(account_id);
CREATE INDEX IF NOT EXISTS idx_labels_account ON labels(account_id);
CREATE INDEX IF NOT EXISTS idx_message_labels_account ON message_labels(account_id);
CREATE INDEX IF NOT EXISTS idx_message_labels_message ON message_labels(message_db_id);
CREATE INDEX IF NOT EXISTS idx_classifications_account ON classifications(account_id);
CREATE INDEX IF NOT EXISTS idx_security_account ON security_findings(account_id);
CREATE INDEX IF NOT EXISTS idx_exports_account ON exports(account_id);

-- Account-scoped message deduplication (supplements the existing UNIQUE(source_id, mbox_key))
CREATE UNIQUE INDEX IF NOT EXISTS idx_messages_account_source_mbox_key
ON messages(account_id, source_id, mbox_key) WHERE account_id IS NOT NULL;

-- Partial unique indexes for categories (global vs account-specific)
CREATE UNIQUE INDEX IF NOT EXISTS idx_categories_account_path
ON categories(account_id, path) WHERE account_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_categories_global_path
ON categories(path) WHERE account_id IS NULL;

-- Partial unique indexes for aliases and rules
CREATE UNIQUE INDEX IF NOT EXISTS idx_category_aliases_global
ON category_aliases(alias) WHERE account_id IS NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_category_aliases_account
ON category_aliases(account_id, alias) WHERE account_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_category_rules_global
ON category_rules(name) WHERE account_id IS NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_category_rules_account
ON category_rules(account_id, name) WHERE account_id IS NOT NULL;
