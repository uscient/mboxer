# NotebookLM packing and publication

Limits come from `exports.notebooklm.profiles` in the selected configuration,
then CLI overrides. These are MBoxer's local packing settings, not verified
current NotebookLM subscription quotas. Check your service plan before uploading.
The bundled default selects `ultra_safe`; bundled source budgets are:

| Profile | Maximum sources | Reserved slots | Effective budget | Target sources |
| --- | ---: | ---: | ---: | ---: |
| `standard` | 50 | 10 | 40 | 40 |
| `plus` | 100 | 20 | 80 | 80 |
| `pro` | 300 | 50 | 250 | 250 |
| `ultra` | 600 | 75 | 525 | 525 |
| `ultra_safe` | 600 | 100 | 500 | 450 |

Use `mboxer config-example` to inspect all bundled byte, word, and message
limits. Custom profile names are supported. An explicit configuration file must
contain its own profile mapping; loading that file does not merge in bundled
profiles. `exports.notebooklm.profile` selects the default name, and `--profile`
overrides it. This is separate from `--export-profile`, which selects the
security projection (`raw`, `reviewed`, `scrubbed`, or `metadata-only`).

For an existing database/account, preview a scrubbed export before publishing
(replace `personal` with your account key):

```bash
mboxer config-example > /tmp/mboxer-notebooklm.yaml
mboxer export notebooklm --config /tmp/mboxer-notebooklm.yaml \
  --db var/mboxer.sqlite --account personal --profile ultra_safe \
  --export-profile scrubbed --findings-policy block --dry-run
```

Remove `--dry-run` to publish. `--out` overrides `paths.notebooklm_dir`; each
account writes under `<out>/<account-key>/`. Relative paths resolve from the
working directory, not from the configuration file's directory.

## Complete files and global budgets

Every profile defines `max_sources`, `reserved_sources`, `target_sources`,
`max_words_per_source`, `target_words_per_source`, `max_bytes_per_source`,
`target_bytes_per_source`, and `max_messages_per_source`.

- The hard source budget is `max(0, max_sources - reserved_sources)` across every
  category/year group in one account export. `--allow-full-source-budget` uses
  the reserved slots too, up to `max_sources`; it never allows unlimited sources.
  With `--accounts KEY1,KEY2`, each account gets that budget separately. Accounts
  publish sequentially; failure of a later account does not undo an earlier one.
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
- `--dry-run` runs the same projection and packing calculation without writing
  live output or export ledger rows. The library result contains exact planned
  file/message counts; the CLI currently prints the category/band group count,
  which can be smaller than the planned file count. It uses temporary disk space
  and does not test publication ownership or locks.

Positive hard and target limits are required, with nonnegative reserved slots.
YAML byte limits use literal bytes. Despite their names, CLI `--max-mb` and
`--target-mb` convert whole-number values using 1,048,576 bytes per MiB. The local
CLI guard for more than 200 MiB per file requires `--force`; this flag does not
bypass configured packing caps or confirm service acceptance. Values over
500,000 words trigger a local warning rather than an additional hard cap.
`max_messages_per_source` is configurable in the profile, with no matching CLI
override.

The bundled `format` and `split_strategy` mappings are recorded in manifests as
descriptive metadata. They do not change the renderer or grouping. Markdown
headers, message metadata, manifests, and category/year grouping are fixed in
the implementation; `prefer_thread_integrity` does not keep a thread together.
The current Markdown renderer does not include attachment references or separate
security-note sections, even though those names appear in the metadata mapping.

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
JSONL replaces the two requested filenames without NotebookLM's prior-generation
ownership/hash checks; choose a destination whose existing files may be replaced.

For library callers, successful publication calls `conn.commit()`, including any
caller writes already pending on that connection. Failure and NotebookLM dry-run
roll back only the export savepoint, preserving earlier pending caller work.

## Memory, disk, and recovery

Archive bodies are processed one message at a time. NotebookLM keeps projected
Markdown, ordering, and distinct thread counts in disposable SQLite files and
packs each source through a temporary disk stream. JSONL streams projections to
disk and uses disposable SQLite for distinct thread counts. Security scanning
iterates its cursor. Memory still depends on the largest individual message and
bounded database/copy buffers. New per-source metadata grows up to the selected
source budget. Re-publication also loads the previous JSON manifest and its
ownership inventory into memory, even if that older generation exceeds the
newly selected budget.

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
