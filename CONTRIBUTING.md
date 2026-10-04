# Contributing

Normally develop on a focused branch from `dev` and open PRs into `dev`.
Promote integrated changes with a `dev` → `master` PR. A maintainer can request
a different target for a specific change, such as a documentation PR directly
into `master`. Version tags and publication are separate actions described below.

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

These activation commands assume a POSIX shell. On Windows PowerShell use
`.venv\Scripts\Activate.ps1` instead. Run the commands below with the selected
environment's Python. The editable install keeps runtime imports connected to
`src/`; the version metadata is computed during installation, so reinstall after
switching revisions if you need it to reflect the new checkout.

For an editable user configuration, create its directory and print the bundled
example. Runtime commands use this copy only when given `--config`:

```bash
mkdir -p config
mboxer config-example > config/mboxer.yaml
```

The canonical example is `src/mboxer/defaults.yaml`; do not maintain a second
tracked copy. Existing local `config/mboxer.example.yaml` files retain precedence
when no explicit `--config` is supplied. Configuration-relative paths are not
rebased to the YAML file: relative paths use the current working directory.
See [configuration](docs/configuration.md) for fallback behavior and active settings.

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

## CI and automated reviews

The checked-in workflows have different responsibilities:

| Workflow | Trigger and behavior |
| --- | --- |
| CI | Pushes and PRs targeting `dev` or `master`, plus manual runs; runs Ruff/mypy, the full suite on Python 3.11/3.12, and an installed-wheel smoke test when selected. Coverage runs on 3.11. |
| Dependency Review | Pull requests; checks dependency changes. |
| Bandit | Pushes and PRs targeting `dev` or `master`, plus a weekly scan; uploads security findings. Its `exit_zero: true` setting makes findings advisory, although operational failures can still fail the job. |
| Random order canary | Weekly and manual; scheduled runs test `dev`, manual runs test the selected ref. |
| Publish to PyPI | A published GitHub Release; see the release sequence below. |

**CI gate** requires all selected CI jobs to pass. The selector skips expensive
jobs only for its explicit documentation allowlist. `README.md` runs the full
checks because it is package metadata; `HOWTO.md` and `tests/README.md` are also
outside the current skip allowlist. An unknown path runs all checks. Required
checks and review requirements are configured separately in GitHub rulesets;
workflow files alone do not make checks merge requirements.

GitHub-managed CodeQL security scanning and Code Quality can appear in Actions
without a workflow file in this repository. Their enablement and review behavior
are repository/organization settings. Assess review findings against behavior and
tests; reply with the fix or the evidence for rejecting a suggestion, then resolve
the conversation. A resolved conversation is separate from disabling a scanner.

## Installed package verification

For changes to packaging or bundled resources:

```bash
python -m pip install build
python -m build
python scripts/smoke_wheel.py dist/<wheel-filename>.whl
```

Replace the placeholder with one wheel produced by the build. The smoke script
creates a temporary virtual environment and working directory, installs that
wheel, and checks configuration resources, entrypoints, migrations, and accounts.
Dependency installation requires access to the configured Python package index.

## Releases and PyPI publication

Merging into `master` does **not** publish a package. The trigger in
[publish.yml](.github/workflows/publish.yml) is `release: types: [published]`.
The release sequence is:

1. Merge the intended changes into `master` and check their CI results.
2. Select an unused version tag, such as `vX.Y.Z`, at the intended commit. Package
   versions are derived from Git tags by `setuptools-scm`; there is no version
   literal to bump in `pyproject.toml`.
3. Publish the GitHub Release for that tag. Saving a draft release or pushing a
   tag alone does not trigger this workflow.
4. Check **Publish to PyPI** in Actions and confirm the published version on
   [PyPI](https://pypi.org/project/uscient-mboxer/).

The workflow builds an sdist and wheel, then publishes the artifacts through the
`pypi` GitHub environment with an OIDC token. Environment approvals and PyPI's
trusted-publisher configuration are maintained outside the repository. The
workflow does not run the test suite itself and does not restrict releases to
`master`, so the selected commit and its verification matter. Automatic version
selection, tag creation, and release creation on merge are not implemented.

Include the behavior changed, checks run, and remaining limitations in the PR.
The [maintenance audit](docs/maintenance-audit.md) records remaining work; it does
not change the scope of an individual task.
