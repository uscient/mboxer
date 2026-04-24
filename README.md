# mboxer

`mboxer` is a local-first MBOX archive processor for knowledge management, RAG pipelines, and NotebookLM source-pack exports.

It is designed for large personal or organizational mail archives where you need to:

- ingest one or more `.mbox` files into a durable local SQLite index
- track email metadata, bodies, thread hints, and attachments
- classify messages or threads with deterministic rules and optional local LLMs
- let the system propose and manage a category taxonomy
- leave room for security scanning and scrubbing before cloud upload
- export filesystem-organized Markdown source packs for NotebookLM
- export JSONL for RAG systems

## Project identity

```text
GitHub repo:      xormania/mboxer
Python package:   mboxer
CLI command:      mboxer
Default database: var/mboxer.sqlite
```

## Current project status

This repository is a scaffold plus design baseline. It includes:

- config-driven NotebookLM export limits
- category-directory export conventions
- SQLite schema plan
- attachment tracking model
- ingest-run checkpoint model
- security/scrubbing roadmap
- CLI shape and config loading utilities
- a Claude Code implementation prompt

The next implementation pass should wire ingest, classification, security scanning, and exporters to the SQLite schema.

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

## Intended workflow

```bash
mboxer ingest data/mboxes/archive.mbox \
  --config config/mboxer.yaml \
  --source-name "Main Archive" \
  --extract-attachments \
  --resume

mboxer classify \
  --config config/mboxer.yaml \
  --model llama3.1:8b \
  --level thread

mboxer review-categories \
  --config config/mboxer.yaml

mboxer security-scan \
  --config config/mboxer.yaml

mboxer export notebooklm \
  --config config/mboxer.yaml \
  --profile ultra_safe \
  --out exports/notebooklm

mboxer export jsonl \
  --config config/mboxer.yaml \
  --out exports/rag/messages.jsonl
```

## NotebookLM source-pack strategy

NotebookLM exports should be Markdown-first and organized by category directories:

```text
exports/notebooklm/
  medical/
    hospital-billing/
      2024/
        medical-hospital-billing-2024-001.md
  legal/
    law-firm-correspondence/
      2023-2024/
        legal-law-firm-correspondence-2023-2024-001.md
  postal/
    usps-informed-delivery/
      2024/
        postal-usps-informed-delivery-2024-001.md
```

Filenames must remain meaningful even if folder hierarchy is flattened during upload.

## Export profiles

NotebookLM export limits live in `config/mboxer.example.yaml`:

- `standard`
- `plus`
- `pro`
- `ultra`
- `ultra_safe`

Use `ultra_safe` as the default for Google AI Ultra workflows: it preserves headroom for manual sources, attachments, PDFs, and later additions.

## Security stance

`mboxer` should assume mail archives contain sensitive material. Raw export should be local-only. Cloud-oriented exports should use `reviewed`, `scrubbed`, or `metadata-only` profiles.

Planned security pipeline:

```text
ingest
  → normalize
  → classify
  → security-scan
  → scrub
  → review
  → export
```
