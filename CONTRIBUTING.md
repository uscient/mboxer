# Contributing

Develop on a focused branch from `dev` and open PRs into `dev`. Version tags
and publication remain deliberate maintainer actions.

[PROJECT.md](PROJECT.md) maps implementation ownership and shared components.
AGENTS.md provides navigation; executable behavior belongs in source,
configuration, and tests. Historical agent setup packs and speculative task
prompts have been removed.

## Local setup

Use Python 3.11 or newer in a virtual environment. From the checkout:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
python tests/fixtures/make_synthetic.py
python -m mboxer --help
```

For an editable user configuration, create its directory and print the bundled
example. Runtime commands use this copy only when given `--config`:

```bash
mkdir -p config
mboxer config-example > config/mboxer.yaml
```

The canonical example is `src/mboxer/defaults.yaml`; do not maintain a second
tracked copy. Existing local `config/mboxer.example.yaml` files retain precedence
when no explicit `--config` is supplied.

## Verification

Reuse the shared fixtures and factories in `tests/`. Add behavioral regressions
for changed contracts, especially account isolation, ingest recovery, migration
preservation, and export profile handling. Use synthetic messages and temporary
directories; do not commit real archives, extracted attachments, or databases.

```bash
python -m pytest tests/test_config.py
python -m ruff check src/
python -m mypy src/
python -m pytest --cov=mboxer --cov-report=term-missing
```

See [tests/README.md](tests/README.md) for test subsets, property tests, and the
golden-output workflow, and [docs/performance.md](docs/performance.md) for
repeatable performance measurements. Update a golden only for an intentional,
reviewed output change.

CI checks PRs into `dev` and `master`. Configure **CI gate** as the required
branch-protection check: it succeeds for explicitly scoped documentation-only
changes and requires all selected jobs to pass for code, configuration, package,
workflow, or unknown changes. The full test suite covers actual migrations;
the package job tests the installed wheel outside the checkout. The separate
random-order canary runs weekly and manually without adding per-PR work.

For changes to packaging or bundled resources:

```bash
python -m pip install build
python -m build
python scripts/smoke_wheel.py dist/<wheel-filename>.whl
```

Include the behavior changed, checks run, and remaining limitations in the PR.
The [maintenance audit](docs/maintenance-audit.md) records remaining work; it does
not change the scope of an individual task.
