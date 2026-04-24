# SQLite Schema Plan

The concrete schema lives in `src/mboxer/db/schema.sql`.

## Core concepts

```text
mbox_sources
  One row per source MBOX file ever ingested.

ingest_runs
  One row per import attempt. Tracks status, checkpoint, and counters.

messages
  One row per email message. Stores metadata, normalized body text, hashes, and thread hints.

attachments
  One row per attachment. Stores original filename, safe filename, content type, path, hash, and extraction status.

categories
  Governed taxonomy. Category paths are slash-delimited filesystem paths.

classifications
  Model/rule output for message or thread classification.

category_proposals
  LLM-suggested taxonomy changes pending review.

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
