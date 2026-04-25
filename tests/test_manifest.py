"""Tests for manifest export: NotebookLM CSV/JSON manifests and JSONL manifest."""
import csv
import json
import sqlite3
import textwrap
import mailbox
from pathlib import Path

import pytest

from mboxer.accounts import create_account
from mboxer.classify import run_rule_classification
from mboxer.config import load_config
from mboxer.db import init_db
from mboxer.exporters.jsonl import export_jsonl
from mboxer.exporters.manifest import (
    MANIFEST_FIELDS,
    build_jsonl_manifest_rows,
    build_notebooklm_manifest_rows,
    write_jsonl_manifest,
    write_notebooklm_manifest,
)
from mboxer.exporters.notebooklm import export_notebooklm
from mboxer.ingest import ingest_mbox
from mboxer.limits import resolve_notebooklm_limits

# ── Shared fixtures ───────────────────────────────────────────────────────────

MSGS = [
    textwrap.dedent("""\
        From: billing@hospital.example.com
        To: user@example.com
        Subject: Your Hospital Bill
        Date: Mon, 01 Jan 2024 10:00:00 +0000
        Message-ID: <manifest-medical-001@example.com>

        Balance due: $350.00.
    """),
    textwrap.dedent("""\
        From: auto-reply@usps.com
        To: user@example.com
        Subject: Your Informed Delivery Daily Digest
        Date: Tue, 02 Jan 2024 08:00:00 +0000
        Message-ID: <manifest-usps-001@usps.com>

        Here are your mail pieces for today.
    """),
]

INGEST_CONFIG = {
    "paths": {"attachments_dir": "/tmp/test-manifest-attachments"},
    "ingest": {"batch_commit_size": 10, "store_body_html": False, "max_body_chars": 50000},
    "security": {"default_export_profile": "scrubbed"},
}

CLASSIFY_CONFIG = {
    **INGEST_CONFIG,
    "taxonomy": {"locked_categories": ["postal/usps-informed-delivery"]},
    "rules": [
        {
            "name": "usps-informed-delivery",
            "match": {
                "from_contains": ["usps"],
                "subject_contains": ["informed delivery"],
            },
            "assign": {
                "category_path": "postal/usps-informed-delivery",
                "sensitivity": "medium",
                "export_profile": "metadata-only",
            },
        }
    ],
}


def _make_mbox(path: Path, messages: list[str]) -> None:
    mbox = mailbox.mbox(str(path), create=True)
    for raw in messages:
        mbox.add(mailbox.mboxMessage(raw))
    mbox.flush()
    mbox.close()


@pytest.fixture()
def db_with_data(tmp_path):
    """DB with one account, ingested messages, and rule classifications."""
    db_path = tmp_path / "mboxer.sqlite"
    mbox_path = tmp_path / "test.mbox"
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    create_account(
        conn, "test-gmail",
        display_name="Test Gmail Account",
        email_address="user@example.com",
    )
    conn.close()
    _make_mbox(mbox_path, MSGS)
    ingest_mbox(mbox_path, config=CLASSIFY_CONFIG, db_path=db_path, account_key="test-gmail")
    conn = sqlite3.connect(db_path)
    account_id = conn.execute(
        "SELECT id FROM accounts WHERE account_key = 'test-gmail'"
    ).fetchone()[0]
    run_rule_classification(conn, CLASSIFY_CONFIG, account_id=account_id)
    conn.commit()
    conn.close()
    return db_path


@pytest.fixture()
def example_config():
    return load_config("config/mboxer.example.yaml")


# ── Unit: manifest builders ───────────────────────────────────────────────────

def test_build_notebooklm_manifest_rows_fields(tmp_path):
    fake_path = tmp_path / "cat-2024-001.md"
    fake_path.write_text("content")
    file_stats = [{
        "path": fake_path,
        "category_path": "medical",
        "date_band": "2024",
        "message_count": 3,
        "thread_count": 2,
        "word_count": 150,
        "byte_count": fake_path.stat().st_size,
        "date_min": "2024-01-01T10:00:00",
        "date_max": "2024-01-03T12:00:00",
    }]
    rows = build_notebooklm_manifest_rows(
        file_stats,
        account_key="test-gmail",
        account_display_name="Test Gmail",
        account_email_address="user@example.com",
        export_profile="raw",
        security_profile="scrubbed",
        created_at="2024-01-04T00:00:00Z",
    )
    assert len(rows) == 1
    r = rows[0]
    assert r["account_key"] == "test-gmail"
    assert r["account_display_name"] == "Test Gmail"
    assert r["account_email_address"] == "user@example.com"
    assert r["source_file"] == fake_path.name
    assert r["source_pack"] == fake_path.name
    assert r["category_path"] == "medical"
    assert r["message_count"] == 3
    assert r["thread_count"] == 2
    assert r["word_count"] == 150
    assert r["contains_scrubbed_content"] is False
    assert r["created_at"] == "2024-01-04T00:00:00Z"


def test_build_jsonl_manifest_rows_fields(tmp_path):
    out_path = tmp_path / "messages.jsonl"
    rows = build_jsonl_manifest_rows(
        account_key="test-gmail",
        account_display_name="Test Gmail",
        account_email_address="user@example.com",
        out_path=out_path,
        message_count=10,
        thread_count=4,
        date_min="2024-01-01T00:00:00",
        date_max="2024-12-31T00:00:00",
        word_count=5000,
        byte_count=102400,
        export_profile=None,
        security_profile="scrubbed",
        created_at="2025-01-01T00:00:00Z",
    )
    assert len(rows) == 1
    r = rows[0]
    assert r["account_key"] == "test-gmail"
    assert r["source_file"] == "messages.jsonl"
    assert r["message_count"] == 10
    assert r["thread_count"] == 4
    assert r["byte_count"] == 102400
    assert r["security_profile"] == "scrubbed"


def test_write_notebooklm_manifest_creates_files(tmp_path):
    rows = [{f: "" for f in MANIFEST_FIELDS}]
    csv_path, json_path = write_notebooklm_manifest(tmp_path, "test-gmail", rows)
    assert csv_path.exists()
    assert json_path.exists()
    assert csv_path == tmp_path / "test-gmail" / "manifest.csv"
    assert json_path == tmp_path / "test-gmail" / "manifest.json"


def test_write_notebooklm_manifest_csv_has_all_fields(tmp_path):
    rows = [{f: f"val-{f}" for f in MANIFEST_FIELDS}]
    csv_path, _ = write_notebooklm_manifest(tmp_path, "test-gmail", rows)
    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        assert reader.fieldnames == MANIFEST_FIELDS
        data_rows = list(reader)
    assert len(data_rows) == 1


def test_write_jsonl_manifest_path(tmp_path):
    out_path = tmp_path / "test-gmail" / "messages.jsonl"
    out_path.parent.mkdir(parents=True)
    rows = [{"account_key": "test-gmail"}]
    manifest_path = write_jsonl_manifest(out_path, rows)
    assert manifest_path == tmp_path / "test-gmail" / "messages.manifest.json"
    assert manifest_path.exists()


# ── Integration: NotebookLM manifest ─────────────────────────────────────────

def _do_notebooklm_export(db_path, tmp_path, account_key="test-gmail", dry_run=False):
    config = load_config("config/mboxer.example.yaml")
    limits = resolve_notebooklm_limits(config, "ultra_safe")
    conn = sqlite3.connect(db_path)
    try:
        account = conn.execute(
            "SELECT id, display_name, email_address FROM accounts WHERE account_key = ?",
            (account_key,),
        ).fetchone()
        account_id, display_name, email_address = account
        return export_notebooklm(
            conn, CLASSIFY_CONFIG, limits, tmp_path / "nlm_out",
            account_id=account_id,
            account_key=account_key,
            account_email=email_address,
            account_display_name=display_name,
            dry_run=dry_run,
            db_path=str(db_path),
        )
    finally:
        conn.close()


def test_notebooklm_manifest_csv_created(tmp_path, db_with_data):
    stats = _do_notebooklm_export(db_with_data, tmp_path)
    csv_path = Path(stats["manifest_csv"])
    assert csv_path.exists(), f"manifest.csv not found at {csv_path}"
    assert csv_path.name == "manifest.csv"
    assert "test-gmail" in csv_path.parts


def test_notebooklm_manifest_json_created(tmp_path, db_with_data):
    stats = _do_notebooklm_export(db_with_data, tmp_path)
    json_path = Path(stats["manifest_json"])
    assert json_path.exists(), f"manifest.json not found at {json_path}"
    data = json.loads(json_path.read_text())
    assert isinstance(data, list)
    assert len(data) >= 1


def test_notebooklm_manifest_csv_all_fields(tmp_path, db_with_data):
    stats = _do_notebooklm_export(db_with_data, tmp_path)
    with open(stats["manifest_csv"], newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        assert reader.fieldnames == MANIFEST_FIELDS
        rows = list(reader)
    assert len(rows) >= 1


def test_notebooklm_manifest_includes_account_metadata(tmp_path, db_with_data):
    stats = _do_notebooklm_export(db_with_data, tmp_path)
    data = json.loads(Path(stats["manifest_json"]).read_text())
    for row in data:
        assert row["account_key"] == "test-gmail"
        assert row["account_display_name"] == "Test Gmail Account"
        assert row["account_email_address"] == "user@example.com"


def test_notebooklm_manifest_counts_match_files(tmp_path, db_with_data):
    stats = _do_notebooklm_export(db_with_data, tmp_path)
    md_files = list((tmp_path / "nlm_out" / "test-gmail").rglob("*.md"))
    data = json.loads(Path(stats["manifest_json"]).read_text())
    assert len(md_files) == len(data) == stats["files_written"]


def test_notebooklm_manifest_message_counts(tmp_path, db_with_data):
    stats = _do_notebooklm_export(db_with_data, tmp_path)
    data = json.loads(Path(stats["manifest_json"]).read_text())
    total_messages = sum(row["message_count"] for row in data)
    assert total_messages == stats["messages_exported"]


def test_notebooklm_manifest_security_profile(tmp_path, db_with_data):
    stats = _do_notebooklm_export(db_with_data, tmp_path)
    data = json.loads(Path(stats["manifest_json"]).read_text())
    for row in data:
        assert row["security_profile"] == "scrubbed"
        assert row["contains_scrubbed_content"] is False


def test_notebooklm_dry_run_no_manifest_written(tmp_path, db_with_data):
    stats = _do_notebooklm_export(db_with_data, tmp_path, dry_run=True)
    assert stats["dry_run"] is True
    assert not Path(stats["manifest_csv"]).exists()
    assert not Path(stats["manifest_json"]).exists()
    # Paths are still reported in stats so callers know where they would land
    assert "test-gmail" in stats["manifest_csv"]
    assert "manifest.csv" in stats["manifest_csv"]
    assert "manifest.json" in stats["manifest_json"]


# ── Integration: JSONL manifest ───────────────────────────────────────────────

def test_jsonl_manifest_created(tmp_path, db_with_data):
    out = tmp_path / "test-gmail" / "messages.jsonl"
    conn = sqlite3.connect(db_with_data)
    try:
        account_id = conn.execute(
            "SELECT id FROM accounts WHERE account_key = 'test-gmail'"
        ).fetchone()[0]
        result = export_jsonl(
            conn, INGEST_CONFIG, out,
            account_id=account_id,
            account_key="test-gmail",
            account_display_name="Test Gmail Account",
            account_email_address="user@example.com",
        )
    finally:
        conn.close()

    manifest_path = Path(result["manifest_path"])
    assert manifest_path.exists()
    assert manifest_path.name == "messages.manifest.json"
    assert manifest_path.parent == out.parent


def test_jsonl_manifest_fields(tmp_path, db_with_data):
    out = tmp_path / "test-gmail" / "messages.jsonl"
    conn = sqlite3.connect(db_with_data)
    try:
        account_id = conn.execute(
            "SELECT id FROM accounts WHERE account_key = 'test-gmail'"
        ).fetchone()[0]
        result = export_jsonl(
            conn, INGEST_CONFIG, out,
            account_id=account_id,
            account_key="test-gmail",
            account_display_name="Test Gmail Account",
            account_email_address="user@example.com",
        )
    finally:
        conn.close()

    data = json.loads(Path(result["manifest_path"]).read_text())
    assert len(data) == 1
    row = data[0]
    assert row["account_key"] == "test-gmail"
    assert row["account_display_name"] == "Test Gmail Account"
    assert row["account_email_address"] == "user@example.com"
    assert row["source_file"] == "messages.jsonl"
    assert row["message_count"] == 2
    assert row["byte_count"] > 0
    assert row["security_profile"] == "scrubbed"
    for field in MANIFEST_FIELDS:
        assert field in row, f"Missing manifest field: {field}"


def test_jsonl_manifest_thread_count(tmp_path, db_with_data):
    out = tmp_path / "test-gmail" / "messages.jsonl"
    conn = sqlite3.connect(db_with_data)
    try:
        account_id = conn.execute(
            "SELECT id FROM accounts WHERE account_key = 'test-gmail'"
        ).fetchone()[0]
        result = export_jsonl(
            conn, INGEST_CONFIG, out,
            account_id=account_id,
            account_key="test-gmail",
        )
    finally:
        conn.close()

    data = json.loads(Path(result["manifest_path"]).read_text())
    row = data[0]
    # 2 separate messages with distinct thread keys → thread_count >= 1
    assert row["thread_count"] >= 1
    assert row["date_min"] != ""
    assert row["date_max"] != ""
