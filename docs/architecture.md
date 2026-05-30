# mboxer Architecture

`mboxer` is a local-first MBOX archive processor.

## Pipeline

```text
MBOX files
  → ingest
  → normalize
  → SQLite metadata store
  → attachment extraction/tracking
  → deterministic rules
  → local LLM classification
  → taxonomy governance
  → security scan / scrubbing
  → export profiles
  → NotebookLM Markdown source packs
  → RAG JSONL
```

## Principles

1. Raw email stays local by default.
2. Ingest must be resumable.
3. Multiple MBOX files may be imported into the same database.
4. Attachments are first-class records, not opaque blobs.
5. Categories are filesystem paths.
6. The LLM may propose taxonomy changes, but stable categories should be governed.
7. Exported files should be useful even when folder hierarchy is flattened.
8. Security/scrubbing should be a pipeline stage, not an afterthought.
9. NotebookLM limits must be config-driven.
10. SQLite is local operational state and must not be shared with external systems.
11. Data should leave through explicit exports or safe projections.
12. Future API/import handoff destinations should be configured, not hard-coded.

## Major components

```text
src/mboxer/
  cli.py
  config.py
  limits.py
  naming.py
  db/
    schema.sql
    schema.py
  ingest.py
  attachments.py
  normalize.py
  taxonomy.py
  classify.py
  security/
    scan.py
    scrub.py
    policy.py
  exporters/
    notebooklm.py
    jsonl.py
    manifest.py
```

## Category directories

Category paths are stored with `/` separators:

```text
medical/hospital-billing
legal/law-firm-correspondence
postal/usps-informed-delivery
household/utilities/electric
family/recipient-family/correspondence
```

The NotebookLM exporter writes category paths as directories:

```text
exports/notebooklm/<category-path>/<date-band>/<source-pack>.md
```

The filename must contain enough context to remain meaningful outside the directory.

## SQLite as durable state

SQLite is not just a cache. It is the local archive index.

It stores:

- source MBOX files
- ingest runs and checkpoints
- message metadata
- normalized bodies
- attachment paths and extraction status
- thread hints
- category taxonomy
- classification outputs
- category proposals
- security findings
- export manifests

This lets the user ingest once, reclassify many times, tune export profiles, and regenerate NotebookLM packs without rereading huge MBOX files.

## External handoff boundaries

NotebookLM Markdown and JSONL are standalone outputs. File-based delivery exists today; external API/import delivery is only a future direction.

Future external API/import destinations should consume safe projections through explicit configured intake routes. Do not share the SQLite database directly with an external system, and do not hard-code a downstream service.

No raw email body text, attachment payloads, local paths, account emails, or security excerpts should be emitted by default. Optional raw custody handoff, if ever added, should be explicit opt-in, default off, and separate from safe projection/export paths.
