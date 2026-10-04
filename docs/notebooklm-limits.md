# NotebookLM packing and publication

Limits come from the selected configuration profile plus CLI overrides. They
describe the local export contract; check your service plan separately before
uploading. Existing profile names remain `standard`, `plus`, `pro`, `ultra`, and
`ultra_safe`.

## Complete files and global budgets

Every profile defines `max_sources`, `reserved_sources`, `target_sources`,
`max_words_per_source`, `target_words_per_source`, `max_bytes_per_source`,
`target_bytes_per_source`, and `max_messages_per_source`.

- The hard source budget is `max(0, max_sources - reserved_sources)` across every
  category/year group in one account export. `--allow-full-source-budget` uses
  the reserved slots too, up to `max_sources`; it never allows unlimited sources.
- Byte counts are UTF-8 bytes of the complete Markdown file. Word counts use
  whitespace splitting on the complete rendered text. Both include source
  headers, message metadata, separators, and message-count digits.
- Byte, word, and message maxima are hard per-file caps. A single message that
  cannot fit with its headers raises an error. Messages are never truncated or
  silently omitted to satisfy a cap.
- Target bytes and words are preferred split points. If those split points
  exhaust the source budget, packing retries with hard caps only. `target_sources`
  remains a planning/warning value rather than a distribution algorithm.
- Groups retain category/year boundaries. If they cannot fit the global budget,
  the whole export fails before publication. Threads can span files; packing
  remains message based.
- `--dry-run` runs the same projection and packing calculation, returning actual
  planned file/message counts without writing live output or export ledger rows.
  It uses temporary disk space. It does not test publication ownership or locks.

Positive hard and target limits are required, with nonnegative reserved slots.
The existing CLI recommendation guard for more than 200 MiB per file still
requires `--force`; this flag does not bypass the configured packing caps.

## Re-export and stale files

NotebookLM stages every source and both manifests before replacing the managed
generation under `<out>/<account-key>/`. The previous JSON manifest identifies
owned source paths and SHA-256 hashes. Obsolete owned packs are removed, including
when every message is excluded. Unrelated files are retained. Modified owned
packs, malformed inventories, symlink destinations, and unrelated filename
collisions cause an error before replacement.

A small `.mboxer-notebooklm.json` marker identifies ownership even after a valid
zero-source export. Existing nonempty MBoxer manifests can be adopted without
this marker. Empty legacy manifests cannot establish ownership and require a
new destination or manual review and relocation of the old export. Files already
orphaned by older buggy runs cannot safely be identified from a newer manifest;
inspect those old directories separately. Ownership markers are local bookkeeping,
not authentication against a person who can alter the export directory.

JSONL similarly stages its output and matching manifest before publication.
Late residual-policy blocks leave the previous output pair intact. Successful
exports commit their ledger after all staged files are installed; handled copy,
rename, or commit failures restore previous output and roll back new ledger rows.

## Memory, disk, and recovery

Archive bodies are processed one message at a time. NotebookLM keeps projected
Markdown, ordering, and distinct thread counts in disposable SQLite files and
packs each source through a temporary disk stream. JSONL streams projections to
disk and uses disposable SQLite for distinct thread counts. Security scanning
iterates its cursor. Memory still depends on the largest individual message,
bounded database/copy buffers, and per-source metadata up to the source budget.

Allow disk space for projections, staged output, an installation copy on the
destination filesystem, and the previous output during publication. Temporary
directories and publication backups are private; published new files use mode
0600 where POSIX permissions apply. Cross-filesystem destinations are supported.

SQLite and filesystem updates are not crash-atomic together. A lock prevents
cooperating publishers from changing the same destination at once. A hard kill
or failed rollback may leave that lock and a sibling `.mboxer-backup-*` directory.
Its `recovery.json` identifies the destination and paths; `previous/` holds old
files with their original relative names. Stop competing exports, inspect the
destination and database, and preserve remaining backups before manual recovery
and stale-lock removal. Do not blindly replay a backup: the database commit may
already have succeeded. Backups may contain prior raw exports. The lock is not a
defense against arbitrary concurrent filesystem writers.
