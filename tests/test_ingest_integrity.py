"""Behavioral regressions for custody, failed writes, and source replacement."""
from __future__ import annotations

import hashlib
import mailbox
import sqlite3
from contextlib import closing
from email.message import EmailMessage

import pytest

import mboxer.ingest as ingest_module
from mboxer.classify import run_rule_classification


def _write(path, subjects, *, id_prefix="message", reply_to=None):
    path.unlink(missing_ok=True)
    with closing(mailbox.mbox(str(path))) as box:
        for i, subject in enumerate(subjects):
            msg = EmailMessage()
            msg["From"] = "sender@example.test"
            msg["To"] = "reader@example.test"
            msg["Message-ID"] = f"<{id_prefix}-{i}@example.test>"
            if reply_to:
                msg["References"] = reply_to
            msg["Subject"] = subject
            msg["X-Gmail-Labels"] = "Example"
            msg.set_content(f"Synthetic body: {subject}")
            box.add(msg)


def _run(path, db, config, **kwargs):
    return ingest_module.ingest_mbox(path, db_path=db, config=config, account_key="test-gmail", **kwargs)


def _rows(db, sql):
    with sqlite3.connect(db) as conn:
        return conn.execute(sql).fetchall()


def test_same_archive_path_is_independent_per_account(tmp_path, tmp_db, make_account, config):
    make_account()
    make_account("other")
    path = tmp_path / "source.mbox"
    _write(path, ["Original"])
    _run(path, tmp_db, config)
    ingest_module.ingest_mbox(path, db_path=tmp_db, config=config, account_key="other")
    _write(path, ["Replacement"])
    _run(path, tmp_db, config, force=True)
    assert _rows(tmp_db, "SELECT a.account_key, m.subject FROM messages m JOIN accounts a ON a.id=m.account_id ORDER BY a.account_key") == [
        ("other", "Original"), ("test-gmail", "Replacement"),
    ]


def test_force_shrink_removes_missing_keys_and_rebuilds_threads(tmp_path, tmp_db, make_account, config):
    make_account()
    path = tmp_path / "source.mbox"
    _write(path, ["Original", "Removed"])
    _run(path, tmp_db, config)
    _write(path, ["Replacement"])
    counts = _run(path, tmp_db, config, force=True)
    assert counts["errors"] == 0
    assert _rows(tmp_db, "SELECT mbox_key, subject FROM messages") == [("0", "Replacement")]
    assert _rows(tmp_db, "SELECT message_count, subject FROM threads") == [(1, "Replacement")]


@pytest.mark.parametrize("failure", ["normalize", "labels", "insert", "interrupt"])
def test_force_failure_preserves_original_evidence_and_identity(
    tmp_path, tmp_db, make_account, config, monkeypatch, failure,
):
    make_account()
    path = tmp_path / "source.mbox"
    _write(path, ["Original"])
    _run(path, tmp_db, config)
    old_messages = _rows(tmp_db, "SELECT * FROM messages")
    old_sources = _rows(tmp_db, "SELECT * FROM mbox_sources")
    _write(path, ["Replacement"])
    with monkeypatch.context() as patch:
        if failure == "insert":
            with sqlite3.connect(tmp_db) as conn:
                conn.executescript("CREATE TRIGGER injected_failure BEFORE INSERT ON messages BEGIN SELECT RAISE(ABORT, 'injected failure'); END;")
        else:
            def fail(*_args, **_kwargs):
                if failure == "interrupt":
                    raise KeyboardInterrupt
                raise RuntimeError("injected failure")
            patch.setattr(ingest_module, "normalize_message" if failure == "normalize" else "_store_labels", fail)
        counts = _run(path, tmp_db, config, force=True)
    assert counts["inserted"] == counts["replaced"] == 0
    assert _rows(tmp_db, "SELECT * FROM messages") == old_messages
    assert _rows(tmp_db, "SELECT * FROM mbox_sources") == old_sources
    assert _rows(tmp_db, "SELECT status, last_mbox_key FROM ingest_runs ORDER BY id DESC LIMIT 1") == [
        ("interrupted" if failure == "interrupt" else "failed", None),
    ]
    with pytest.raises(ingest_module.SourceIdentityError):
        _run(path, tmp_db, config)


def test_partial_message_failure_can_be_retried(tmp_path, tmp_db, make_account, config, monkeypatch):
    make_account()
    path = tmp_path / "source.mbox"
    _write(path, ["Labelled"])
    with monkeypatch.context() as patch:
        def fail(*_args, **_kwargs):
            raise RuntimeError("injected label failure")
        patch.setattr(ingest_module, "_store_labels", fail)
        counts = _run(path, tmp_db, config)
    assert counts["inserted"] == 0 and counts["errors"] == 1
    assert _rows(tmp_db, "SELECT COUNT(*) FROM messages") == [(0,)]
    assert _rows(tmp_db, "SELECT COUNT(*) FROM threads") == [(0,)]
    assert _run(path, tmp_db, config)["inserted"] == 1
    assert _rows(tmp_db, "SELECT COUNT(*) FROM message_labels") == [(1,)]


def test_resume_retries_failure_before_successful_checkpoint(tmp_path, tmp_db, make_account, config, monkeypatch):
    make_account()
    path = tmp_path / "source.mbox"
    _write(path, ["Retry", "Saved", "Interrupted"])
    normalize = ingest_module.normalize_message
    def injected(msg, source_id, key, account_id):
        if key == "0":
            raise ValueError("injected read failure")
        if key == "2":
            raise KeyboardInterrupt
        return normalize(msg, source_id, key, account_id)
    with monkeypatch.context() as patch:
        patch.setattr(ingest_module, "normalize_message", injected)
        _run(path, tmp_db, config)
    assert _rows(tmp_db, "SELECT last_mbox_key FROM ingest_runs") == [(None,)]
    _run(path, tmp_db, config, resume=True)
    assert _rows(tmp_db, "SELECT mbox_key FROM messages ORDER BY mbox_key") == [("0",), ("1",), ("2",)]


def test_force_does_not_resume_checkpoint_from_previous_content(tmp_path, tmp_db, make_account, config):
    make_account()
    path = tmp_path / "source.mbox"
    _write(path, ["Old A", "Old B"])
    _run(path, tmp_db, config)
    with sqlite3.connect(tmp_db) as conn:
        conn.execute("UPDATE ingest_runs SET status='interrupted', last_mbox_key='0'")
    _write(path, ["New A", "New B"])
    _run(path, tmp_db, config, force=True, resume=True)
    assert _rows(tmp_db, "SELECT subject FROM messages ORDER BY mbox_key") == [("New A",), ("New B",)]


def test_force_reclassifies_affected_threads_and_preserves_other_account(
    tmp_path, tmp_db, make_account, config,
):
    account_id = make_account()
    other_id = make_account("other")
    config["rules"] = [
        {"name": word, "match": {"subject_contains": [word]},
         "assign": {"category_path": word.lower()}}
        for word in ("Old", "New")
    ]
    path = tmp_path / "source.mbox"
    other_source = tmp_path / "other-source.mbox"
    _write(path, ["Old"])
    _write(other_source, ["Old"])
    _run(path, tmp_db, config)
    _run(other_source, tmp_db, config)
    ingest_module.ingest_mbox(path, db_path=tmp_db, config=config, account_key="other")
    with sqlite3.connect(tmp_db) as conn:
        run_rule_classification(conn, config, level="thread", account_id=account_id)
        run_rule_classification(conn, config, level="thread", account_id=other_id)
        original_other = conn.execute("SELECT * FROM classifications WHERE account_id=?", (other_id,)).fetchall()
    _write(path, ["New"])
    _run(path, tmp_db, config, force=True)
    with sqlite3.connect(tmp_db) as conn:
        assert conn.execute("SELECT * FROM classifications WHERE account_id=?", (other_id,)).fetchall() == original_other
        assert conn.execute("SELECT COUNT(*) FROM classifications WHERE account_id=? AND target_type='thread'", (account_id,)).fetchone() == (0,)
        assert conn.execute("SELECT COUNT(*) FROM classifications WHERE account_id=? AND classifier_type='rule_inherited'", (account_id,)).fetchone() == (1,)
        # The surviving second source is still present and joins the new thread
        # classification; it is not left with an inherited stale result.
        assert run_rule_classification(conn, config, level="thread", account_id=account_id)["classified"] == 1
        assert conn.execute("SELECT COUNT(*) FROM messages WHERE account_id=?", (account_id,)).fetchone() == (2,)
        assert conn.execute("SELECT COUNT(*) FROM classifications WHERE account_id=? AND classifier_type='rule_inherited'", (account_id,)).fetchone() == (2,)


def test_html_retained_and_truncated_body_metadata_matches_storage(tmp_path, tmp_db, make_account, config):
    make_account()
    path = tmp_path / "html.mbox"
    msg = EmailMessage()
    msg.set_content("<p>Synthetic HTML body</p>", subtype="html")
    with closing(mailbox.mbox(str(path))) as box:
        box.add(msg)
    config["ingest"].update(store_body_html=True, max_body_chars=10)
    _run(path, tmp_db, config)
    body, html, digest, size, words = _rows(tmp_db, "SELECT body_text,body_html,body_hash,body_chars,body_word_count FROM messages")[0]
    assert "<p>" in html
    assert len(body) == size == 10
    assert digest == hashlib.sha256(body.encode()).hexdigest()
    assert words == len(body.split())


def test_inline_filename_attachment_is_extracted(tmp_path, tmp_db, make_account, config):
    make_account()
    path = tmp_path / "inline.mbox"
    msg = EmailMessage()
    msg.set_content("Synthetic body")
    msg.add_attachment(b"synthetic bytes", maintype="image", subtype="png", disposition="inline", filename="image.png")
    with closing(mailbox.mbox(str(path))) as box:
        box.add(msg)
    _run(path, tmp_db, config, extract_attachments_flag=True)
    assert _rows(tmp_db, "SELECT attachment_count FROM messages") == [(1,)]
    assert _rows(tmp_db, "SELECT extraction_status FROM attachments") == [("extracted",)]


def test_force_into_existing_thread_refreshes_inherited_classification(tmp_path, tmp_db, make_account, config):
    account_id = make_account()
    config["rules"] = [{"name": "example", "match": {"from_domain": ["example.test"]},
                        "assign": {"category_path": "example"}}]
    first, second = tmp_path / "first.mbox", tmp_path / "second.mbox"
    _write(first, ["Original"], id_prefix="old")
    _write(second, ["Existing"])
    _run(first, tmp_db, config)
    _run(second, tmp_db, config)
    with sqlite3.connect(tmp_db) as conn:
        assert run_rule_classification(conn, config, level="thread", account_id=account_id)["classified"] == 2
    _write(first, ["Joined"], id_prefix="new", reply_to="<message-0@example.test>")
    _run(first, tmp_db, config, force=True)
    with sqlite3.connect(tmp_db) as conn:
        assert run_rule_classification(conn, config, level="thread", account_id=account_id)["classified"] == 1
        assert conn.execute("SELECT COUNT(*) FROM classifications WHERE classifier_type='rule_inherited'").fetchone() == (2,)


def test_force_attachment_insert_failure_cleans_new_payload_only(tmp_path, tmp_db, make_account, config):
    make_account()
    path = tmp_path / "attachments.mbox"
    msg = EmailMessage()
    msg.set_content("Synthetic body")
    msg.add_attachment(b"synthetic payload", maintype="application", subtype="octet-stream", filename="sample.bin")
    with closing(mailbox.mbox(str(path))) as box:
        box.add(msg)
    _run(path, tmp_db, config, extract_attachments_flag=True)
    attachment_dir = tmp_path / "attachments"
    original_files = {file: file.read_bytes() for file in attachment_dir.rglob("*") if file.is_file()}
    with sqlite3.connect(tmp_db) as conn:
        # Also exercise deletion of findings linked only through attachment_id.
        conn.execute("INSERT INTO security_findings(account_id,target_type,attachment_id,finding_type,severity,detector) SELECT account_id,'attachment',id,'synthetic','low','test' FROM attachments")
        conn.executescript("CREATE TRIGGER injected_attachment_failure BEFORE INSERT ON attachments BEGIN SELECT RAISE(ABORT, 'injected failure'); END;")
    result = _run(path, tmp_db, config, force=True, extract_attachments_flag=True)
    assert result["status"] == "failed"
    assert {file: file.read_bytes() for file in attachment_dir.rglob("*") if file.is_file()} == original_files
    assert _rows(tmp_db, "SELECT COUNT(*) FROM attachments") == [(1,)]
    assert _rows(tmp_db, "SELECT COUNT(*) FROM security_findings") == [(1,)]
    with sqlite3.connect(tmp_db) as conn:
        conn.execute("DROP TRIGGER injected_attachment_failure")
    assert _run(path, tmp_db, config, force=True, extract_attachments_flag=True)["errors"] == 0
    assert _rows(tmp_db, "SELECT COUNT(*) FROM security_findings") == [(0,)]


def test_force_detects_source_change_during_replacement(tmp_path, tmp_db, make_account, config, monkeypatch):
    make_account()
    path = tmp_path / "source.mbox"
    _write(path, ["Original"])
    _run(path, tmp_db, config)
    _write(path, ["Replacement"])
    normalize = ingest_module.normalize_message
    def change_source(*args):
        record = normalize(*args)
        with path.open("ab") as handle:
            handle.write(b"source changed during ingest\n")
        return record
    monkeypatch.setattr(ingest_module, "normalize_message", change_source)
    assert _run(path, tmp_db, config, force=True)["status"] == "failed"
    assert _rows(tmp_db, "SELECT subject FROM messages") == [("Original",)]


@pytest.mark.parametrize("interrupted,exit_code", [(False, 1), (True, 130)])
def test_cli_ingest_reports_failure_exit_code(tmp_path, cli_config, run_cli, monkeypatch, interrupted, exit_code):
    path = tmp_path / "source.mbox"
    _write(path, ["Original"])
    assert run_cli("account", "add", "test-gmail", "--config", cli_config).exit_code == 0
    assert run_cli("ingest", path, "--config", cli_config).exit_code == 0
    def fail(*args, **kwargs):
        if interrupted:
            raise KeyboardInterrupt
        raise ValueError("synthetic normalization failure")
    monkeypatch.setattr(ingest_module, "normalize_message", fail)
    result = run_cli("ingest", path, "--config", cli_config, "--force")
    assert result.exit_code == exit_code
    assert "previous source evidence retained" in result.stdout


def test_ingest_run_update_rejects_unknown_column(tmp_db):
    with sqlite3.connect(tmp_db) as conn, pytest.raises(ValueError, match="Unsupported"):
        ingest_module._update_run(conn, 1, unexpected="value")


@pytest.mark.parametrize("setting,value", [("batch_commit_size", 0), ("max_body_chars", -1)])
def test_invalid_ingest_limits_rejected_before_evidence_write(tmp_path, tmp_db, make_account, config, setting, value):
    make_account()
    path = tmp_path / "source.mbox"
    _write(path, ["Original"])
    config["ingest"][setting] = value
    with pytest.raises(ValueError, match="batch_commit_size"):
        _run(path, tmp_db, config)
    assert _rows(tmp_db, "SELECT COUNT(*) FROM messages") == [(0,)]
