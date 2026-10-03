# Ingest integrity and upgrade behavior

Ordinary ingest commits in configured batches. Each message, its thread update,
labels, and requested attachment metadata form a savepoint: a failed write leaves
no partially stored message to be skipped on retry. A resume checkpoint does not
advance past a failed message, even if subsequent messages succeed. Run counters
currently describe the latest invocation of a resumed run; error rows from earlier
invocations remain available in `ingest_errors`.

`--force` replaces the entire selected account/source in one SQLite transaction,
including messages that disappeared from a shorter archive. Failed reads,
normalization, database writes, requested attachment extraction, or interruption
roll back the replacement and retain prior message evidence and source identity.
The source hash is checked again before committing the replacement. `--force
--resume` starts a complete replacement; it never applies an older source's
checkpoint to new content. An interrupted replacement must be rerun with `--force`.

Successful replacement rebuilds source thread summaries and invalidates affected
thread classifications and inherited message classifications. This includes a
newly joined thread in another source of the same account. Run classification
again to derive results from the new evidence. Unrelated accounts and sources
retain their messages. Historical export run records remain, while replaced
message-level export items, findings, labels, and attachment rows are removed.

The atomic replacement can hold a SQLite write transaction and grow its WAL for
the duration of a large archive. Ordinary ingest retains batching. Payload files
created by a handled failed extraction or replacement are cleaned up; previously
extracted payload files are retained. SQLite and the filesystem are not one atomic
store: abrupt process termination can leave unreferenced new payload files.

The CLI exits with `0` after successful ingest, `1` when ingest reports errors or a
replacement fails, and `130` after a handled keyboard interruption. Library results
include `status` together with the existing numeric counters.

Each schema migration and its version record now commit together after a foreign
key check. At the legacy address migration boundary, a missing (`NULL`) address
list becomes `[]`; invalid non-NULL JSON still causes a recoverable failure. An
empty staging table left by the older runner is removed during retry. A nonempty
staging table requires manual recovery and is never discarded automatically.
New migrations scope source-path uniqueness by account and add composite indexes
for message and thread classification and security-finding lookups. The reference
schema is checked against migrated columns, foreign keys, and indexes.

Newly ingested dates with known offsets are converted to UTC. Unknown offsets
remain absent from `date_utc`, with the original date header preserved. Stored
body hash, character count, and word count describe the retained, possibly
truncated body. HTML is retained when `ingest.store_body_html` is enabled. Inline
parts with filenames are included in attachment extraction. Existing message
normalization is not rewritten by migration; use an intentional force ingest to
rebuild it under the new behavior.
