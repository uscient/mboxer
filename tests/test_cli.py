"""CLI surface tests.

Drives ``mboxer.cli.main`` through the ``run_cli`` fixture (argv -> main ->
captured exit_code/stdout/stderr) and asserts observable effects: exit codes,
DB/file state, and key output substrings — never whole stdout dumps. This covers
the argparse wiring, every subcommand's happy path, and the contract errors
(config-not-found, account required/unknown, unknown profile, bad input).
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from mboxer.config import load_config

SYNTHETIC_MBOX = Path(__file__).parent / "fixtures" / "synthetic.mbox"


def _db_path(cli_config: Path) -> Path:
    return Path(load_config(str(cli_config))["paths"]["database"])


# ── argument parsing / help ───────────────────────────────────────────────────

@pytest.mark.integration
def test_no_command_exits_2(run_cli):
    assert run_cli().exit_code == 2


@pytest.mark.integration
def test_unknown_command_exits_2(run_cli):
    assert run_cli("frobnicate").exit_code == 2


@pytest.mark.integration
def test_help_lists_subcommands(run_cli):
    result = run_cli("--help")
    assert result.exit_code == 0
    assert "init-db" in result.stdout
    assert "export" in result.stdout


# ── init-db ───────────────────────────────────────────────────────────────────

@pytest.mark.integration
def test_init_db_creates_database(run_cli, cli_config):
    result = run_cli("init-db", "--config", cli_config)
    assert result.exit_code == 0
    assert "Database ready" in result.stdout
    assert _db_path(cli_config).exists()


@pytest.mark.integration
def test_missing_config_exits_with_message(run_cli, tmp_path):
    result = run_cli("init-db", "--config", tmp_path / "does-not-exist.yaml")
    assert result.exit_code == 1
    assert "Config file not found" in result.stderr


# ── account ───────────────────────────────────────────────────────────────────

@pytest.mark.integration
def test_account_add_then_list_shows_it(run_cli, cli_config):
    add = run_cli("account", "add", "primary-gmail", "--email", "u@example.com",
                  "--config", cli_config)
    assert add.exit_code == 0
    assert "Added account" in add.stdout

    listing = run_cli("account", "list", "--config", cli_config)
    assert "primary-gmail" in listing.stdout
    # persisted
    conn = sqlite3.connect(_db_path(cli_config))
    try:
        assert conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0] == 1
    finally:
        conn.close()


@pytest.mark.integration
def test_account_list_empty(run_cli, cli_config):
    result = run_cli("account", "list", "--config", cli_config)
    assert result.exit_code == 0
    assert "No accounts configured" in result.stdout


@pytest.mark.integration
def test_account_show_existing_and_missing(run_cli, cli_config):
    run_cli("account", "add", "primary-gmail", "--email", "u@example.com", "--config", cli_config)

    shown = run_cli("account", "show", "primary-gmail", "--config", cli_config)
    assert shown.exit_code == 0
    assert "u@example.com" in shown.stdout

    missing = run_cli("account", "show", "ghost", "--config", cli_config)
    assert missing.exit_code != 0
    assert "not found" in (missing.stderr + missing.stdout).lower()


@pytest.mark.integration
def test_account_update_changes_display_name(run_cli, cli_config):
    run_cli("account", "add", "primary-gmail", "--config", cli_config)
    upd = run_cli("account", "update", "primary-gmail", "--display-name", "Primary",
                  "--config", cli_config)
    assert upd.exit_code == 0
    assert "Updated account" in upd.stdout
    assert "Primary" in run_cli("account", "show", "primary-gmail", "--config", cli_config).stdout


@pytest.mark.integration
def test_account_update_missing_exits_nonzero(run_cli, cli_config):
    run_cli("init-db", "--config", cli_config)
    result = run_cli("account", "update", "ghost", "--display-name", "X", "--config", cli_config)
    assert result.exit_code != 0


# ── account resolution contracts ──────────────────────────────────────────────

@pytest.mark.integration
def test_command_requires_account_when_multiple_exist(run_cli, cli_config):
    run_cli("account", "add", "a-gmail", "--config", cli_config)
    run_cli("account", "add", "b-gmail", "--config", cli_config)
    result = run_cli("classify", "--config", cli_config)
    assert result.exit_code == 1
    assert "requires --account" in result.stderr


@pytest.mark.integration
def test_unknown_account_exits_with_hint(run_cli, cli_config):
    result = run_cli(
        "ingest", str(SYNTHETIC_MBOX), "--config", cli_config, "--account", "ghost",
    )
    assert result.exit_code == 1
    assert "not found" in result.stderr.lower()


# ── ingest / classify / review / security (happy paths) ───────────────────────

@pytest.mark.integration
def test_ingest_inserts_messages(run_cli, cli_config):
    run_cli("account", "add", "primary-gmail", "--config", cli_config)
    result = run_cli(
        "ingest", str(SYNTHETIC_MBOX),
        "--config", cli_config, "--account", "primary-gmail", "--source-name", "syn",
    )
    assert result.exit_code == 0
    assert "inserted=5" in result.stdout
    conn = sqlite3.connect(_db_path(cli_config))
    try:
        assert conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 5
    finally:
        conn.close()


@pytest.mark.integration
def test_classify_reports_results(run_cli, ready):
    result = run_cli("classify", "--config", ready, "--account", "primary-gmail")
    assert result.exit_code == 0
    assert "classified" in result.stdout


@pytest.mark.integration
def test_review_categories_lists_taxonomy(run_cli, ready):
    run_cli("classify", "--config", ready, "--account", "primary-gmail")
    result = run_cli("review-categories", "--config", ready, "--account", "primary-gmail")
    assert result.exit_code == 0
    assert "Categories for account" in result.stdout


@pytest.mark.integration
def test_security_scan_runs(run_cli, ready):
    result = run_cli("security-scan", "--config", ready, "--account", "primary-gmail")
    assert result.exit_code == 0
    assert "Scanned" in result.stdout


# ── category proposal error paths ─────────────────────────────────────────────

@pytest.mark.integration
def test_approve_missing_proposal_exits_nonzero(run_cli, ready):
    result = run_cli("approve-category", "999999", "--config", ready)
    assert result.exit_code != 0


@pytest.mark.integration
def test_reject_missing_proposal_exits_nonzero(run_cli, ready):
    result = run_cli("reject-category", "999999", "--config", ready)
    assert result.exit_code != 0


# ── export ────────────────────────────────────────────────────────────────────

@pytest.mark.integration
def test_export_notebooklm_dry_run_writes_nothing(run_cli, ready, tmp_path):
    out = tmp_path / "nlm"
    result = run_cli(
        "export", "notebooklm", "--config", ready, "--account", "primary-gmail",
        "--profile", "ultra_safe", "--out", out, "--dry-run",
    )
    assert result.exit_code == 0
    assert "Dry run" in result.stdout
    assert not out.exists()


@pytest.mark.integration
def test_export_notebooklm_writes_account_scoped_files(run_cli, ready, tmp_path):
    run_cli("classify", "--config", ready, "--account", "primary-gmail")
    out = tmp_path / "nlm"
    result = run_cli(
        "export", "notebooklm", "--config", ready, "--account", "primary-gmail",
        "--profile", "ultra_safe", "--out", out,
    )
    assert result.exit_code == 0
    assert "Exported" in result.stdout
    md_files = list(out.rglob("*.md"))
    assert md_files
    assert all("primary-gmail" in str(f) for f in md_files)


@pytest.mark.integration
def test_export_unknown_profile_exits(run_cli, ready):
    result = run_cli(
        "export", "notebooklm", "--config", ready, "--account", "primary-gmail",
        "--profile", "does-not-exist",
    )
    assert result.exit_code == 1
    assert "Unknown NotebookLM profile" in result.stderr


@pytest.mark.integration
def test_export_jsonl_writes_account_scoped_file(run_cli, ready, tmp_path):
    out = tmp_path / "rag" / "messages.jsonl"
    result = run_cli(
        "export", "jsonl", "--config", ready, "--account", "primary-gmail", "--out", out,
    )
    assert result.exit_code == 0
    assert "Wrote" in result.stdout
    written = tmp_path / "rag" / "primary-gmail" / "messages.jsonl"
    assert written.exists()


# ── multi-account + inline account + LLM-not-wired branches ───────────────────

@pytest.mark.integration
def test_ingest_create_account_inline(run_cli, cli_config):
    result = run_cli(
        "ingest", str(SYNTHETIC_MBOX),
        "--config", cli_config, "--account", "fresh-acct", "--create-account",
        "--source-name", "syn",
    )
    assert result.exit_code == 0
    assert "Created account" in result.stdout
    conn = sqlite3.connect(_db_path(cli_config))
    try:
        assert conn.execute(
            "SELECT COUNT(*) FROM accounts WHERE account_key = 'fresh-acct'"
        ).fetchone()[0] == 1
    finally:
        conn.close()


@pytest.mark.integration
def test_export_notebooklm_combined_accounts_stay_isolated(
    run_cli, cli_config, mbox_factory, tmp_path
):
    """Combined --accounts export: each account's content and manifest land under
    its own directory with no cross-account bleed (mbox_sources.file_path is unique,
    so each account also needs its own source file)."""
    def _msg(key, marker):
        return (
            f"From: s@example.com\nTo: u@example.com\nSubject: {marker} note\n"
            f"Date: Mon, 01 Jan 2024 10:00:00 +0000\nMessage-ID: <{key}-1@example.com>\n\n"
            f"This is {marker} unique body content.\n"
        )
    for key, marker in (("alpha", "ALPHA"), ("beta", "BETA")):
        run_cli("account", "add", key, "--config", cli_config)
        mbox = mbox_factory([_msg(key, marker)], name=f"{key}.mbox")
        run_cli("ingest", str(mbox), "--config", cli_config, "--account", key, "--source-name", "syn")

    out = tmp_path / "nlm"
    result = run_cli(
        "export", "notebooklm", "--config", cli_config,
        "--accounts", "alpha,beta", "--profile", "ultra_safe", "--out", out,
    )
    assert result.exit_code == 0

    alpha_md = "\n".join(f.read_text() for f in (out / "alpha").rglob("*.md"))
    beta_md = "\n".join(f.read_text() for f in (out / "beta").rglob("*.md"))
    assert "ALPHA" in alpha_md and "BETA" not in alpha_md
    assert "BETA" in beta_md and "ALPHA" not in beta_md

    for key in ("alpha", "beta"):
        manifest = json.loads((out / key / "manifest.json").read_text())
        assert manifest  # non-empty
        assert all(row["account_key"] == key for row in manifest)  # no provenance mix-up
        # Lineage structure is present (field presence, not timestamp values).
        assert {"tool_name", "export_kind", "account_key", "source_pack"} <= set(manifest[0].keys())


@pytest.mark.integration
def test_classify_model_flag_reports_not_implemented(run_cli, ready):
    result = run_cli(
        "classify", "--config", ready, "--account", "primary-gmail", "--model", "llama3.1:8b",
    )
    assert result.exit_code == 0
    assert "not yet implemented" in result.stdout
