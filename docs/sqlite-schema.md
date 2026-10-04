# SQLite schema

The runtime database is created and upgraded by
[`src/mboxer/db/migrations/`](../src/mboxer/db/migrations/) through `mboxer init-db`.
Ingest also runs initialization before opening the database. The
[`schema.sql`](../src/mboxer/db/schema.sql) reference snapshot is not executed by
runtime initialization. A regression test compares its tables, columns, foreign
keys, and index signatures with a freshly migrated database.

## Tables and current uses

| Table | Current role |
|---|---|
| `schema_migrations` | Applied migration filenames without `.sql`, with application timestamps. |
| `accounts` | Unique account keys and optional display, email, provider, and notes fields. |
| `mbox_sources` | One source identity per account and resolved MBOX path, including size, modification time, and SHA-256. Re-ingesting that path reuses its source row. |
| `ingest_runs` | Import attempts, or resumed attempts sharing a row; status, checkpoint, counters, and timestamps. |
| `ingest_errors` | Per-run read, normalization, storage, checkpoint, or source-verification failures. |
| `messages` | Normalized headers, address arrays, retained text/HTML, body metrics, and message/thread identifiers. |
| `threads` | Per-source thread summaries: count and date range, with subject and up to 20 sender/recipient entries captured from the first stored message. Later messages update count and dates, not that participant list. |
| `attachments` | Decoded original filename, sanitized base filename, actual storage path, payload hash/size, MIME metadata, and extraction status. Ingest creates these rows only when attachment extraction is requested. |
| `labels`, `message_labels` | Account-specific Gmail label definitions and message associations. |
| `categories` | Global or account-specific normalized taxonomy paths and display/lock/active metadata. |
| `category_aliases`, `category_rules` | Schema support for aliases and stored rules. Current classification reads YAML rules, not these tables. |
| `classifications` | Message or thread assignments, policy metadata, confidence, and classifier provenance. Thread records also store participant/date summaries and selected body excerpts. |
| `category_proposals` | Stored proposed paths and their review status. The current CLI can approve/reject existing proposals; rule classification does not create them. |
| `security_findings` | Regex findings from stored message bodies. Attachment-related columns exist, but attachment scanning is not implemented. |
| `exports` | Completed export metadata, including output path, profile, counts, and JSON lineage metadata. Failed publication does not leave a completed export row. |
| `export_items` | One row per output file/pack for each successful export run. The schema permits `message_db_id`, but current JSONL and NotebookLM exporters leave it NULL; this is not a complete message-to-file membership ledger. |

The schema contains fields for possible richer classification, including
`model_name`, but their presence does not mean an LLM classifier is implemented.
See [architecture](architecture.md) for the current processing flow.

## Identity and constraints

New ingestion uses a registered account. Nullable `account_id` columns preserve
unassigned legacy evidence; migration does not create a default account or
automatically assign those rows. In taxonomy tables, NULL instead denotes a
global definition. Account isolation also depends on application queries: the
schema has separate account/source/message foreign keys, not a composite
constraint proving that every referenced row belongs to the same account.

Source paths are unique within an account; a partial unique index also prevents
duplicate source paths among legacy NULL-account rows. The same path can belong
to two different accounts. Messages are unique by `(source_id, mbox_key)`.
`message_id` and `body_hash` have lookup indexes, not uniqueness constraints:
copies at other source keys remain separate records.

Thread summary rows are unique by `(thread_key, source_id)`. Account-scoped thread
classification reads messages across sources sharing that thread key; it does
not use the `threads.participants_json` snapshot to build its participant set.
Classifications are retained evidence and can contain competing rows. Export
policy resolution selects among them rather than relying on a unique constraint.

`recipients_json`, `cc_json`, and `bcc_json` are non-NULL JSON arrays with `[]` as
their default. SQLite checks the array shape; Python address decoding additionally
requires every member to be a string. Other JSON columns are not covered by that
address-array invariant.

## Migration history and recovery

| Migration | Change |
|---|---|
| `001_initial` | Initial archive, classification, taxonomy, finding, and export tables. |
| `002_multi_account` | Accounts, Gmail labels, account references, and global/account-specific taxonomy indexes. |
| `003_address_invariant` | Rebuilds messages with non-NULL JSON-array checks for recipient, Cc, and Bcc fields. |
| `004_account_source_identity` | Replaces globally unique source paths with account-scoped uniqueness while preserving legacy NULL-account paths. |
| `005_evidence_lookup_indexes` | Composite classification and security-finding indexes for per-message and per-thread lookups. |

The migration runner enables WAL and applies each pending migration inside
`BEGIN IMMEDIATE`. Table rebuilds temporarily disable foreign-key enforcement;
`PRAGMA foreign_key_check` must succeed before the migration and its ledger row
commit together. A failure rolls back that migration, while earlier successful
migrations remain applied.

A database containing `messages` without a migration ledger is treated as an
initial-schema legacy database. Before migration 003, legacy NULL address lists
become `[]`; invalid non-NULL JSON fails the migration. Retry removes an empty
`messages_new` table left by an older runner, but a nonempty table requires manual
recovery. See [ingest integrity](ingest-integrity.md) for source replacement,
checkpoints, and filesystem recovery boundaries.
