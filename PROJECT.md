# Implementation map

The installed command is `mboxer` (`mboxer.cli:main`); `python -m mboxer` uses
the same entrypoint. Runtime code lives in `src/mboxer/`.

| Area | Implementation | Verification |
| --- | --- | --- |
| CLI and configuration | `cli.py`, `config.py`, `defaults.yaml` | `test_cli.py`, `test_config.py`, `test_first_run.py` |
| Accounts and safe names | `accounts.py`, `naming.py` | `test_accounts.py`, `test_naming.py`, `test_properties.py` |
| SQLite initialization | `db/schema.py`, `db/migrations/` | `test_db.py`, `test_migration*.py` |
| Ingest and recovery | `ingest.py` | `test_ingest*.py` |
| Message decoding | `normalize.py`, `attachments.py`, `mime.py`, `records.py` | `test_normalize.py`, `test_attachments.py`, `test_address_invariant.py` |
| Rule classification and taxonomy | `classify.py`, `taxonomy.py` | `test_classify.py`, `test_thread_classify.py`, `test_taxonomy.py` |
| Detection, redaction, and policy | `security/` | `test_scrub_export.py`, `test_findings_gate.py`, `test_policy_resolution.py` |
| Effective export classification | `exporters/classification.py` | `test_policy_resolution.py`, `test_export_boundaries.py` |
| Record projection | `exporters/projection.py` | `test_scrub_export.py`, `test_streaming_export.py` |
| JSONL and NotebookLM | `exporters/jsonl.py`, `exporters/notebooklm.py`, `limits.py` | `test_export*.py`, `test_notebooklm_packing.py`, `test_limits.py` |
| Publication and recovery | `exporters/publication.py` | `test_publication.py` |
| File manifests and database lineage | `exporters/manifest.py` | `test_manifest.py`, `test_e2e_pipeline.py` |

Test paths above are relative to `tests/`. The migration-built schema is the
runtime source; `db/schema.sql` is a reference snapshot compared against it by
the migration tests.

## Shared behavior

- Configuration loading, dotted lookup, and configured paths live in `config.py`.
  `defaults.yaml` is the bundled example; explicit YAML files remain independent
  configurations, rather than being merged with the example's rules and taxonomy.
- `records.py` decodes stored address lists. `mime.py` shares header decoding
  and attachment selection between normalization and extraction; `files.py`
  streams file hashing for ingest and export lineage.
- `security/patterns.py` defines the regexes, redaction switches, and replacement
  text used by detection and scrubbing. `security/policy.py` resolves content
  profiles and findings policies.
- Both exporters use the effective-classification query, record projection,
  residual findings gate, and safe lineage metadata helpers. They retain their
  format-specific rendering and publication behavior.
- SQLite staging supports streaming exports and exact NotebookLM packing.
  Publication owns rollback and destination-local copies; callers do not need
  to duplicate filesystem recovery logic.

## Detailed references

- [Architecture](docs/architecture.md)
- [Ingest integrity](docs/ingest-integrity.md)
- [SQLite schema](docs/sqlite-schema.md)
- [NotebookLM packing and publication](docs/notebooklm-limits.md)
- [Security behavior and remaining work](docs/security-roadmap.md)
- [Performance](docs/performance.md) and [export memory](docs/export-memory.md)

`scripts/benchmark.py` and `scripts/benchmark_memory.py` measure synthetic
workloads. `scripts/smoke_wheel.py` exercises an installed package outside the
checkout. Development commands and CI are described in
[CONTRIBUTING.md](CONTRIBUTING.md).
