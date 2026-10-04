"""Packing failures and explicit use of reserved source slots through the CLI."""
from __future__ import annotations

import pytest


def setup_archive(run_cli, cli_config, mbox_factory):
    path = mbox_factory([
        "From: synthetic@example.invalid\nSubject: Synthetic\n"
        "Message-ID: <synthetic-limit>\n\nOrdinary synthetic body.\n"
    ])
    assert run_cli("init-db", "--config", cli_config).exit_code == 0
    assert run_cli("account", "add", "synthetic", "--config", cli_config).exit_code == 0
    assert run_cli("ingest", path, "--config", cli_config, "--account", "synthetic").exit_code == 0


@pytest.mark.parametrize("allow_full", [False, True])
def test_cli_reserved_sources_require_explicit_override(
    run_cli, cli_config, mbox_factory, tmp_path, allow_full,
):
    setup_archive(run_cli, cli_config, mbox_factory)
    out = tmp_path / "out"
    result = run_cli(
        "export", "notebooklm", "--config", cli_config, "--account", "synthetic",
        "--out", out, "--max-sources", 1, "--reserved-sources", 1,
        *(["--allow-full-source-budget"] if allow_full else []),
    )
    assert result.exit_code == (0 if allow_full else 1)
    assert bool(list(out.rglob("*.md"))) == allow_full


def test_cli_impossible_rendered_limit_is_clean_error(run_cli, cli_config, mbox_factory, tmp_path):
    setup_archive(run_cli, cli_config, mbox_factory)
    out = tmp_path / "out"
    result = run_cli(
        "export", "notebooklm", "--config", cli_config, "--account", "synthetic",
        "--out", out, "--max-words", 1,
    )
    assert result.exit_code == 1
    assert "rendered message cannot fit" in result.stderr
    assert "Traceback" not in result.stderr
    assert not out.exists()
