# How to Use mboxer

`mboxer` converts raw Gmail MBOX exports into organized, structured Markdown files optimized for NotebookLM. This guide walks you through the complete end-to-end workflow.

## Phase 1: Preparation

### 1. Get Your Gmail MBOX File

1. Go to Google Takeout and request an export of your Gmail data.

2. Download and extract the generated archive to locate the `.mbox` file.

**Warning: Test with a small MBOX before ingesting large archives.**
Gmail MBOX exports can exceed several gigabytes for long-lived accounts. Before ingesting a full archive:

1. Extract a small slice of messages into a separate `.mbox` file and ingest that first.

2. Run `mboxer export notebooklm --dry-run` to verify the output shape.

3. Review the generated exports locally before uploading anything to a cloud service.

### 2. Configure mboxer

Copy the example configuration file:

    cp config/mboxer.example.yaml config/mboxer.yaml

Customize `config/mboxer.yaml` to define your limits, categories, and classification rules.

## Phase 2: The Core Pipeline

Complete walkthrough from a fresh checkout to export:

### 1. Initialize the Database

Set up the local SQLite database that acts as the durable project index.

    mboxer init

### 2. Register Your Account

`mboxer` supports multi-account separation. Register your account key first.

    mboxer register --account your_account_key

### 3. Ingest the MBOX File

Load your `.mbox` file into the local database.

    mboxer ingest --account your_account_key --source your_mbox_file.mbox --resume

*Note: The `--resume` flag makes the ingest restartable using per-run checkpoint keys, but a full ingest still takes significant time and disk space.*

### 4. Classify with Rules

Run the classification engine. This assigns categories, sensitivities, and export profiles at both the message and thread levels.

    mboxer classify

### 5. Review Categories

The classifier can propose new categories. You must explicitly review, approve, or reject these proposals before they are used in exports.

    mboxer review-categories

### 6. Run a Security Scan

Apply redaction passes and security scan hooks.

    mboxer scan

## Phase 3: Export

### 1. Dry-Run Export

Verify the output shape, category directories, and size limits without writing massive amounts of data. Running `--dry-run` on exports is free and fast.

    mboxer export notebooklm --dry-run

### 2. Real Export

Generate the Markdown source packs for NotebookLM, or JSONL for RAG pipelines.

    mboxer export notebooklm
