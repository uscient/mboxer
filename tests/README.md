# Running the tests

## Commands

From the repository root, activate the development environment described in
[CONTRIBUTING.md](../CONTRIBUTING.md) and install `.[dev]`. Generate the synthetic
fixture before running tests that use it:

```bash
python tests/fixtures/make_synthetic.py
```

| Goal | Command |
| --- | --- |
| Marked unit subset | `python -m pytest -m unit` |
| Full suite (deterministic order) | `python -m pytest` |
| With branch-enabled coverage and the configured floor | `python -m pytest --cov=mboxer --cov-report=term-missing` |
| Order-independence check | `python -m pytest -p randomly -o addopts="--strict-markers --strict-config"` |

Durations depend on the machine, Python version, and generated Hypothesis cases;
the commands above are verification entrypoints, not timing guarantees.

## Markers

- `unit` — pure, isolated (no DB or filesystem); this is the fast inner loop.
- `integration` — exercises real SQLite in `tmp_path` or the mbox→DB→export flow.
- `e2e` — the golden full-pipeline test (kept out of `-m unit`).
- `slow` — long-running; deselect with `-m "not slow"`.

Subsets compose, e.g. `python -m pytest -m "unit or integration"`. Many tests
are unmarked; selecting markers is not a substitute for running the full suite.

## Behavior-focused checks

Use [PROJECT.md](../PROJECT.md) to map implementation areas to tests. Some
cross-cutting checks are:

| Contract | Test files under `tests/` |
| --- | --- |
| Configuration and CLI first run | `test_config.py`, `test_cli.py`, `test_first_run.py` |
| Account/source identity, resumability, and replacement rollback | `test_ingest_integrity.py`, `test_ingest_review.py`, `test_migration_integrity.py` |
| Attachment filenames and interruption cleanup | `test_attachments.py`, `test_ingest_attachment_filenames.py`, `test_interrupt_cleanup.py` |
| Export policy, body scrubbing, and residual findings | `test_policy_resolution.py`, `test_export_boundaries.py`, `test_scrub_export.py`, `test_findings_gate.py` |
| Exact packing, publication rollback, and memory-oriented iteration | `test_notebooklm_packing.py`, `test_publication.py`, `test_streaming_export.py` |

For example:

```bash
python -m pytest tests/test_interrupt_cleanup.py tests/test_ingest_attachment_filenames.py
```

## Determinism & random order

Order is **deterministic by default** (reproducible runs, stable golden). Opt into
random order with the command above; the `addopts` override removes the default
`-p no:randomly` setting. pytest-randomly prints `Using
--randomly-seed=<N>`. Reproduce an order-dependent failure with:

```bash
python -m pytest -p randomly -o addopts="--strict-markers --strict-config" --randomly-seed=12345
```

Replace `12345` with the failing run's seed.

The separate Random order workflow runs weekly and via `workflow_dispatch`; it surfaces
order-dependence without adding another full-suite job to each PR. Failures make that
workflow fail. Whether a workflow is required for merging is a separate GitHub
ruleset setting; the canary is not part of the checked-in **CI gate** dependencies.

## Coverage

The floor lives in `pyproject.toml` (`[tool.coverage.report] fail_under`) and is a
single source of truth. Coverage includes branches; the Python 3.11 CI job fails
when total coverage falls below that floor. The Python 3.12 job runs the same
suite without duplicate coverage collection.

## Property tests (Hypothesis)

`tests/test_properties.py` fuzzes the slug/filename safety boundary. It is bounded
to 300 generated examples per property, plus explicit regression examples; its
example database (`.hypothesis/`)
is gitignored.

## Golden end-to-end test

`tests/test_e2e_pipeline.py` drives the real CLI through the whole pipeline and
compares all exported artifacts against `tests/golden/pipeline_export.json`
(volatile fields — timestamps, tmp paths, SHA-256 digests, and the setuptools-scm
tool version — are normalized first). After an **intentional** output change,
re-bless the golden:

```bash
MBOXER_BLESS_GOLDEN=1 python -m pytest tests/test_e2e_pipeline.py
python -m pytest tests/test_e2e_pipeline.py
```

The first command updates the tracked snapshot and skips the comparison. Inspect
its diff, then run the second command without the environment variable to verify
it. This environment-variable syntax assumes a POSIX shell. Normalization means
the golden test does not itself prove hash correctness; focused tests cover that.

## Fixtures

Shared fixtures live in `tests/conftest.py` (`tmp_db`, `make_account`,
`mbox_factory`, `config`, `mime_factory`, `run_cli`, `cli_config`, `ready`) and
importable helpers in `tests/_factories.py` (`make_mbox`, `base_config`,
`make_attachment_message`). Reuse these instead of re-building setup. The synthetic
corpus is `tests/fixtures/synthetic.mbox`, regenerated with
`python tests/fixtures/make_synthetic.py`.

## Installed distribution

PR CI builds a distribution and runs `scripts/smoke_wheel.py` against the wheel in a fresh
virtual environment and unrelated working directory. This verifies bundled defaults,
console/module entrypoints, actual migrations, account persistence, and explicit config errors.
Source-tree tests alone cannot verify package resources are shipped. The smoke
script takes exactly one wheel path and installs dependencies from the configured
package index. See [installed package verification](../CONTRIBUTING.md#installed-package-verification)
for the build and smoke commands.
