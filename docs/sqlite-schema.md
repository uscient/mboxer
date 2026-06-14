# SQLite Schema Plan

The runtime database is built by applying the versioned migrations in `src/mboxer/db/migrations/`
(run by `mboxer init-db`). `src/mboxer/db/schema.sql` is a reference snapshot of the full schema —
validated in CI, but not executed at runtime. A `schema_migrations` table records which migrations
have been applied.

## Core concepts

```text
accounts
  One row per registered account. All evidence is keyed by account for isolation.

mbox_sources
  One row per source MBOX file ever ingested.

ingest_runs
  One row per import attempt. Tracks status, checkpoint, and counters.

ingest_errors
  Per-run record of messages that failed to ingest.

messages
  One row per email message. Stores metadata, normalized body text, hashes, and thread hints.

threads
  Thread groupings with participant aggregation and date ranges.

attachments
  One row per attachment. Stores original filename, safe filename, content type, path, hash, and extraction status.

labels / message_labels
  Gmail labels and the message-to-label associations.

categories
  Governed taxonomy. Category paths are slash-delimited filesystem paths.

category_aliases / category_rules
  Alternate names and stored rule definitions for the taxonomy.

classifications
  Rule (and future model) output for message or thread classification.

category_proposals
  Proposed taxonomy additions pending review.

security_findings
  Local security/sensitivity scan findings.

exports
  Export run metadata.

export_items
  Mapping between exported source files and included messages.
```

## Resume strategy

Conservative resume avoids fragile byte offsets:

1. Find the latest incomplete `ingest_runs` row for the MBOX source.
2. Read `last_mbox_key`.
3. Iterate from the beginning until that key is found.
4. Continue processing from there.
5. Still skip duplicate messages already present in `messages` unless `--force` is used.

This is slower than true byte-offset resume, but safer and portable.
