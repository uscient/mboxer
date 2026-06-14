# How to Use mboxer

`mboxer` converts raw Gmail MBOX exports into organized, structured Markdown source packs for
NotebookLM (plus JSONL for RAG). This is the friendly step-by-step walkthrough; see `README.md` for
the full reference and `docs/` for design detail.

Every command below passes `--config config/mboxer.yaml`. If you omit `--config`, `mboxer` falls
back to the bundled `config/mboxer.example.yaml`, so you can try the tool before writing your own
config.

## Phase 1: Preparation

### 1. Install mboxer

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
mboxer --help
```

### 2. Get your Gmail MBOX file

1. Go to Google Takeout and request an export of your Gmail data.
2. Download and extract the archive, then locate the `.mbox` file.

> **Test with a small MBOX before ingesting large archives.**
> Gmail exports can exceed several gigabytes. Slice a small `.mbox` and ingest that first, run an
> export `--dry-run` to verify the output shape, and review the generated files locally before
> uploading anything to a cloud service.

### 3. Configure mboxer

```bash
cp config/mboxer.example.yaml config/mboxer.yaml
```

Edit `config/mboxer.yaml` to set your limit profile, locked taxonomy, classification rules, and
security/redaction policy.

## Phase 2: The core pipeline

### 1. Initialize the database

Create (or migrate) the local SQLite index that holds all durable state.

```bash
mboxer init-db --config config/mboxer.yaml
```

### 2. Register your account

`mboxer` keeps accounts separate. Add one before ingesting.

```bash
mboxer account add primary-gmail \
  --display-name "Primary Gmail" \
  --email you@example.com \
  --config config/mboxer.yaml
```

Confirm it with `mboxer account list --config config/mboxer.yaml`.

### 3. Ingest the MBOX file

The path to the `.mbox` is a positional argument; the human-readable label is `--source-name`.

```bash
mboxer ingest data/mboxes/primary-gmail/sample.mbox \
  --config config/mboxer.yaml \
  --account primary-gmail \
  --source-name "Sample" \
  --extract-attachments \
  --resume
```

`--resume` makes ingest restartable from its last checkpoint. Add `--create-account` to create the
account key inline if you skipped step 2.

### 4. Classify with rules

Assign categories, sensitivities, and export profiles deterministically. Defaults to thread level
with inheritance down to messages.

```bash
mboxer classify --config config/mboxer.yaml --account primary-gmail --level thread
```

### 5. Review categories

The classifier can propose new categories. Review counts and pending proposals, then approve or
reject before they are used in exports.

```bash
mboxer review-categories --config config/mboxer.yaml --account primary-gmail
mboxer approve-category <proposal_id>
mboxer reject-category <proposal_id>
```

### 6. Run a security scan

Run the local regex sensitivity scan (email, phone, SSN-like, credit-card-like) and record findings.

```bash
mboxer security-scan --config config/mboxer.yaml --account primary-gmail
```

## Phase 3: Export

### 1. Dry-run export

Verify the output shape, category directories, and size splitting without writing the full output.
A dry run is free and fast.

```bash
mboxer export notebooklm \
  --config config/mboxer.yaml \
  --account primary-gmail \
  --profile ultra_safe \
  --dry-run
```

### 2. Real export

```bash
mboxer export notebooklm \
  --config config/mboxer.yaml \
  --account primary-gmail \
  --profile ultra_safe \
  --out exports/notebooklm
```

Output (and a `manifest.csv` + `manifest.json`) is written under `exports/notebooklm/<account-key>/`.

### 3. JSONL for RAG (optional)

```bash
mboxer export jsonl \
  --config config/mboxer.yaml \
  --account primary-gmail \
  --out exports/rag/messages.jsonl
```

The account key is inserted into the output path automatically, so this lands at
`exports/rag/primary-gmail/messages.jsonl` with a `messages.manifest.json` beside it.
