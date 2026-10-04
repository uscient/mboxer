# Ingest integrity and upgrade behavior

## Source identity and retries

An input source is identified by its registered account and resolved filesystem
path. Ingest computes the MBOX SHA-256 before processing it. If that path already
has a different recorded hash, ordinary ingest and `--resume` reject it;
`--force` explicitly replaces its stored message evidence. The same input path
can be ingested independently for different accounts.

Messages are deduplicated by source and MBOX key, not by Message-ID or body hash.
An ordinary rerun skips keys already present. It does not update normalization or
backfill attachments on those messages: use an intentional force ingest when
those stored results need rebuilding.

Ordinary ingest commits in configured batches. Each message, its thread update,
labels, and requested attachment metadata form a savepoint: a failed write leaves
no partially stored message to be skipped on retry. A checkpoint does not advance
past a failed message, even if subsequent messages succeed.

`--resume` selects the latest run for that source whose status is `running` or
`interrupted`. It enumerates the archive keys, skips through the saved
`last_mbox_key`, and processes subsequent keys. A missing saved key records
`InvalidResumeCheckpoint` and restarts from the beginning; stored keys are still
skipped as duplicates. With no resumable run, ingestion starts a new attempt.

An ordinary run that reaches the end has status `completed` even when individual
messages failed. Its nonzero error count makes the CLI fail; rerunning the archive
retries absent messages. `--resume` does not select that completed run. Counters
on a resumed run describe the latest invocation; earlier `ingest_errors` rows
remain available. `skipped` includes both skipped checkpoint keys and duplicate
stored keys.

## Force replacement

`--force` replaces the entire selected account/source in one SQLite transaction,
including messages that disappeared from a shorter archive. Failed message
reads, normalization, database writes, or requested attachment extraction cause
the replacement to roll back and retain previous message evidence. The source
hash is checked again before committing. A changed hash, or failure to read or
stat the source at this check, records a failed run and preserves the prior source
identity. A handled keyboard interruption records an interrupted replacement.

`--force --resume` always starts a complete replacement and ignores an older
checkpoint. An interrupted replacement must be rerun with `--force`. Account,
source, and run registration precede the replacement transaction; a failed first
import can therefore leave registration/history rows even with no messages.

Successful replacement rebuilds that source's thread summaries and invalidates
affected thread classifications, including a newly joined thread in another
source of the same account. Untouched messages keep their inherited export
restrictions until successful reclassification replaces them. A failed or
unmatched reclassification retains those restrictions. Thread classification
reads and writes share one SQLite snapshot; a concurrent replacement that makes
it stale causes classification to fail and requires retry.

Unrelated accounts and sources retain their messages. Historical export runs and
existing export files remain. For replaced messages, message classifications,
linked export items, findings, message-label associations, and attachment rows are
removed. Account label definitions remain. Current exporters record file-level
items with NULL `message_db_id`, so those historical items also remain; see the
[schema](sqlite-schema.md).

## Interruptions and filesystem boundaries

During ordinary message processing, a handled `KeyboardInterrupt` discards the
incomplete message, commits completed messages and the last safe checkpoint, and
returns `interrupted`. Force mode instead rolls back the full replacement.
Attachment writes and inserts also clean up newly created files before
re-raising `KeyboardInterrupt` or `SystemExit`. A `SystemExit` is not converted
into an interrupted result: it propagates after cleanup, and the database retains
earlier committed batches; run status can remain `running`.

Previously extracted payload files are retained even after successful force
replacement removes their database rows. New files from handled failed messages
or replacements are cleaned up. SQLite and the filesystem are not one atomic
store: abrupt process termination can leave unreferenced new payload files, and
filesystem failures can prevent cleanup. Existing payloads are never overwritten
to resolve filename collisions.

Force replacement holds a SQLite write transaction and can grow its WAL for the
duration of a large archive. Ingest processes message payloads one at a time but
enumerates MBOX keys, and force mode tracks replaced IDs and created file paths.
It is not a constant-memory archive reader. Ordinary ingestion checks source
identity before processing but does not repeat the final hash check used by
force mode. Keep the input archive unchanged during either operation.

| Returned ingest outcome | CLI exit code |
|---|---|
| Completed, no errors | `0` |
| Completed with errors, or failed replacement | `1` |
| Handled keyboard interruption | `130` |

These codes describe returned ingest results. Failures before a result is
returned, such as an inaccessible source, can raise an exception instead.

## Normalization and database upgrades

Newly ingested dates with known offsets are converted to UTC. Missing, invalid,
or unknown offsets leave `date_utc` absent while preserving the original date
header. Stored body hash, character count, and word count describe the retained,
possibly truncated text. The first usable plain-text part is preferred; HTML is
converted with a simple tag-stripping fallback when plain text is absent. Raw
HTML is stored only when `ingest.store_body_html` is enabled and is not subject
to the text character limit.

Attachment counting and extraction use the same MIME selection: attachment
disposition or a filename, including named inline parts. Ingest stores attachment
rows and payloads only with `--extract-attachments`. Filenames are sanitized,
bounded by UTF-8 bytes, and disambiguated; details are in
[naming conventions](naming-conventions.md).

Schema upgrades are transactional per migration and check foreign keys before
commit. They preserve legacy IDs and unassigned accounts, repair NULL address
lists at migration 003, and reject malformed address data or nonempty abandoned
staging tables. The [schema reference](sqlite-schema.md) describes these cases.
Migrations do not rewrite existing message normalization; rebuilding it requires
an explicit force ingest.
