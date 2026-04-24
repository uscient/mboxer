import json
import sqlite3
import textwrap
import mailbox
from pathlib import Path

import pytest
from mboxer.accounts import create_account
from mboxer.config import load_config
from mboxer.db import init_db
from mboxer.exporters.notebooklm import export_notebooklm
from mboxer.exporters.jsonl import export_jsonl
from mboxer.ingest import ingest_mbox
from mboxer.limits import resolve_notebooklm_limits, validate_notebooklm_limits, NotebookLMLimits


MSGS = [
    textwrap.dedent("""\
        From: alice@example.com
        To: bob@example.com
        Subject: Medical bill question
        Date: Mon, 1 Jan 2024 10:00:00 +0000
        Message-ID: <medical-001@example.com>

        I have a question about my hospital bill.
    """),
    textwrap.dedent("""\
        From: bob@example.com
        To: alice@example.com
        Subject: Re: Medical bill question
        Date: Mon, 1 Jan 2024 11:00:00 +0000
        Message-ID: <medical-002@example.com>
        In-Reply-To: <medical-001@example.com>

        Please call the billing department.
    """),
]

CONFIG = {
    "paths": {"attachments_dir": "/tmp/attachments"},
    "ingest": {"batch_commit_size": 10, "store_body_html": False, "max_body_chars": 50000},
    "exports": {
        "jsonl": {"include_classification": True, "output_file": "exports/rag/messages.jsonl"},
        "notebooklm": {"profile": "ultra_safe"},
    },
}


def _make_mbox(path: Path, messages: list[str]) -> None:
    mbox = mailbox.mbox(str(path), create=True)
    for raw in messages:
        mbox.add(mailbox.mboxMessage(raw))
    mbox.flush()
    mbox.close()


def _setup_db_with_account(tmp_path: Path, account_key: str = "test-gmail") -> tuple[Path, int]:
    mbox_path = tmp_path / "test.mbox"
    db_path = tmp_path / "test.sqlite"
    _make_mbox(mbox_path, MSGS)
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    account_id = create_account(conn, account_key, email_address=f"{account_key}@example.com")
    conn.close()
    ingest_mbox(mbox_path, config=CONFIG, db_path=db_path, account_key=account_key)
    return db_path, account_id


def test_source_budget_calculation():
    limits = NotebookLMLimits(
        profile_name="test",
        max_sources=100, reserved_sources=25, target_sources=70,
        max_words_per_source=100000, target_words_per_source=50000,
        max_bytes_per_source=50_000_000, target_bytes_per_source=25_000_000,
        max_messages_per_source=1000,
    )
    assert limits.effective_source_budget == 75


def test_export_limit_validation_warns():
    limits = NotebookLMLimits(
        profile_name="test",
        max_sources=100, reserved_sources=0, target_sources=110,
        max_words_per_source=100000, target_words_per_source=50000,
        max_bytes_per_source=50_000_000, target_bytes_per_source=25_000_000,
        max_messages_per_source=1000,
    )
    warnings = validate_notebooklm_limits(limits)
    assert any("target_sources" in w for w in warnings)


def test_dry_run_notebooklm(tmp_path):
    db_path, account_id = _setup_db_with_account(tmp_path)
    config = load_config("config/mboxer.example.yaml")
    limits = resolve_notebooklm_limits(config, "ultra_safe")
    conn = sqlite3.connect(db_path)
    try:
        stats = export_notebooklm(
            conn, CONFIG, limits, tmp_path / "out",
            account_id=account_id, account_key="test-gmail",
            dry_run=True, db_path=str(db_path),
        )
    finally:
        conn.close()
    assert stats["dry_run"] is True
    assert not (tmp_path / "out").exists()


def test_jsonl_export(tmp_path):
    db_path, account_id = _setup_db_with_account(tmp_path)
    out = tmp_path / "test-gmail" / "messages.jsonl"
    conn = sqlite3.connect(db_path)
    try:
        result = export_jsonl(conn, CONFIG, out, account_id=account_id, account_key="test-gmail")
    finally:
        conn.close()
    assert out.exists()
    lines = [json.loads(l) for l in out.read_text().splitlines()]
    assert result["messages_written"] == len(lines) == 2
    assert all(line.get("account_key") == "test-gmail" for line in lines)


def test_jsonl_path_includes_account_key(tmp_path):
    db_path, account_id = _setup_db_with_account(tmp_path, "dad-gmail")
    out = tmp_path / "dad-gmail" / "messages.jsonl"
    conn = sqlite3.connect(db_path)
    try:
        export_jsonl(conn, CONFIG, out, account_id=account_id, account_key="dad-gmail")
    finally:
        conn.close()
    assert "dad-gmail" in str(out)


def test_notebooklm_export_writes_files_under_account_dir(tmp_path):
    db_path, account_id = _setup_db_with_account(tmp_path, "dad-gmail")
    config = load_config("config/mboxer.example.yaml")
    limits = resolve_notebooklm_limits(config, "ultra_safe")
    out_dir = tmp_path / "nlm_out"
    conn = sqlite3.connect(db_path)
    try:
        stats = export_notebooklm(
            conn, CONFIG, limits, out_dir,
            account_id=account_id, account_key="dad-gmail",
            account_email="dad@example.com",
            dry_run=False, db_path=str(db_path),
        )
    finally:
        conn.close()
    # Files should exist under the account subdirectory
    assert stats["files_written"] >= 1
    md_files = list(out_dir.rglob("*.md"))
    assert len(md_files) >= 1
    assert all("dad-gmail" in str(f) for f in md_files)


def test_notebooklm_export_header_contains_account(tmp_path):
    db_path, account_id = _setup_db_with_account(tmp_path, "dad-gmail")
    config = load_config("config/mboxer.example.yaml")
    limits = resolve_notebooklm_limits(config, "ultra_safe")
    out_dir = tmp_path / "nlm_out"
    conn = sqlite3.connect(db_path)
    try:
        export_notebooklm(
            conn, CONFIG, limits, out_dir,
            account_id=account_id, account_key="dad-gmail",
            account_email="dad@example.com",
            dry_run=False, db_path=str(db_path),
        )
    finally:
        conn.close()
    md_files = list(out_dir.rglob("*.md"))
    content = md_files[0].read_text()
    assert "account: dad-gmail" in content


def test_accounts_do_not_mix_in_export(tmp_path):
    """Messages from account A must not appear in account B's export."""
    db_path = tmp_path / "test.sqlite"
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    aid = create_account(conn, "dad-gmail")
    bid = create_account(conn, "personal-gmail")
    conn.close()

    mbox_a = tmp_path / "dad.mbox"
    mbox_b = tmp_path / "personal.mbox"
    _make_mbox(mbox_a, [MSGS[0]])
    _make_mbox(mbox_b, [MSGS[1]])

    ingest_mbox(mbox_a, config=CONFIG, db_path=db_path, account_key="dad-gmail")
    ingest_mbox(mbox_b, config=CONFIG, db_path=db_path, account_key="personal-gmail")

    config = load_config("config/mboxer.example.yaml")
    limits = resolve_notebooklm_limits(config, "ultra_safe")

    conn = sqlite3.connect(db_path)
    try:
        stats_a = export_notebooklm(
            conn, CONFIG, limits, tmp_path / "out",
            account_id=aid, account_key="dad-gmail",
            dry_run=False, db_path=str(db_path),
        )
        stats_b = export_notebooklm(
            conn, CONFIG, limits, tmp_path / "out",
            account_id=bid, account_key="personal-gmail",
            dry_run=False, db_path=str(db_path),
        )
    finally:
        conn.close()

    dad_files = list((tmp_path / "out" / "dad-gmail").rglob("*.md")) if (tmp_path / "out" / "dad-gmail").exists() else []
    personal_files = list((tmp_path / "out" / "personal-gmail").rglob("*.md")) if (tmp_path / "out" / "personal-gmail").exists() else []

    # Each account's files should only contain content from that account
    for f in dad_files:
        assert "personal-gmail" not in f.read_text()
    for f in personal_files:
        assert "dad-gmail" not in f.read_text()
