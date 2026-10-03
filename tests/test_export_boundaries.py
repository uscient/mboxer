"""Policy and filesystem regressions using only synthetic messages."""
from __future__ import annotations

import email
import hashlib
import json
import sqlite3
from contextlib import nullcontext
from pathlib import Path

import pytest

from mboxer.accounts import AccountError, create_account, get_account, update_account
from mboxer.attachments import attachment_output_path, extract_attachments
from mboxer.config import load_config
from mboxer.db import init_db
from mboxer.exporters.jsonl import export_jsonl
from mboxer.exporters.manifest import write_notebooklm_manifest
from mboxer.exporters.notebooklm import export_notebooklm
from mboxer.ingest import ingest_mbox
from mboxer.limits import resolve_notebooklm_limits

from _factories import base_config, make_attachment_message, make_mbox

BODY = "Synthetic contact: 555-867-5309."
PROFILES = ("raw", "reviewed", "scrubbed", "metadata-only", "exclude")


@pytest.fixture
def classified_mail(tmp_path):
    db_path = tmp_path / "mail.sqlite"
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    account_id = create_account(conn, "synthetic")
    config = base_config(
        paths={"attachments_dir": str(tmp_path / "attachments")},
        security={
            "default_export_profile": "raw",
            "scrub_enabled": True,
            "redact_phone_numbers": True,
            "on_residual_findings": "allow",
        },
    )
    mbox_path = tmp_path / "synthetic.mbox"
    make_mbox(mbox_path, [
        make_attachment_message(
            subject=profile,
            message_id=f"<synthetic-{profile}@example.invalid>",
            body=BODY,
        )
        for profile in PROFILES
    ])
    ingest_mbox(mbox_path, config=config, db_path=db_path, account_key="synthetic")
    for mid, profile in conn.execute("SELECT id, subject FROM messages").fetchall():
        conn.execute(
            "INSERT INTO classifications "
            "(account_id, message_db_id, category_path, export_profile, classifier_type) "
            "VALUES (?, ?, 'synthetic', ?, 'rule')",
            (account_id, mid, profile),
        )
    conn.commit()
    try:
        yield conn, db_path, account_id, config, mbox_path
    finally:
        conn.close()


@pytest.mark.parametrize("include_classification", [False, True])
@pytest.mark.parametrize("override", [None, "raw"])
def test_jsonl_classification_display_flag_does_not_change_content_policy(
    classified_mail, tmp_path, include_classification, override,
):
    conn, _, account_id, config, _ = classified_mail
    config["exports"] = {"jsonl": {"include_classification": include_classification}}
    out = tmp_path / "export" / "messages.jsonl"
    result = export_jsonl(
        conn, config, out, account_id=account_id, account_key="synthetic",
        export_profile=override,
    )
    records = {r["subject"]: r for r in map(json.loads, out.read_text().splitlines())}
    assert all(("classification" in record) == include_classification for record in records.values())
    if override == "raw":
        assert set(records) == set(PROFILES)
        assert all(BODY in record["body_text"] for record in records.values())
        assert result["excluded_message_count"] == 0
    else:
        assert set(records) == set(PROFILES) - {"exclude"}
        assert result["excluded_message_count"] == 1
        assert BODY in records["raw"]["body_text"]
        for profile in ("reviewed", "scrubbed"):
            assert "555-867-5309" not in records[profile]["body_text"]
            assert "[PHONE REDACTED]" in records[profile]["body_text"]
        assert records["metadata-only"]["body_text"] is None
        assert records["metadata-only"]["body_word_count"] is None


@pytest.mark.parametrize("key", [
    "", ".", "..", "../escape", "/absolute", "nested/account", r"nested\account",
    r"C:\escape", "C:escape", "line\nbreak", "trailing.", "trailing ", "NUL",
    "con.txt", "CON .txt", "COM1", "LPT²", "bad*key", "a" * 256, "bad\x7fkey", "bad\u200bkey",
])
def test_unsafe_account_keys_are_rejected_without_creating_identity(tmp_db, key):
    with sqlite3.connect(tmp_db) as conn:
        with pytest.raises(AccountError, match="Unsafe account key"):
            create_account(conn, key)
        assert conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0] == 0


@pytest.mark.parametrize("key", ["primary-gmail", "Family Mail", "archive.2024", "café", "CONTEXT"])
def test_safe_account_keys_preserve_exact_identity(tmp_db, key):
    with sqlite3.connect(tmp_db) as conn:
        create_account(conn, key)
        assert get_account(conn, key)["account_key"] == key


@pytest.mark.parametrize("operation", [
    "jsonl", "notebooklm", "manifest", "attachment-path", "extract", "ingest", "cli-jsonl",
])
def test_unsafe_legacy_account_remains_readable_but_cannot_write_output_paths(
    classified_mail, tmp_path, operation, run_cli,
):
    conn, db_path, account_id, config, mbox_path = classified_mail
    unsafe_key = "../escaped-account"
    conn.execute("UPDATE accounts SET account_key = ? WHERE id = ?", (unsafe_key, account_id))
    conn.commit()
    assert get_account(conn, unsafe_key)["id"] == account_id
    out = tmp_path / "output"
    expected_error = (
        nullcontext() if operation == "cli-jsonl"
        else pytest.raises(AccountError, match="Unsafe account key")
    )
    with expected_error:
        if operation == "jsonl":
            export_jsonl(conn, config, out / "mail.jsonl", account_id=account_id, account_key=unsafe_key)
        elif operation == "notebooklm":
            limits = resolve_notebooklm_limits(load_config())
            export_notebooklm(conn, config, limits, out, account_id=account_id, account_key=unsafe_key)
        elif operation == "manifest":
            write_notebooklm_manifest(out, unsafe_key, [])
        elif operation == "attachment-path":
            attachment_output_path(
                base_dir=out, account_key=unsafe_key, date_str="2024-01-01",
                message_id="synthetic", filename="safe.txt",
            )
        elif operation == "extract":
            message = email.message_from_string(make_attachment_message(
                attachments=[("safe.txt", b"SYNTHETIC", "text/plain")],
            ))
            extract_attachments(
                message, 1, 1, account_key=unsafe_key, attachments_dir=out, conn=conn,
            )
        elif operation == "ingest":
            ingest_mbox(
                mbox_path, config=config, db_path=db_path, account_key=unsafe_key,
                extract_attachments_flag=True,
            )
        else:
            result = run_cli(
                "export", "jsonl", "--db", db_path, "--account", unsafe_key,
                "--out", out / "messages.jsonl",
            )
            assert result.exit_code == 1
            assert "Unsafe account key" in result.stderr
    assert not out.exists()
    assert not (tmp_path / "escaped-account").exists()
    assert not (tmp_path / "attachments").exists()
    assert conn.execute("SELECT COUNT(*) FROM exports").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM ingest_runs").fetchone()[0] == 1
    assert get_account(conn, unsafe_key)["id"] == account_id


@pytest.mark.parametrize(("filename", "expected_manifest"), [
    ("messages.2024.jsonl", "messages.2024.manifest.json"),
    ("messages.2025.jsonl", "messages.2025.manifest.json"),
    ("messages.manifest.json", "messages.manifest.manifest.json"),
])
def test_jsonl_manifest_preserves_output_and_dotted_stem(
    classified_mail, tmp_path, filename, expected_manifest,
):
    conn, _, account_id, config, _ = classified_mail
    out = tmp_path / "export" / filename
    result = export_jsonl(conn, config, out, account_id=account_id, account_key="synthetic")
    manifest_path = Path(result["manifest_path"])
    assert manifest_path != out
    assert manifest_path.name == expected_manifest
    records = list(map(json.loads, out.read_text().splitlines()))
    assert len(records) == result["messages_written"] == 4
    manifest = json.loads(manifest_path.read_text())[0]
    assert manifest["generated_sha256"] == hashlib.sha256(out.read_bytes()).hexdigest()


def test_account_update_preserves_unspecified_fields_and_allows_empty_values(tmp_db):
    with sqlite3.connect(tmp_db) as conn:
        create_account(conn, "synthetic", display_name="Original", email_address="a@example.invalid",
                       notes="unchanged")
        assert update_account(conn, "synthetic", display_name="", email_address="b@example.invalid")
        row = get_account(conn, "synthetic")
        assert row["display_name"] == ""
        assert row["email_address"] == "b@example.invalid"
        assert row["notes"] == "unchanged"
        assert not update_account(conn, "synthetic")
