# First run with MBoxer

This walkthrough starts with synthetic messages, then shows how to process a
Gmail MBOX. Commands assume a source checkout, Python 3.11 or newer, and a POSIX
shell. [README.md](README.md) summarizes capabilities; the
[configuration reference](docs/configuration.md) describes runtime settings.

## 1. Install from the checkout

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .
mboxer --help
```

`python -m mboxer` is an equivalent entrypoint. Stay in the same working directory
for this walkthrough: relative database, archive, and output paths are resolved
from there.

## 2. Create and review configuration

For a new configuration:

```bash
mkdir -p config
mboxer config-example > config/mboxer.yaml
```

If you already have `config/mboxer.yaml`, edit it instead of overwriting it.
Commands below select that file explicitly. Without `--config`, MBoxer uses a
legacy local `config/mboxer.example.yaml` if present, otherwise bundled defaults;
it does not auto-load `config/mboxer.yaml`.

Before ingesting real mail, review these settings:

- `paths.database`: the local database, default `var/mboxer.sqlite`.
- `ingest.max_body_chars`: default 50,000 characters; longer normalized bodies
  are truncated when stored. `ingest.store_body_html` defaults to `false`.
- `rules` and `classification.level`: deterministic category/content assignments;
  the default level is `thread`.
- `security`: body-redaction switches, default content profile, and residual
  findings policy.
- `exports.notebooklm.profiles`: local packing budgets. Their names do not
  establish the limits of your NotebookLM account.

Keep the original MBOX. The database and exports are processed projections, not
complete replacements for the source archive.

## 3. Exercise the pipeline with synthetic mail

Generate the repository's five-message fixture and register a separate demo
account:

```bash
python tests/fixtures/make_synthetic.py
mboxer init-db --config config/mboxer.yaml
mboxer account add demo --config config/mboxer.yaml
mboxer ingest tests/fixtures/synthetic.mbox \
  --config config/mboxer.yaml --account demo --source-name Synthetic
mboxer classify --config config/mboxer.yaml --account demo
mboxer review-categories --config config/mboxer.yaml --account demo
mboxer security-scan --config config/mboxer.yaml --account demo
```

For an existing demo account, skip `account add`. Repeating ingest of the same
unchanged source skips already stored messages.

Check packing, then publish local output:

```bash
mboxer export notebooklm --config config/mboxer.yaml --account demo --dry-run
mboxer export notebooklm --config config/mboxer.yaml --account demo
mboxer export jsonl --config config/mboxer.yaml --account demo
```

With the printed defaults, inspect:

| Output | Location |
|---|---|
| Markdown packs | `exports/notebooklm/demo/<category>/<year>/*.md` |
| NotebookLM manifests | `exports/notebooklm/demo/manifest.csv` and `manifest.json` |
| JSONL records | `exports/rag/demo/messages.jsonl` |
| JSONL manifest | `exports/rag/demo/messages.manifest.json` |

A dry run performs the same body projection and packing with temporary disk
staging. It does not publish output, write export ledger rows, or test publication
ownership and locks. Its CLI reports category/year group counts, not a listing of
all planned filenames.

## 4. Add a real account and ingest a small archive

Extract the `.mbox` file from your Gmail/Google Takeout download. Start with a small
archive or a separate small MBOX subset. Use a different account from the demo:

```bash
mboxer account add primary-gmail \
  --display-name "Primary Gmail" --email user@example.com \
  --config config/mboxer.yaml
mboxer account list --config config/mboxer.yaml
```

Replace the example email and `/path/to/sample.mbox` below with your account
metadata and archive path:

```bash
mboxer ingest /path/to/sample.mbox \
  --account primary-gmail --source-name "Gmail sample" \
  --resume --config config/mboxer.yaml
```

Add `--extract-attachments` if you want attachment files written under
`paths.attachments_dir` (default `data/attachments`), grouped by account, year, and message.
They are not scanned, quarantined, or included in Markdown packs.

`--resume` continues the same source's interrupted run from its checkpoint.
Normal ingest commits in batches and reports per-message errors; a command exit
of `1` means errors occurred, and `130` means interruption. Inspect the local
`ingest_runs` and `ingest_errors` tables when troubleshooting a partial run.

If the MBOX at the same account/path has changed, MBoxer requires `--force` for
replacement. That is a separate operation: it replaces that source's message rows
and invalidates affected derived state, rolling back database changes on failure.
Handled replacement failure also removes newly created attachment payloads;
previous payloads are retained, and the database/filesystem are not jointly
crash-atomic. Reclassify, scan, and export after a successful replacement; old
export files are not automatically regenerated. See [ingest and recovery](docs/ingest-integrity.md).

## 5. Classify and inspect

```bash
mboxer classify --config config/mboxer.yaml --account primary-gmail --level thread
mboxer review-categories --config config/mboxer.yaml --account primary-gmail
mboxer security-scan --config config/mboxer.yaml --account primary-gmail
```

`--level` overrides configuration. Rules run in order, with OR matching across
address/domain/subject clauses. Address matching uses senders and To recipients,
not Cc/Bcc. Thread classification inherits results to messages
unless an equal-or-higher-confidence explicit message rule applies. Rerunning
classification skips existing classified targets; editing YAML is not a general
reclassification mechanism.

Category review shows existing taxonomy rows and pending database proposals.
The rule classifier does not create proposals. If there is a pending proposal,
use `approve-category ID` or `reject-category ID` with the same `--config`; approval
creates or activates a category and does not classify messages.

The scan records regex findings in stored bodies. It does not scrub SQLite
contents, headers, or attachments.

## 6. Export and review locally

```bash
mboxer export notebooklm --config config/mboxer.yaml --account primary-gmail \
  --profile ultra_safe --dry-run
mboxer export notebooklm --config config/mboxer.yaml --account primary-gmail \
  --profile ultra_safe --out exports/notebooklm
mboxer export jsonl --config config/mboxer.yaml --account primary-gmail \
  --out exports/rag/messages.jsonl
```

Markdown and its manifests land beneath `exports/notebooklm/primary-gmail/`.
JSONL and its manifest land beneath `exports/rag/primary-gmail/`.

`--profile` selects NotebookLM packing limits. Content profiles instead come from
message classification or `security.default_export_profile`. Leaving
`--export-profile` unset preserves per-message policies. A run-wide override can
supersede `exclude`, so it changes which messages leave the database as well as
how their bodies are rendered.

By default, detected residual body patterns produce a warning and the export is
written. To block publication when any active detector still finds a body pattern,
add `--findings-policy block` to either export command. A blocked export exits `2`
and preserves prior published files; temporary staging may still have been used.

Scrubbing and the residual gate cover body text only. Inspect subjects, sender and
recipient fields, account/category names, and other metadata before sharing.
`metadata-only` omits bodies but does not anonymize headers. `reviewed` uses the
same scrubbing path as `scrubbed`; it is not proof of human review.

Successful NotebookLM re-export removes obsolete managed packs and keeps unrelated
files. Modified managed packs, filename collisions, or stale publication locks
can block replacement. Use a separate review copy if you want to edit generated
files. See [packing and recovery](docs/notebooklm-limits.md) before resolving an
ownership or interrupted-publication error.

## 7. Scale up

Once the small archive gives the expected output, ingest the larger MBOX under
the intended account and repeat classification, scanning, and export. Retain disk
space for the original archive, database, optional attachments, temporary export
staging, and the previous output generation during publication.

Export body processing uses disk staging; memory can still grow with the largest
individual message and with ingest/thread-classification bookkeeping. A dry run
checks packing, not total system capacity or NotebookLM's current service quotas.
[Performance measurements](docs/performance.md) explains synthetic benchmarking.
