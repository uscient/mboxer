# mboxer

MBoxer turns Gmail/Google Takeout MBOX archives into local SQLite records,
NotebookLM-oriented Markdown source packs, and JSONL for RAG or archive review.
Ingest, classification, scanning, and export run locally through explicit CLI
commands. MBoxer does not upload mail or call an LLM.

The main workflow is **MBOX → SQLite → rules → body scan → local exports**.
Inspect the output before choosing what to share with another service.

## What it does

- Ingests normalized messages, Gmail labels, thread metadata, and optional
  attachments into an account-scoped local archive.
- Resumes interrupted ingest, avoids duplicate insertion on repeated ingest,
  and supports transactional replacement of a changed source.
- Classifies messages or threads using ordered YAML rules, with thread-to-message
  inheritance and explicit export content policies.
- Scans stored body text and redacts configured regex patterns during export.
- Packs Markdown by account, category, and year within configured file and source
  budgets; exports message records as JSONL.
- Records export lineage in SQLite and adjacent manifests, and removes obsolete
  managed NotebookLM packs on successful re-export.

Python 3.11 or newer is required; CI tests Python 3.11 and 3.12. The distribution
name is `uscient-mboxer`; the import and CLI name are `mboxer`.

[HOWTO.md](HOWTO.md) is the first-run walkthrough.
[PROJECT.md](PROJECT.md) maps the implementation.
[Architecture](docs/architecture.md) describes storage and processing boundaries.

## Install the released package

In a POSIX shell:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install uscient-mboxer
mboxer --help
```

The installed package includes its configuration example and database migrations.
The synthetic fixture generator used below is part of the source checkout.

## Quick start with synthetic mail

Run these commands from a source checkout in a POSIX shell:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .

mkdir -p config
mboxer config-example > config/mboxer.yaml
python tests/fixtures/make_synthetic.py

mboxer init-db --config config/mboxer.yaml
mboxer account add demo --config config/mboxer.yaml
mboxer ingest tests/fixtures/synthetic.mbox \
  --config config/mboxer.yaml --account demo --source-name Synthetic
mboxer classify --config config/mboxer.yaml --account demo
mboxer review-categories --config config/mboxer.yaml --account demo
mboxer security-scan --config config/mboxer.yaml --account demo
mboxer export notebooklm --config config/mboxer.yaml --account demo --dry-run
mboxer export notebooklm --config config/mboxer.yaml --account demo
mboxer export jsonl --config config/mboxer.yaml --account demo
```

This creates a demonstration account in `var/mboxer.sqlite`, Markdown under
`exports/notebooklm/demo/`, and JSONL at `exports/rag/demo/messages.jsonl`.
The walkthrough explains how to add a separate account for a real archive.
Do not overwrite an existing customized configuration with `config-example`.

`python -m mboxer` provides the same CLI as `mboxer`. Use `mboxer --help` and
subcommand help, such as `mboxer export notebooklm --help`, for available flags.

## Configuration

Print the canonical example with `mboxer config-example`; its packaged source is
[src/mboxer/defaults.yaml](src/mboxer/defaults.yaml).

- `--config PATH` selects an explicit YAML file. A missing or invalid explicit
  file is an error.
- Without `--config`, `config/mboxer.example.yaml` in the working directory takes
  precedence over bundled defaults. `config/mboxer.yaml` is never auto-selected.
- `--db PATH` overrides the database path. Otherwise MBoxer uses `paths.database`,
  the legacy `project.default_database`, then `var/mboxer.sqlite`.
- Relative configuration and data paths are relative to the working directory,
  not the YAML file's directory. Common flags follow the selected command.
- A user configuration is not merged wholesale with the example. Individual
  settings have fallbacks, but omitted rules and NotebookLM profile definitions
  are not silently imported. Start from the printed example.

The configuration controls paths, ingest batch size and body retention,
classification level and rules, taxonomy seeds, body redaction, and export
settings. `classification.level` defaults to `thread`; `--level message|thread`
overrides it. Resume and attachment extraction are explicit ingest flags.
There is no environment-variable configuration layer. In a partial custom YAML,
omitted `security.redact_*` flags are off; `scrub_enabled: true` alone does not
enable them. The printed example enables all four current redaction types.

**Body retention matters:** `ingest.max_body_chars` defaults to 50,000 characters
per normalized message body; longer bodies are truncated during ingest.
`ingest.store_body_html` defaults to `false`. Even a `raw` export contains the
stored normalized body, not the original MIME message. Keep the original MBOX
when full source fidelity is needed.

See [configuration reference](docs/configuration.md) for all active keys,
precedence, legacy settings, and validation behavior.

## Accounts and ingest

Accounts share a database but have distinct source, classification, and export
scope. Use portable directory names for account keys, such as `primary-gmail`;
keys are also used in output paths and are not silently renamed.

```bash
mboxer account add primary-gmail --display-name "Primary Gmail" \
  --email user@example.com --config config/mboxer.yaml
mboxer account list --config config/mboxer.yaml
mboxer account show primary-gmail --config config/mboxer.yaml
mboxer account update primary-gmail --display-name "Personal mail" \
  --config config/mboxer.yaml

mboxer ingest /path/to/archive.mbox --account primary-gmail \
  --source-name "Gmail Takeout" --resume --config config/mboxer.yaml
```

Replace `/path/to/archive.mbox` with an extracted MBOX. With exactly one account,
account-scoped commands can auto-select it; with multiple accounts they require
`--account`, except the explicit multi-account NotebookLM option below.

| Ingest flag | Behavior |
|---|---|
| `--resume` | Continues a running/interrupted run for the same source from its checkpoint. |
| `--extract-attachments` | Writes attachment files beneath `paths.attachments_dir`, grouped by account, year, and message, with source identity recorded in SQLite. |
| `--create-account` | Creates the specified `--account` if absent. |
| `--force` | Replaces the stored messages for that account/source in one transaction. |

A changed MBOX at an existing account/path requires `--force`. Replacement also
invalidates affected derived classifications, findings, and export-item links;
classify, scan, and export again afterward. Failed or interrupted replacement
rolls back database changes and removes newly created attachment payloads during
handled failure recovery. Previous payload files are retained even after successful
replacement; database/filesystem changes are not jointly crash-atomic. Existing
published exports remain until a later export. See [ingest and recovery](docs/ingest-integrity.md).

Normal ingest commits batches and records per-message errors. Its CLI exits `1`
when errors occur and `130` on interruption; successful completion exits `0`.
See [the walkthrough](HOWTO.md) before processing a large archive.

## Classification and categories

Rules run locally in their configured order; the first matching rule with an
assignment wins. Match clauses use **OR**, not AND:

- `from_domain` matches a domain in the sender or To-recipient list.
- `from_contains` matches an address fragment in the sender or To-recipient list.
- `subject_contains` matches a subject phrase.

Cc and Bcc addresses are not included in these match predicates. At thread level,
address matching aggregates senders and To recipients, and subject
matching uses the first nonempty subject with reply/forward prefixes removed.
`assign` records confidence `1.0`; `assign_hint` records `0.75`. Assignments carry
a category and optional sensitivity, NotebookLM priority, and content profile.
Priority and sensitivity are metadata; `export_profile` controls content handling.

```bash
mboxer classify --level thread --account primary-gmail --config config/mboxer.yaml
mboxer review-categories --account primary-gmail --config config/mboxer.yaml
```

Thread results are inherited by messages unless an explicit message rule has
equal or greater confidence. Classification skips already classified targets;
editing rules and rerunning is not a general reclassification operation.

Category paths are normalized into slash-delimited slugs. `taxonomy.locked_categories`
seeds global category rows with a locked flag during classification; that flag is
metadata, not a database deletion guard. Rules can assign paths outside that list.
There is no category-deletion CLI.

`review-categories` shows category classification-row counts and existing pending
proposals. Counts may exceed distinct messages when retained classifications
coexist. Rule classification does not generate proposals. To act on a known
pending proposal ID, choose either approval or rejection:

```bash
mboxer approve-category 123 --note "Reviewed" --config config/mboxer.yaml
# Or: mboxer reject-category 123 --note "Not needed" --config config/mboxer.yaml
```

Replace `123` with the actual ID. Approval creates or activates a category; it
does not reclassify messages.

## Export formats

### NotebookLM Markdown

```bash
mboxer export notebooklm --account primary-gmail --profile ultra_safe \
  --out exports/notebooklm --config config/mboxer.yaml
```

The output layout is `<out>/<account>/<category>/<year>/<category>-<year>-001.md`.
Undated messages use `undated`. Packs contain an account/category header and each
message's subject, sender, date, message ID, and projected body. Recipient lists
and attachment references are not rendered into Markdown.

`manifest.csv` and `manifest.json` accompany each account's packs. They describe
source files, counts, hashes, limits, and export posture; the CSV is not a
row-per-message export. Re-export replaces files owned by the previous generation
and removes obsolete owned packs while preserving unrelated files. Modified
managed files or conflicting destinations cause errors.

```bash
mboxer export notebooklm --accounts primary-gmail,work-gmail \
  --out exports/notebooklm --config config/mboxer.yaml
```

Multi-account export processes each account separately, with a separate directory,
source budget, and commit. It is not one combined source budget or transaction.

### JSONL

```bash
mboxer export jsonl --account primary-gmail \
  --out exports/rag/messages.jsonl --config config/mboxer.yaml
```

Each exported message becomes a JSON object containing stored metadata, projected
body text, source information, and optional classification. The CLI inserts the
account directory unless it already appears as a path component; this example
writes `exports/rag/primary-gmail/messages.jsonl` and
`exports/rag/primary-gmail/messages.manifest.json`.

`exports.jsonl.include_classification: false` hides classification metadata in the
output, while content policy still applies. JSONL has no `--dry-run` option.

## NotebookLM packing limits

`--profile` selects a local size-limit preset. These preset names and numbers are
MBoxer configuration, not a claim about current NotebookLM subscription quotas.

| Preset | Max sources | Reserved sources | Target sources | Target words/source |
|---|---:|---:|---:|---:|
| `standard` | 50 | 10 | 40 | 300,000 |
| `plus` | 100 | 20 | 80 | 300,000 |
| `pro` | 300 | 50 | 250 | 300,000 |
| `ultra` | 600 | 75 | 525 | 300,000 |
| `ultra_safe` (default) | 600 | 100 | 450 | 225,000 |

The hard budget is `max_sources - reserved_sources` for one account. Complete
rendered UTF-8 files, including headers and separators, must fit hard byte, word,
and message limits. The exporter never truncates a stored message to satisfy a
packing cap. Threads may cross file boundaries. Target bytes/words are preferred
split points; `target_sources` is a warning/planning value, not a packing target.

CLI overrides are `--max-sources`, `--reserved-sources`, `--target-sources`,
`--max-words`, `--target-words`, `--max-mb`, and `--target-mb`; message caps are YAML
settings. The `*-mb` flags use MiB (1,048,576 bytes). `--allow-full-source-budget`
sets reserved slots to zero. Export `--force` permits a configured ceiling above
200 MiB; it does not bypass the selected hard limits or force file replacement.

`--dry-run` performs projection and packing using temporary disk space but does
not publish files or record export rows. It does not verify destination ownership
or publication locks. Body processing uses disk staging rather than retaining all
archive text in memory. Temporary disk usage and the largest message still matter;
ingest and thread classification have their own memory requirements.

See [packing, publication, and recovery](docs/notebooklm-limits.md) for stale-file
ownership, cross-filesystem publication, and failure recovery. Filesystem changes
and SQLite commits are not jointly crash-atomic.

## Content profiles and security

`--export-profile` controls content independently of the NotebookLM size `--profile`.
Without an override, exporters select one effective classification per message,
using confidence and direct-rule precedence. Equally ranked conflicting policies
block export. Unclassified messages use `security.default_export_profile`, whose
bundled value is `scrubbed`.

| Content profile | Export behavior |
|---|---|
| `raw` | Stored normalized body is unchanged. |
| `reviewed` | Same body-redaction path as `scrubbed`; no human-review state is checked. |
| `scrubbed` | Configured regex redactions apply when `security.scrub_enabled` is true. |
| `metadata-only` | Body is omitted; message metadata remains. |
| `exclude` | Message is omitted. |

The CLI accepts the first four profiles. An explicit `--export-profile` overrides
per-message policy, **including `exclude`**, and can resolve a policy conflict.
Omit it when classification-specific restrictions should remain in effect.

Scanning and redaction cover stored/projected **body text only**. Subjects,
addresses in headers, category names, account keys, and attachment content are not
scrubbed or checked by the export residual gate. Metadata-only output is therefore
not an anonymized export. Detectors cover email addresses, phone numbers,
SSN-like values, and credit-card-like values using regexes; there is no semantic
PII detection, attachment scanning, quarantine, or malware analysis.

```bash
mboxer security-scan --account primary-gmail --config config/mboxer.yaml
mboxer export notebooklm --account primary-gmail --findings-policy block \
  --config config/mboxer.yaml
```

`security-scan` stores local findings, including short matching excerpts; it does
not redact database bodies. Export always scans the projected body again,
independently of `security.scan_enabled`:

| Findings policy | Result |
|---|---|
| `allow` | Publish and record residual counts. |
| `warn` (default) | Publish, record counts, and print a counts-only warning. |
| `block` | Exit `2` before publishing files or new export ledger rows. |

A zero finding count means these patterns were not detected in projected bodies,
not that an export contains no sensitive information. All output remains local;
MBoxer does not enforce upload destinations or encrypt the database and exports.

## Development and releases

[CONTRIBUTING.md](CONTRIBUTING.md) covers branches, PRs, verification, and releases.
[tests/README.md](tests/README.md) explains test subsets and golden fixtures.
[Performance measurements](docs/performance.md) describes repeatable synthetic
benchmarks.

```bash
python -m pip install -e ".[dev]"
python tests/fixtures/make_synthetic.py
python -m pytest
python -m ruff check src/
python -m mypy src/
```

CI runs on PRs and pushes to `dev` and `master`. The full path runs Ruff/mypy,
Python 3.11/3.12 tests, coverage on 3.11, and an installed-wheel smoke test outside
the checkout. Known documentation-only paths can skip expensive jobs while
completing `CI gate`; README changes run full checks because README is package
metadata. A separate randomized-order canary runs weekly and manually.

Versions come from git tags through `setuptools-scm`. Publishing a GitHub Release
triggers the distribution-build/PyPI workflow; there is no automatic version bump
on merge.

## Scope and limitations

The implemented interface is a local CLI. There is no web UI, Gmail API sync,
full-text search command, LLM classifier, automatic category-proposal generator,
row-per-message CSV export, or external delivery. JSONL and SQLite provide inputs
for other tools rather than implementing a RAG service themselves.

MBoxer is designed for inspectable, account-scoped archive processing. Preserve
original archives, review retention settings before ingest, and inspect exported
metadata as well as bodies before sharing.

## License

Apache License 2.0. See [LICENSE](LICENSE).
