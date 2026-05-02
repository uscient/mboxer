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
A JSON manifest is written alongside each export run.

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
Account key is injected into the output path automatically to keep multi-account exports separated.

### CSV exports

CSV export is planned for spreadsheet review, filtering, auditing, and manual cleanup.

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
- NotebookLM Markdown export with category directories, year bands, and size-limit profiles
- export dry-run mode
- JSONL export
- JSON export manifests
- five NotebookLM limit profiles: `standard`, `plus`, `pro`, `ultra`, `ultra_safe`
- CLI with subcommands for all pipeline stages
- YAML config loading with deep key access and environment variable support
- `pyproject.toml` packaging with optional `pdf` and `dev` extras

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
Python requires:   >=3.11
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
  db/
    schema.sql        # full SQLite schema
    schema.py         # init_db helper
    migrations/       # future migration scripts
  exporters/
    notebooklm.py     # Markdown source pack exporter
    jsonl.py          # JSONL exporter
    manifest.py       # JSON manifest writer
  security/
    scan.py           # security scan runner
    scrub.py          # scrub hooks
    policy.py         # export policy helpers

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

## Export profiles

NotebookLM limit profiles are defined in `config/mboxer.example.yaml`.

| Profile | Max sources | Reserved | Target sources | Target words/source |
|---|---|---|---|---|
| `standard` | 50 | 10 | 40 | 300,000 |
| `plus` | 100 | 20 | 80 | 300,000 |
| `pro` | 300 | 50 | 250 | 300,000 |
| `ultra` | 600 | 75 | 525 | 300,000 |
| `ultra_safe` | 600 | 100 | 450 | 225,000 |

Use `ultra_safe` as the default for large NotebookLM-oriented workflows where you want to preserve headroom for manual sources, attachments, PDFs, and later additions.

Limit overrides can be passed directly on the CLI:

```bash
mboxer export notebooklm \
  --profile ultra_safe \
  --max-sources 400 \
  --target-words 200000
```

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

The config controls which redaction passes are applied before export:

```yaml
security:
  redact_phone_numbers: true
  redact_ssn_like_numbers: true
  redact_credit_card_like_numbers: true
  redact_email_addresses: false
  redact_physical_addresses: false
  scan_attachments: true
  quarantine_unsafe_attachments: true
```

Cloud-oriented exports should use reviewed, scrubbed, or metadata-only profiles.

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

Optional PDF support:

```bash
pip install -e ".[pdf]"
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

## Releases

Releases are automated via [Python Semantic Release](https://python-semantic-release.readthedocs.io/) and `.github/workflows/release.yml`.

### How releases work

On every push to `master` (i.e. every merged PR when branch protection is enforced), the workflow:

1. Inspects all commits since the last `v*` tag.
2. Determines the next semantic version (`MAJOR.MINOR.PATCH`) from commit message prefixes (conventional commits).
3. Updates the version in `pyproject.toml` and `src/mboxer/__init__.py`, commits those changes, and pushes a `v<version>` tag.
4. Publishes a GitHub Release with a generated changelog under that tag.

If no commits since the last tag contain a version-bearing prefix, no new release is created.

### Conventional commits

Version bumping is driven entirely by commit message prefixes. Maintainers **must** follow this convention:

| Prefix | Version bump | Example |
|---|---|---|
| `fix:` | patch (`0.0.x`) | `fix: handle empty MBOX file` |
| `feat:` | minor (`0.x.0`) | `feat: add JSONL exporter` |
| `feat!:` or `BREAKING CHANGE:` footer | major (`x.0.0`) | `feat!: rename CLI flag --out to --output` |
| `chore:`, `docs:`, `test:`, `refactor:`, `style:`, `ci:`, `perf:` | none | `chore: update dependencies` |

Commit messages that do not carry a version-bearing prefix are included in the changelog but do not trigger a release on their own.

### Maintainer expectations

- Use the conventional commit format for every commit that lands on `master`.
- Breaking changes must be called out with either a `!` suffix on the type (`feat!:`) or a `BREAKING CHANGE:` footer in the commit body.
- Commits with `chore:`, `docs:`, `ci:`, `test:`, and similar prefixes accumulate silently and are released together with the next `fix:` or `feat:` commit.
- Do not manually push `v*` tags; let the automation handle all tagging.

### Changelog

Python Semantic Release maintains `CHANGELOG.md` automatically. Do not edit this file by hand.

## License

MIT
