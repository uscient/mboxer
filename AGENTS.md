# AGENTS.md

## Repository identity

This repository is `uscient/mboxer`: a local-first Python CLI for turning Gmail/Takeout `.mbox` archives into structured SQLite evidence and export packs for NotebookLM, RAG, and review workflows.

Core flow:

```text
Gmail MBOX
  -> ingest emails
  -> normalize message metadata/body
  -> store in SQLite
  -> optionally extract attachments
  -> classify by governed rules
  -> scan/scrub sensitive text
  -> export Markdown packs or JSONL
```

The main command is `mboxer`, wired through `mboxer.cli:main`. The module entrypoint is also available with `python -m mboxer`.

## Non-negotiable working agreements

- Inspect before editing. Summarize the relevant files and current behavior before making changes.
- Keep changes PR-sized and source-only. Do not generate local runtime data, real exports, real archives, databases, attachments, caches, or large artifacts inside the repo unless the user explicitly asks.
- Do not ingest, inspect, print, summarize, or expose real email archive contents unless explicitly instructed for that task.
- Never include raw private email body text, secrets, account identifiers, attachment contents, or sensitive findings in final reports. Use counts, paths, and sanitized examples.
- Preserve local-first behavior. Do not add cloud, SaaS, telemetry, background sync, external network calls, or hosted service assumptions without explicit approval.
- Do not add production dependencies without calling them out first and explaining why the standard library or current dependencies are insufficient.
- Do not broaden `mboxer` into uScientDB, a general knowledge manager, an agent platform, or a UI. `mboxer` is the focused email archive processor and future evidence producer.
- For future uScientDB readiness work, add neutral seams only. Do not invent the final uScientDB API, wire network delivery, or hard-code uScientDB-specific behavior unless explicitly requested.
- Preserve deterministic behavior wherever possible. LLM/Ollama classification is future-facing unless the task explicitly says to implement it.
- Prefer additive changes and tests over rewrites.

## Instruction-surface handling

Treat these as governance/instruction-surface files, not ordinary edits:

- `AGENTS.md`
- `CLAUDE.md`
- `.codex/`
- `.claude/`
- `.agents/`
- `CLAUDE.local.md`
- hooks, skills, rules, prompts, MCP config, agent config, or similar files

When any of these are created, deleted, or modified:

1. Report the exact files changed.
2. Explain whether the change affects the current agent session or only future sessions.
3. Recommend a fresh Codex/Claude session when the tool may not reload instructions automatically.
4. Do not assume newly edited instructions govern the current session unless the tool explicitly confirms reload.

## Architecture map

Primary areas to inspect before changing behavior:

- CLI: `src/mboxer/cli.py`, `src/mboxer/__main__.py`
- Config: `src/mboxer/config.py`, `config/mboxer.example.yaml`
- SQLite schema/migrations: `src/mboxer/db/schema.sql`, `src/mboxer/db/schema.py`, `src/mboxer/db/migrations/`
- Accounts: `src/mboxer/accounts.py`
- Ingest: `src/mboxer/ingest.py`
- Normalization: `src/mboxer/normalize.py`
- Attachments: `src/mboxer/attachments.py`
- Classification: `src/mboxer/classify.py`
- Taxonomy: `src/mboxer/taxonomy.py`
- Security scan/scrub/policy: `src/mboxer/security/`
- Exporters: `src/mboxer/exporters/`
- Naming: `src/mboxer/naming.py`
- Limits: `src/mboxer/limits.py`
- Tests: `tests/`

## Core invariants

### Local custody

- SQLite is the durable local state center.
- MBOX input, normalized message rows, classifications, security findings, export records, and manifests are evidence surfaces.
- Re-ingest and resume behavior must remain conservative and explainable.
- Schema migrations must be tested and must not silently corrupt or discard existing evidence.

### Accounts

- Preserve account isolation.
- If one account exists, current auto-selection behavior may apply.
- If multiple accounts exist, commands should require explicit account selection unless the command intentionally supports multi-account behavior.
- Do not collapse account identity into export paths, manifests, or event-like records in a way that loses provenance.

### Ingest and normalization

- Keep normalization deterministic and testable.
- Preserve message IDs, references, thread keys, dates, body hashes, labels, and attachment metadata as provenance-bearing fields.
- Be careful with date parsing, encoded headers, HTML-to-text fallback, Gmail labels, duplicate messages, and malformed messages.
- Attachment extraction must sanitize filenames and preserve hashes/metadata.

### Classification and taxonomy

- Current classification is deterministic rule-based config behavior.
- Thread-level classification and inheritance are important and must not regress.
- Category paths are governed taxonomy paths. Do not silently approve proposed categories.
- Category proposals are future suggestion candidates; they are not automatically trusted categories.

### Security and export boundaries

- Security scanning is currently regex-based. Do not overstate it as full DLP, attachment forensics, malware scanning, or semantic PII detection.
- Export profiles must remain clear:
  - `raw`
  - `reviewed`
  - `scrubbed`
  - `metadata-only`
  - `exclude`
- Cloud-style/NotebookLM exports should default toward safer scrubbed behavior when config says so.
- Manifests should not contain raw sensitive body text.
- Tests should cover policy/profile behavior when security or export behavior changes.

### Export and lineage

- NotebookLM Markdown exports and JSONL exports are transformations of local evidence.
- Export manifests should preserve enough lineage to understand what was produced, from what account/category/profile/config posture, when, and with what limits/splitting behavior.
- Export output must remain stable enough for repeatable review workflows.
- Do not let export convenience override custody, provenance, or scrub/profile semantics.

### Future uScientDB readiness

`mboxer` may later become a producer for uScientDB. Until explicitly instructed otherwise:

- Keep uScientDB integration optional and absent.
- Add only neutral event/manifest/lineage seams that are useful locally even without uScientDB.
- Treat future producer events as append-oriented descriptions of operations, not mutable source truth.
- Avoid raw body content in event-like payloads by default.
- Make future adapter boundaries easy to test without a running server.

## Development workflow

Before changes:

```bash
git status --short
python -m mboxer --help
```

For tests, prefer targeted tests first, then broader tests before final handoff:

```bash
python -m pytest tests/<targeted_test_file>.py
python -m pytest
```

If the project uses a virtual environment, activate it first. Inspect `pyproject.toml` before assuming optional dependency groups or tool commands.

When touching SQL/migrations:

- Inspect current schema and migration loader.
- Add migration tests.
- Verify fresh DB creation and migrated DB behavior when practical.
- Do not edit historical migrations unless explicitly instructed and safe for unreleased state.

When touching CLI behavior:

- Preserve help text quality.
- Add or update CLI tests.
- Document behavior changes in the final report.

When touching exports:

- Use temporary directories in tests.
- Check file naming, splitting limits, manifests, and scrub/profile behavior.
- Do not write sample exports into the repo root.

## Final report format

End every task with:

```text
What I inspected
Files changed
Behavior changes
Tests run
Risks / limitations
Instruction-surface changes
Suggested next step
```

Keep the report factual. Do not claim security, privacy, or lineage guarantees beyond what the code and tests actually prove.
