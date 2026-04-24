# Claude Code Prompt: Build `xormania/mboxer`

You are working in the `xormania/mboxer` repository.

Project identity:

```text
GitHub repo:      xormania/mboxer
Python package:   mboxer
CLI command:      mboxer
Default database: var/mboxer.sqlite
```

## Goal

Turn this scaffold into a working local-first MBOX archive processor for knowledge management, RAG, and NotebookLM source-pack exports.

The project must support:

- ingesting one or more `.mbox` files
- storing email metadata and normalized body text in SQLite
- tracking attachments in a normalized `attachments` table
- tracking ingest runs and checkpoints so interrupted imports can resume
- deterministic rules before LLM classification
- optional local LLM classification through Ollama
- LLM-managed category proposals with review/approval
- category paths as filesystem directories
- future security scan/scrubbing stages
- NotebookLM Markdown export with config-driven file/source limits
- JSONL export for RAG

## Important design constraints

1. Raw email stays local by default.
2. SQLite is durable project state, not a disposable cache.
3. Ingest must be resumable.
4. Multiple MBOX files may be imported into the same SQLite database.
5. Attachments are first-class database records.
6. Category paths are slash-delimited filesystem paths.
7. NotebookLM export limits are config-driven, not hardcoded.
8. The default cloud-oriented export profile should be `scrubbed`, not `raw`.
9. Keep the code boring, modular, and testable.
10. Do not introduce a web app yet.

## Current files to respect

- `config/mboxer.example.yaml`
- `docs/architecture.md`
- `docs/naming-conventions.md`
- `docs/notebooklm-limits.md`
- `docs/security-roadmap.md`
- `src/mboxer/config.py`
- `src/mboxer/limits.py`
- `src/mboxer/naming.py`
- `src/mboxer/db/schema.sql`
- `src/mboxer/cli.py`

Keep naming consistent with these files.

## Implementation order

### 1. Database initialization

Implement:

```bash
mboxer init-db --config config/mboxer.yaml
```

Behavior:

- create parent directory for SQLite DB
- execute `src/mboxer/db/schema.sql`
- be idempotent
- print the DB path

### 2. MBOX ingest

Implement:

```bash
mboxer ingest data/mboxes/archive.mbox \
  --config config/mboxer.yaml \
  --source-name "Main Archive" \
  --extract-attachments \
  --resume
```

Behavior:

- create or find `mbox_sources` row using canonical file path
- create `ingest_runs` row
- parse messages with Python stdlib `mailbox`
- store metadata in `messages`
- store normalized body text when enabled
- compute body hash
- extract attachments if enabled
- store one row per attachment in `attachments`
- update `ingest_runs.last_mbox_key` and counters regularly
- commit in batches using `ingest.batch_commit_size`
- log message-level errors in `ingest_errors`
- mark ingest run `completed` or `failed`

Minimum message fields:

- `source_id`
- `mbox_key`
- `message_id`
- `thread_key`
- `subject`
- `sender`
- `recipients_json`
- `cc_json`
- `date_header`
- `date_utc`
- `body_text`
- `body_hash`
- `body_chars`
- `attachment_count`
- `raw_headers_json`

Resume behavior:

- if `--resume`, find latest incomplete run for that source
- use `last_mbox_key` as a conservative checkpoint
- iterate from beginning until checkpoint key is found, then continue
- always skip duplicate messages already present unless `--force` is provided

### 3. Header/body normalization

Implement safe helpers in `normalize.py`:

- decode MIME headers with `email.header.decode_header`
- parse dates with `email.utils.parsedate_to_datetime`
- decode plain text body parts with content charset fallback
- optionally strip HTML to text only if needed; keep this minimal for v0
- produce stable `thread_key` from `References`, `In-Reply-To`, `Message-ID`, or normalized subject fallback

### 4. Attachment tracking

Implement `attachments.py`:

- sanitize attachment filenames
- store under `data/attachments/<source-slug>/<message-hash>/<safe-filename>`
- avoid overwrite by adding sequence suffix when needed
- compute sha256
- store original filename, safe filename, content type, size, sha256, path, status
- do not execute or inspect attachment contents beyond safe metadata for now

### 5. Config-driven NotebookLM limits

Use `config/mboxer.example.yaml` as source of truth.

Implement in `limits.py`:

- profile resolution
- CLI override precedence
- byte/MB conversion helpers
- effective source budget: `max_sources - reserved_sources`
- validation warnings/errors

CLI flags for `mboxer export notebooklm`:

```text
--profile
--max-sources
--reserved-sources
--target-sources
--target-words
--max-words
--target-mb
--max-mb
--allow-full-source-budget
--force
```

Validation:

- fail if max bytes > 200 MB unless `--force`
- warn if max words > 500,000
- warn if target sources > effective source budget
- never exceed effective source budget unless `--allow-full-source-budget`

### 6. Rules and classification

Implement deterministic rule matching from config first.

Then implement optional local LLM classification through Ollama.

Classifier output should be structured JSON:

```json
{
  "category_path": "medical/hospital-billing",
  "secondary_paths": ["finance/bills"],
  "specific_topic": "Hospital billing correspondence",
  "summary": "Short factual summary.",
  "people": [],
  "organizations": [],
  "sensitivity": "high",
  "notebooklm_priority": "include",
  "export_profile": "scrubbed",
  "confidence": 0.86,
  "needs_review": false,
  "proposed_category_path": null,
  "proposal_reason": null
}
```

The LLM may propose categories, but do not silently create many new categories. Store proposals in `category_proposals` with `pending` status.

### 7. Category review

Implement:

```bash
mboxer review-categories --config config/mboxer.yaml
mboxer approve-category <proposal-id> --config config/mboxer.yaml
mboxer reject-category <proposal-id> --config config/mboxer.yaml
```

Review should show:

- category counts
- pending proposals
- suggested high-volume categories
- low-confidence classifications

### 8. Security scan placeholder

Implement a basic `security-scan` command.

For v0, detect and store findings for:

- phone-number-like values
- SSN-like values
- credit-card-like values
- credential/password hints
- sensitive category markers for medical/legal/financial content

Store findings in `security_findings`.

Do not overpromise perfect redaction.

### 9. NotebookLM Markdown export

Implement:

```bash
mboxer export notebooklm \
  --config config/mboxer.yaml \
  --profile ultra_safe \
  --out exports/notebooklm
```

Behavior:

- use category directories
- split by category and date band/year
- preserve thread integrity when possible
- obey profile limits
- close files at target limits when practical
- never exceed hard limits
- write source headers containing category, date range, profile, counts, and scrub status
- include message metadata
- include attachment references, not attachment contents
- write `manifest.csv`
- record export run in `exports` and `export_items`

Markdown source format:

```markdown
# Medical / Hospital Billing — 2024 — Part 001

Source Pack Metadata:
- Category: medical/hospital-billing
- Date Range: 2024-01-01 to 2024-12-31
- Export Profile: scrubbed
- Message Count: 123
- Attachment Count: 12

---

## Email: Subject here

- Date: ...
- From: ...
- To: ...
- Message-ID: ...
- Attachments: ...

Body text...
```

### 10. JSONL export

Implement:

```bash
mboxer export jsonl --config config/mboxer.yaml --out exports/rag/messages.jsonl
```

Each line should include:

- message id
- source info
- metadata
- clean body
- classification
- attachment metadata
- security flags

## Tests

Add lightweight tests for:

- slug generation
- category path normalization
- config loading
- NotebookLM profile resolution
- override precedence
- source-budget calculation
- DB initialization idempotency

Do not require a huge sample MBOX for tests.

## Style

Use stdlib where practical.

Avoid heavy dependencies unless clearly needed.

Keep modules small:

```text
src/mboxer/
  cli.py
  config.py
  limits.py
  naming.py
  db/schema.py
  ingest.py
  normalize.py
  attachments.py
  taxonomy.py
  classify.py
  security/scan.py
  security/scrub.py
  exporters/notebooklm.py
  exporters/jsonl.py
  exporters/manifest.py
```

## Acceptance criteria

After implementation, these should work:

```bash
pip install -e .
mboxer --help
mboxer init-db --config config/mboxer.example.yaml
mboxer export notebooklm --config config/mboxer.example.yaml --dry-run
pytest
```

A real ingest should work with:

```bash
mboxer ingest data/mboxes/archive.mbox --config config/mboxer.yaml --resume --extract-attachments
```
