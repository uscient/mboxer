# mboxer

Create **NotebookLM-ready Markdown source packs** from **Gmail MBOX exports**, with local SQLite, JSONL, and CSV outputs for search, RAG, archive review, and LLM workflows.

`mboxer` is a local-first email archive processor designed around a common problem:

```text
You can export Gmail as an MBOX file,
but a raw MBOX archive is not useful for NotebookLM, RAG, review, or analysis.
```

`mboxer` turns that raw archive into organized, structured, reusable knowledge assets.

```text
Gmail / Google Takeout
  → MBOX file
  → local SQLite index
  → organized Markdown source packs
  → NotebookLM, RAG, search, review, JSONL, and future tools
```

## Why this exists

Gmail archives often contain years of valuable personal, professional, legal, financial, operational, project, and organizational history.

Google Takeout makes it possible to export that history as an `.mbox` file, but the exported file is not immediately useful for modern AI workflows.

NotebookLM works best with readable, focused, well-organized source documents.

RAG systems work best with structured, chunkable records.

Spreadsheets work best with clean rows and metadata.

Local review works best when everything is inspectable before anything is uploaded.

`mboxer` bridges that gap.

## Primary use case: Gmail MBOX to NotebookLM

The main selling point of `mboxer` is converting Gmail MBOX exports into clean, category-organized Markdown files that can be used as NotebookLM sources.

Instead of uploading one giant raw archive, `mboxer` creates structured source packs like:

```text
exports/notebooklm/
  primary-gmail/                 # output is nested under the account key
    finance/
      invoices/
        2024/
          finance-invoices-2024-001.md
    legal/
      contracts/
        2023-2024/
          legal-contracts-2023-2024-001.md
    projects/
      product-launch/
        2026/
          projects-product-launch-2026-001.md
    operations/
      vendor-correspondence/
        2025/
          operations-vendor-correspondence-2025-001.md
```

The goal is to make exported Gmail content easier to:

- upload into NotebookLM
- organize by topic or category
- review before upload
- split into useful source packs
- preserve context from email threads
- exclude sensitive or irrelevant material
- reuse later for RAG, search, or analysis

## What `mboxer` produces

### NotebookLM Markdown source packs

Markdown is the primary output format.

Each exported file preserves useful email context:

- subject
- sender and recipients
- date
- thread hints
- category
- source account
- cleaned body text
- attachment references

Export output is split by category, year, and size band to respect NotebookLM source limits.
A CSV manifest (`manifest.csv`) and JSON manifest (`manifest.json`) are written under
`<out>/<account-key>/` for each export run.

### SQLite database

SQLite is the durable local project index.

The schema tracks:

- accounts and MBOX sources
- messages with normalized metadata and body text
- Gmail label associations
- thread groupings with participant and date ranges
- ingest runs with resumable checkpoint keys
- ingest errors per run
- attachments with SHA-256, content type, and extraction status
- classifications per message and per thread
- category taxonomy with locked/global flags
- category proposals for review and approval
- export items and export run records
- security findings per message

### JSONL exports

JSONL is intended for RAG pipelines, embeddings, local LLM tools, and structured downstream processing.

Each line represents one message with clean body text, metadata, and classification context.
Account key is injected into the output path automatically to keep multi-account exports separated,
and a `<name>.manifest.json` is written alongside the JSONL file.

### External API/import handoff

No external API delivery is implemented today. Future configurable API exports should use explicit safe projections and configured intake routes, not direct SQLite sharing or hard-coded downstream services.

NotebookLM Markdown and JSONL remain standalone outputs. Optional raw custody handoff, if ever added, should be explicit opt-in, default off, and separate from safer export paths.

### CSV exports

A row-per-message CSV export (for spreadsheet review, filtering, auditing, and manual cleanup) is
planned and not yet implemented. Note that export **manifests** are already written as CSV today
(`manifest.csv`); the planned feature is a separate CSV export of message data itself.

## Current implementation status

The core pipeline is implemented and working.

Implemented:

- MBOX ingest into SQLite using Python's `mailbox` stdlib
- resumable ingest with per-run checkpoint keys and batch commits
- deduplication via `INSERT OR IGNORE` on message identity
- multi-account separation with per-account keyed storage
- message normalization: subject, sender, recipients, dates, body text, body hash, word count
- Gmail label parsing and storage
- thread grouping with participant aggregation and date ranges
- attachment extraction to disk with SHA-256 and content-type tracking
- rule-based classification at both message and thread level
- thread-level rule classification with message inheritance
- `assign` (confidence 1.0) and `assign_hint` (confidence 0.75) rule actions
- category taxonomy with locked categories and proposal workflow
- category review, approval, and rejection via CLI
- security scan and scrub hooks
- five export content profiles: `raw`, `reviewed`, `scrubbed`, `metadata-only`, `exclude`
- residual-findings export gate (`allow` / `warn` / `block`) that re-scans projected export text
- NotebookLM Markdown export with category directories, year bands, and size-limit profiles
- export dry-run mode
- JSONL export
- CSV + JSON export manifests with provenance/lineage fields
- five NotebookLM limit profiles: `standard`, `plus`, `pro`, `ultra`, `ultra_safe`
- CLI with subcommands for all pipeline stages
- YAML config loading with deep (dotted) key access
- `pyproject.toml` packaging with an optional `dev` extra; version derived from git tags via setuptools-scm

In progress / planned:

- CSV export
- LLM-based classification via Ollama (config shape is present, wiring is not complete)
- local web UI for category review
- incremental export tracking
- scrub profiles for PII redaction before cloud upload

## Project identity

```text
Project name:      mboxer
Python package:    mboxer
CLI command:       mboxer
Default database:  var/mboxer.sqlite
Entry point:       mboxer.cli:main
Module entry:      python -m mboxer
Python requires:   >=3.11 (tested on 3.11 and 3.12)
Versioning:        git tags via setuptools-scm
```

## Source layout

```text
src/mboxer/
  cli.py              # argparse CLI: all subcommands
  config.py           # YAML config loading, path helpers
  ingest.py           # MBOX ingest pipeline
  normalize.py        # message normalization and body extraction
  classify.py         # rule-based classification (message + thread)
  taxonomy.py         # category management and proposal workflow
  accounts.py         # account CRUD and resolution
  attachments.py      # attachment extraction and storage
  limits.py           # NotebookLM limit profiles and validation
  naming.py           # slugify and category path normalization
  records.py          # row/address decoding helpers
  db/
    schema.sql        # reference schema snapshot (validated in CI)
    schema.py         # init_db: applies versioned migrations
    migrations/       # versioned schema migrations (the DB is built from these)
  exporters/
    notebooklm.py     # Markdown source pack exporter
    jsonl.py          # JSONL exporter
    projection.py     # applies export content profile to each record
    manifest.py       # CSV + JSON manifest writer
  security/
    scan.py           # security scan runner
    scrub.py          # scrub hooks
    detectors.py      # regex detector registry
    findings.py       # residual-findings export gate
    policy.py         # export profile / findings policy helpers

config/
  mboxer.example.yaml   # full annotated config example

tests/
  test_accounts.py
  test_classify.py
  test_config.py
  test_db.py
  test_export.py
  test_first_run.py
  test_ingest.py
  test_limits.py
  test_manifest.py
  test_migration.py
  test_naming.py
  test_normalize.py
  test_scrub_export.py
  test_taxonomy.py
  test_thread_classify.py
```

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate

pip install -e .

mboxer --help
```

Copy and customize the example config:

```bash
cp config/mboxer.example.yaml config/mboxer.yaml
```

> Tip: if you omit `--config`, `mboxer` falls back to the bundled `config/mboxer.example.yaml`, so
> the commands below run out of the box for a first look. Copy it to `config/mboxer.yaml` and edit
> that copy for real use.

## First run

Complete walkthrough from a fresh checkout to a dry-run export.

**1. Initialize the database**

```bash
mboxer init-db --config config/mboxer.yaml
```

**2. Register your account**

```bash
mboxer account add primary-gmail \
  --display-name "Primary Gmail" \
  --email user@example.com \
  --config config/mboxer.yaml
```

**3. Verify the account was registered**

```bash
mboxer account list --config config/mboxer.yaml
```

**4. Ingest a small test archive first** (see warning below)

```bash
mboxer ingest data/mboxes/primary-gmail/sample.mbox \
  --config config/mboxer.yaml \
  --account primary-gmail \
  --source-name "Sample" \
  --extract-attachments \
  --resume
```

**5. Classify with rules**

```bash
mboxer classify \
  --config config/mboxer.yaml \
  --account primary-gmail
```

**6. Review categories**

```bash
mboxer review-categories \
  --config config/mboxer.yaml \
  --account primary-gmail
```

**7. Run a security scan**

```bash
mboxer security-scan \
  --config config/mboxer.yaml \
  --account primary-gmail
```

**8. Dry-run export to verify output shape**

```bash
mboxer export notebooklm \
  --config config/mboxer.yaml \
  --account primary-gmail \
  --profile ultra_safe \
  --dry-run
```

**9. Real export when ready**

```bash
mboxer export notebooklm \
  --config config/mboxer.yaml \
  --account primary-gmail \
  --profile ultra_safe \
  --out exports/notebooklm
```

> **Warning: test with a small MBOX before ingesting large archives.**
>
> Gmail MBOX exports can exceed several gigabytes for long-lived accounts.
> Before ingesting a full archive:
>
> 1. Extract a small slice of messages into a separate `.mbox` file and ingest that first.
> 2. Run `mboxer export notebooklm --dry-run` to verify the output shape.
> 3. Review the generated exports locally before uploading anything to a cloud service.
>
> `--resume` makes ingest restartable, but a full ingest of a large archive still takes
> significant time and disk space. Running `--dry-run` on exports is free and fast.

## Getting a Gmail MBOX file

You can export Gmail data from Google Takeout / Google Data Request.

The typical flow is:

1. Request an export of your Gmail data.
2. Download the archive from Google.
3. Extract the downloaded archive locally.
4. Locate the `.mbox` file.
5. Ingest the `.mbox` file with `mboxer`.
6. Export organized Markdown files for NotebookLM.

Example:

```bash
mboxer ingest data/mboxes/archive.mbox \
  --config config/mboxer.yaml \
  --source-name "Primary Gmail Archive" \
  --account primary-gmail \
  --extract-attachments \
  --resume
```

## Intended workflow

```bash
mboxer ingest data/mboxes/archive.mbox \
  --config config/mboxer.yaml \
  --source-name "Primary Gmail Archive" \
  --account primary-gmail \
  --extract-attachments \
  --resume

mboxer classify \
  --config config/mboxer.yaml \
  --account primary-gmail \
  --level thread

mboxer review-categories \
  --config config/mboxer.yaml \
  --account primary-gmail

mboxer security-scan \
  --config config/mboxer.yaml \
  --account primary-gmail

mboxer export notebooklm \
  --config config/mboxer.yaml \
  --account primary-gmail \
  --profile ultra_safe \
  --out exports/notebooklm

mboxer export jsonl \
  --config config/mboxer.yaml \
  --account primary-gmail \
  --out exports/rag/messages.jsonl
```

## Configuration and global flags

Every command accepts two global flags:

- `--config PATH` — path to your YAML config. If omitted, `mboxer` falls back to the bundled
  `config/mboxer.example.yaml`.
- `--db PATH` — override the SQLite database path. Otherwise the path comes from `paths.database`
  (then `project.default_database`) in config, defaulting to `var/mboxer.sqlite`.

The annotated `config/mboxer.example.yaml` is the reference for every available key: ingest batch
size, classification rules, locked taxonomy, security/redaction policy, NotebookLM limit profiles,
and JSONL options. Config values are read with dotted-path access; there is currently no
environment-variable support.

### Account commands

```bash
mboxer account add <key> --display-name "..." --email you@example.com [--provider gmail] [--notes "..."]
mboxer account list
mboxer account show <key>
mboxer account update <key> [--display-name "..."] [--email ...] [--notes "..."]
```

When exactly one account exists it is auto-selected (with a notice). When more than one exists,
account-scoped commands require `--account <key>` (or `--accounts key1,key2` for a combined
NotebookLM export).

### Useful ingest flags

- `--resume` — restart an interrupted ingest from its last checkpoint.
- `--extract-attachments` — extract attachments to `data/attachments/` with SHA-256 + content type.
- `--create-account` — create the `--account` key on the fly if it does not exist yet.
- `--force` — reprocess messages even if already present.

## Multi-account support

`mboxer` supports multiple separate Gmail accounts and archives in the same local project.

Each ingested source is tracked by account, source name, import run, and original MBOX file.

Example account keys:

```text
primary-account
work-account
business-archive
organization-archive
project-archive
```

To export multiple accounts into a single NotebookLM run:

```bash
mboxer export notebooklm \
  --config config/mboxer.yaml \
  --accounts primary-account,work-account \
  --profile ultra_safe \
  --out exports/notebooklm
```

## NotebookLM source-pack strategy

NotebookLM exports are Markdown-first and organized by category directories.

Filenames remain meaningful even if the folder hierarchy is flattened during upload.

```text
category-topic-year-sequence.md
```

Examples:

```text
finance-invoices-2024-001.md
legal-contracts-2023-2024-001.md
projects-product-launch-2026-001.md
operations-vendor-correspondence-2025-001.md
research-literature-review-2024-001.md
support-customer-requests-2025-001.md
```

## Profiles: two independent controls

`mboxer` has **two** different "profile" settings on `export notebooklm`, and they do different
things:

| CLI flag | What it controls | Allowed values |
|---|---|---|
| `--profile` | NotebookLM **size limits** (how many source files, how big) | `standard`, `plus`, `pro`, `ultra`, `ultra_safe` |
| `--export-profile` | **Content** posture (how much of each message is exported) | `raw`, `reviewed`, `scrubbed`, `metadata-only` |

They are covered separately below.

## NotebookLM limit profiles (`--profile`)

Limit profiles bound how many source files an export produces and how large each one gets.
They are defined in `config/mboxer.example.yaml`.

| Profile | Max sources | Reserved | Target sources | Target words/source |
|---|---|---|---|---|
| `standard` | 50 | 10 | 40 | 300,000 |
| `plus` | 100 | 20 | 80 | 300,000 |
| `pro` | 300 | 50 | 250 | 300,000 |
| `ultra` | 600 | 75 | 525 | 300,000 |
| `ultra_safe` | 600 | 100 | 450 | 225,000 |

Use `ultra_safe` as the default for large NotebookLM-oriented workflows where you want to preserve headroom for manual sources, attachments, PDFs, and later additions.

Any field of the selected limit profile can be overridden on the CLI:

```bash
mboxer export notebooklm \
  --profile ultra_safe \
  --max-sources 400 \
  --target-words 200000
```

Full set of limit overrides: `--max-sources`, `--reserved-sources`, `--target-sources`,
`--target-words`, `--max-words`, `--target-mb`, `--max-mb`. Two escape hatches relax the
built-in guardrails:

- `--allow-full-source-budget` — allow the export to use the full `max_sources` budget
  (ignore `reserved_sources` headroom).
- `--force` — override the 200 MB per-source safety ceiling.

## Export content profiles (`--export-profile`)

Content profiles decide how much of each message body actually leaves the database. Every message
gets an effective profile from its classification rule (`export_profile:` in a rule) or, failing
that, from `security.default_export_profile` (the example config uses `scrubbed`).

| Profile | Effect on the exported body |
|---|---|
| `raw` | Full body text, unchanged. Local use only. |
| `reviewed` | Treated like `scrubbed` today: redaction passes are applied. |
| `scrubbed` | Sensitive patterns redacted per `security.redact_*` policy. |
| `metadata-only` | Body text dropped; only headers/metadata are exported. |
| `exclude` | Message is omitted from the export entirely. |

`--export-profile` overrides the effective profile for a whole run, but only accepts
`raw`, `reviewed`, `scrubbed`, or `metadata-only`. `exclude` is **not** a CLI choice — it is applied
per message through classification rules or config, so that "do not export" stays a governed,
per-category decision rather than a global switch.

### Residual-findings gate (`--findings-policy`)

After a record is projected for export, the projected text is scanned again. `--findings-policy`
(default from `security.on_residual_findings`, which the example config sets to `warn`) controls what
happens if detected-sensitive patterns survive:

- `allow` — write the export; record residual counts in the manifest.
- `warn` — write the export, record counts, and print a counts-only warning.
- `block` — abort **before any files are written**; the command exits with status `2`.

## Classification strategy

Classification runs in two passes.

**Rule-based** (deterministic, no network required):

Rules match on sender domain, sender address fragment, and subject keywords.
Each rule assigns a `category_path`, `sensitivity`, `notebooklm_priority`, and `export_profile`.

At thread level, a matching rule is applied to the whole thread and then inherited down to all messages in the thread.

Rules support two assignment modes:

- `assign` — confident match, confidence 1.0
- `assign_hint` — soft match, confidence 0.75

**LLM-based** (optional, local-first):

Config accepts an Ollama endpoint and model name.
LLM classification is wired in the config shape and CLI but is not yet fully connected to the pipeline.

Classification can be scoped by account and run at `message` or `thread` level:

```bash
mboxer classify --level thread --account primary-gmail
```

## Category taxonomy

Categories are slash-delimited paths that become directory hierarchies in exports.

```text
medical
medical/hospital-billing
medical/pharmacy
legal
legal/law-firm-correspondence
finance
household/utilities
postal/usps-informed-delivery
noise/marketing
noise/spam
```

Locked categories are defined in config and cannot be deleted.

The classifier can propose new categories. Proposals appear in `review-categories` and require explicit approval before being used in exports:

```bash
mboxer approve-category <proposal_id>
mboxer reject-category <proposal_id>
```

## Security stance

`mboxer` assumes mail archives contain sensitive material.

Raw exports are local-only by default.

The security pipeline:

```text
ingest
  → normalize
  → classify
  → security-scan
  → scrub
  → review
  → export
```

The `security` config block controls the default content posture, the residual-findings gate, and
which redaction passes run before export:

```yaml
security:
  default_export_profile: scrubbed       # fallback content profile when no rule sets one
  scan_enabled: true
  scrub_enabled: true
  on_residual_findings: warn             # allow | warn | block (maps to --findings-policy)
  scan_attachments: true
  quarantine_unsafe_attachments: true
  redact_email_addresses: true
  redact_phone_numbers: true
  redact_ssn_like_numbers: true
  redact_credit_card_like_numbers: true
  # physical_addresses is a reserved/planned detector name, not active today
```

Detection today is a deterministic in-process **regex** registry covering email addresses, phone
numbers, SSN-like values, and credit-card-like values. Physical-address, medical, legal, and
credential detectors are reserved future names, not active detection or scrubbing.

Cloud-oriented exports should use `reviewed`, `scrubbed`, or `metadata-only` content profiles.

## Development

```bash
pip install -e ".[dev]"

pytest
```

Linting and type checking:

```bash
ruff check src/
mypy src/
```

CI (`.github/workflows/ci.yml`) runs ruff and mypy on Python 3.11 and the test suite on Python 3.11
and 3.12. Test fixtures are synthetic; regenerate them with:

```bash
python tests/fixtures/make_synthetic.py
```

## Design goals

`mboxer` should be:

- NotebookLM-friendly
- Gmail MBOX-focused
- local-first
- privacy-conscious
- resumable
- inspectable
- useful without a cloud service
- useful with local LLMs
- useful with future RAG systems
- safe for sensitive archives
- flexible enough for multiple Gmail accounts
- structured enough to support future application features

## Non-goals

`mboxer` is not intended to be:

- a Gmail client
- a replacement for Gmail search
- a hosted SaaS product
- a tool that uploads raw email archives by default
- a black-box AI classifier
- a cloud-first archive processor

## Troubleshooting / FAQ

**`Config file not found: config/mboxer.yaml`**
You passed `--config config/mboxer.yaml` but never created it. Copy the example
(`cp config/mboxer.example.yaml config/mboxer.yaml`) or drop `--config` to use the bundled example.

**`<command> requires --account when multiple accounts exist`**
More than one account is registered. Pass `--account <key>`; list keys with `mboxer account list`.

**`Unknown NotebookLM profile 'x'. Available: ...`**
`--profile` must be one of `standard`, `plus`, `pro`, `ultra`, `ultra_safe` (or a profile you added
under `exports.notebooklm.profiles`).

**`effective source budget is zero; reduce reserved_sources`**
`reserved_sources` is greater than or equal to `max_sources` for the chosen profile. Lower it, or
pass `--allow-full-source-budget`.

**`max_bytes_per_source exceeds 200 MB safety limit; pass --force to override`**
A per-source byte limit above 200 MB is rejected by default. Pass `--force` only if you really intend
sources that large.

**`BLOCKED: would export residual detected-sensitive items ...` (exit code 2)**
Your findings policy is `block` and the projected export text still contains detected-sensitive
patterns. Scrub/redact further, move the affected categories to `metadata-only`/`exclude`, or rerun
with `--findings-policy warn` (or `allow`) if that is acceptable for the run.

**`mboxer: command not found`**
Activate the virtualenv and install the package: `source .venv/bin/activate && pip install -e .`.

**Ingesting a full archive is slow or huge.**
Expected — Gmail archives can be many GB. Slice a small `.mbox` first, use `--resume`, and validate
shape with `mboxer export notebooklm --dry-run` before a real export.

**Does classification use an LLM?**
Not yet. Classification is deterministic rule matching today. The Ollama config block and the
`classify --model` flag exist, but LLM classification is not wired into the pipeline (the flag prints
a "not yet implemented" notice).

## Releases

The package version is derived from git tags by `setuptools-scm` — there is no hand-edited version
string in `pyproject.toml`. The most recent `vX.Y.Z` tag determines the version of a build.

Publishing is **manual and tag/release-driven**:

1. Push a semantic-version tag, e.g. `git tag v0.2.0 && git push origin v0.2.0`.
2. Create a GitHub Release for that tag.
3. Publishing the GitHub Release triggers `.github/workflows/publish.yml`, which builds the sdist
   and wheel (`python -m build`) and uploads them to PyPI using trusted publishing (OIDC, the `pypi`
   environment) — no API token is stored in the repo.

There is no automatic patch-bump-on-merge workflow; choosing the next version number is a deliberate
step you take when you tag a release.

## License

Apache License 2.0. See [LICENSE](LICENSE).
