# Running the tests

## Commands

| Goal | Command | ~time |
|---|---|---|
| Fast inner loop (pure units) | `pytest -m unit` | ~0.6s |
| Full suite (deterministic order) | `pytest` | ~5s |
| With coverage (enforces the floor) | `pytest --cov=mboxer --cov-report=term-missing` | ~7s |
| Order-independence check | `pytest -p randomly` | ~5s |

## Markers

- `unit` — pure, isolated (no DB or filesystem); this is the fast inner loop.
- `integration` — exercises real SQLite in `tmp_path` or the mbox→DB→export flow.
- `e2e` — the single golden full-pipeline test (kept out of `-m unit`).
- `slow` — long-running; deselect with `-m "not slow"`.

Subsets compose, e.g. `pytest -m "unit or integration"`.

## Determinism & random order

Order is **deterministic by default** (reproducible runs, stable golden). Opt into
random order with `pytest -p randomly`; pytest-randomly prints `Using
--randomly-seed=<N>`. Reproduce an order-dependent failure with:

    pytest -p randomly --randomly-seed=<N>

CI runs random order as an informational canary (it surfaces order-dependence
without blocking merges).

## Coverage

The floor lives in `pyproject.toml` (`[tool.coverage.report] fail_under`) and is a
single source of truth — CI fails the build if total coverage drops below it.

## Property tests (Hypothesis)

`tests/test_properties.py` fuzzes the slug/filename safety boundary. It is bounded
to 300 examples to keep the inner loop fast; its example database (`.hypothesis/`)
is gitignored.

## Golden end-to-end test

`tests/test_e2e_pipeline.py` drives the real CLI through the whole pipeline and
compares all exported artifacts against `tests/golden/pipeline_export.json`
(volatile fields — timestamps, tmp paths, SHA-256 digests, and the setuptools-scm
tool version — are normalized first). After an **intentional** output change,
re-bless the golden:

    MBOXER_BLESS_GOLDEN=1 pytest tests/test_e2e_pipeline.py

## Fixtures

Shared fixtures live in `tests/conftest.py` (`tmp_db`, `make_account`,
`mbox_factory`, `config`, `mime_factory`, `run_cli`, `cli_config`, `ready`) and
importable helpers in `tests/_factories.py` (`make_mbox`, `base_config`,
`make_attachment_message`). Reuse these instead of re-building setup. The synthetic
corpus is `tests/fixtures/synthetic.mbox`, regenerated with
`python tests/fixtures/make_synthetic.py`.
