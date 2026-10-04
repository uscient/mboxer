"""Review regressions for source verification and retained export restrictions."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from _factories import make_mbox

import mboxer.classify as classify_module
import mboxer.ingest as ingest_module
from mboxer.exporters.jsonl import export_jsonl
from mboxer.exporters.notebooklm import export_notebooklm
from mboxer.limits import NotebookLMLimits

PROTECTED_ID = "<protected@example.test>"
PROTECTED_BODY = "Protected synthetic custody payload."


def _write_source(path, message_id, subject, references=None):
    path.unlink(missing_ok=True)
    headers = (
        f"From: sender@example.test\nTo: reader@example.test\n"
        f"Message-ID: {message_id}\nSubject: {subject}\n"
    )
    if references:
        headers += f"References: {references}\n"
    body = PROTECTED_BODY if message_id == PROTECTED_ID else "Other synthetic message."
    make_mbox(path, [headers + "\n" + body + "\n"])


def _ingest(path, db, config, **kwargs):
    return ingest_module.ingest_mbox(path, db_path=db, config=config, account_key="test-gmail", **kwargs)


def _export_flags(conn, config, destination, account_id, format_name):
    if format_name == "jsonl":
        path = destination / "messages.jsonl"
        export_jsonl(conn, config, path, account_id=account_id, account_key="test-gmail")
        records = [json.loads(line) for line in path.read_text().splitlines()]
        protected = [record for record in records if record["message_id"] == PROTECTED_ID]
        return bool(protected), bool(protected and protected[0]["body_text"])
    limits = NotebookLMLimits(
        profile_name="test", max_sources=20, reserved_sources=0, target_sources=20,
        max_words_per_source=10000, target_words_per_source=5000,
        max_bytes_per_source=1000000, target_bytes_per_source=500000,
        max_messages_per_source=100,
    )
    export_notebooklm(conn, config, limits, destination, account_id=account_id,
                      account_key="test-gmail", include_unclassified=True)
    text = "\n".join(path.read_text() for path in destination.rglob("*.md"))
    return PROTECTED_ID in text, PROTECTED_BODY in text


@pytest.mark.parametrize("profile", ["exclude", "metadata-only"])
@pytest.mark.parametrize("format_name", ["jsonl", "notebooklm"])
@pytest.mark.parametrize("thread_change", ["join", "leave"])
def test_force_retains_untouched_export_policy_until_successful_reclassification(
    tmp_path, tmp_db, make_account, config, profile, format_name, thread_change,
):
    account_id = make_account()
    config["security"] = {"default_export_profile": "scrubbed", "scrub_enabled": True}
    config["rules"] = [{
        "name": "protected", "match": {"subject_contains": ["Protected"]},
        "assign": {"category_path": "protected", "export_profile": profile},
    }]
    protected_path, changed_path = tmp_path / "protected.mbox", tmp_path / "changed.mbox"
    _write_source(protected_path, PROTECTED_ID, "Protected")
    _write_source(changed_path, "<changed@example.test>", "Other",
                  PROTECTED_ID if thread_change == "leave" else None)
    _ingest(protected_path, tmp_db, config)
    _ingest(changed_path, tmp_db, config)
    expected = (profile != "exclude", False)
    with sqlite3.connect(tmp_db) as conn:
        classify_module.run_rule_classification(conn, config, level="thread", account_id=account_id)
        original_message = conn.execute("SELECT * FROM messages WHERE message_id=?", (PROTECTED_ID,)).fetchone()
        assert _export_flags(conn, config, tmp_path / "before", account_id, format_name) == expected

    _write_source(changed_path, "<replacement@example.test>", "Other",
                  PROTECTED_ID if thread_change == "join" else None)
    assert _ingest(changed_path, tmp_db, config, force=True)["status"] == "completed"
    with sqlite3.connect(tmp_db) as conn:
        assert conn.execute("SELECT * FROM messages WHERE message_id=?", (PROTECTED_ID,)).fetchone() == original_message
        assert conn.execute("SELECT COUNT(*) FROM classifications WHERE target_type='thread' AND thread_key=?", (PROTECTED_ID,)).fetchone() == (0,)
        assert _export_flags(conn, config, tmp_path / "pending", account_id, format_name) == expected

        # No matching rule is not a successful replacement of prior policy.
        unmatched = {**config, "rules": [{"name": "unmatched", "match": {"subject_contains": ["missing"]},
                                         "assign": {"category_path": "other", "export_profile": "raw"}}]}
        classify_module.run_rule_classification(conn, unmatched, level="thread", account_id=account_id)
        assert _export_flags(conn, config, tmp_path / "unmatched", account_id, format_name) == expected

        # An explicit fresh rule result can replace the retained classification.
        config["rules"][0]["assign"].update(category_path="refreshed", export_profile="raw")
        assert classify_module.run_rule_classification(conn, config, level="thread", account_id=account_id)["classified"] == 1
        rows = conn.execute(
            "SELECT category_path,export_profile FROM classifications WHERE message_db_id=? AND classifier_type='rule_inherited'",
            (original_message[0],),
        ).fetchall()
        assert rows == [("refreshed", "raw")]
        assert _export_flags(conn, config, tmp_path / "refreshed", account_id, format_name) == (True, True)


def test_failed_reclassification_restores_previous_inherited_policies(
    tmp_path, tmp_db, make_account, config,
):
    account_id = make_account()
    config["rules"] = [{"name": "protect", "match": {"from_domain": ["example.test"]},
                        "assign": {"category_path": "protected", "export_profile": "exclude"}}]
    protected_path, changed_path = tmp_path / "protected.mbox", tmp_path / "changed.mbox"
    _write_source(protected_path, PROTECTED_ID, "Protected")
    _write_source(changed_path, "<changed@example.test>", "Other")
    _ingest(protected_path, tmp_db, config)
    _ingest(changed_path, tmp_db, config)
    with sqlite3.connect(tmp_db) as conn:
        classify_module.run_rule_classification(conn, config, level="thread", account_id=account_id)
    _write_source(changed_path, "<replacement@example.test>", "Other", PROTECTED_ID)
    _ingest(changed_path, tmp_db, config, force=True)
    config["rules"][0]["assign"]["export_profile"] = "raw"
    with sqlite3.connect(tmp_db) as conn:
        before = conn.execute("SELECT * FROM classifications ORDER BY id").fetchall()
        # Fail after the protected message has already received a fresh policy.
        conn.executescript("""
            CREATE TRIGGER fail_second_inheritance BEFORE INSERT ON classifications
            WHEN NEW.classifier_type='rule_inherited'
              AND NEW.message_db_id=(SELECT id FROM messages WHERE message_id='<replacement@example.test>')
            BEGIN SELECT RAISE(ABORT,'synthetic inheritance failure'); END;
        """)
        with pytest.raises(sqlite3.IntegrityError, match="synthetic inheritance failure"):
            classify_module.run_rule_classification(conn, config, level="thread", account_id=account_id)
        conn.commit()  # The helper must restore policy before returning failure.
        assert conn.execute("SELECT * FROM classifications ORDER BY id").fetchall() == before
        assert _export_flags(conn, config, tmp_path / "failed", account_id, "jsonl") == (False, False)
        conn.execute("DROP TRIGGER fail_second_inheritance")
        assert classify_module.run_rule_classification(conn, config, level="thread", account_id=account_id)["classified"] == 1
        assert _export_flags(conn, config, tmp_path / "retried", account_id, "jsonl") == (True, True)


def test_successful_reclassification_retires_old_inheritance_when_explicit_rule_wins(
    tmp_path, tmp_db, make_account, config,
):
    account_id = make_account()
    config["rules"] = [{"name": "old", "match": {"from_domain": ["example.test"]},
                        "assign": {"category_path": "old", "export_profile": "raw"}}]
    protected_path, changed_path = tmp_path / "protected.mbox", tmp_path / "changed.mbox"
    _write_source(protected_path, PROTECTED_ID, "Protected")
    _write_source(changed_path, "<changed@example.test>", "Other")
    _ingest(protected_path, tmp_db, config)
    _ingest(changed_path, tmp_db, config)
    with sqlite3.connect(tmp_db) as conn:
        classify_module.run_rule_classification(conn, config, level="thread", account_id=account_id)
        protected_id = conn.execute("SELECT id FROM messages WHERE message_id=?", (PROTECTED_ID,)).fetchone()[0]
        conn.execute(
            "INSERT INTO classifications(account_id,target_type,message_db_id,thread_key,category_path,export_profile,classifier_type,confidence) "
            "VALUES(?,'message',?,?,'explicit','exclude','rule_hint',0.75)",
            (account_id, protected_id, PROTECTED_ID),
        )
    _write_source(changed_path, "<replacement@example.test>", "Other", PROTECTED_ID)
    _ingest(changed_path, tmp_db, config, force=True)
    config["rules"] = [{"name": "fresh", "match": {"from_domain": ["example.test"]},
                        "assign_hint": {"category_path": "fresh", "export_profile": "exclude"}}]
    with sqlite3.connect(tmp_db) as conn:
        assert classify_module.run_rule_classification(conn, config, level="thread", account_id=account_id)["classified"] == 1
        assert conn.execute(
            "SELECT classifier_type,confidence,export_profile FROM classifications WHERE message_db_id=?",
            (protected_id,),
        ).fetchall() == [("rule_hint", 0.75, "exclude")]
        assert _export_flags(conn, config, tmp_path / "explicit", account_id, "jsonl") == (False, False)


def test_reclassification_cannot_apply_old_policy_after_concurrent_source_replacement(
    tmp_path, tmp_db, make_account, config, monkeypatch,
):
    account_id = make_account()
    config["rules"] = [
        {"name": subject, "match": {"subject_contains": [subject]},
         "assign": {"category_path": subject.lower(), "export_profile": profile}}
        for subject, profile in (("Public", "raw"), ("Private", "exclude"))
    ]
    source = tmp_path / "source.mbox"
    _write_source(source, PROTECTED_ID, "Public")
    _ingest(source, tmp_db, config)
    original_build = classify_module._build_thread_input

    def replace_after_read(thread_key, messages):
        _write_source(source, PROTECTED_ID, "Private")
        assert _ingest(source, tmp_db, config, force=True)["status"] == "completed"
        return original_build(thread_key, messages)

    with sqlite3.connect(tmp_db) as conn:
        with monkeypatch.context() as patch:
            patch.setattr(classify_module, "_build_thread_input", replace_after_read)
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                classify_module.run_rule_classification(conn, config, level="thread", account_id=account_id)
        conn.commit()
        assert conn.execute("SELECT subject FROM messages").fetchall() == [("Private",)]
        assert conn.execute("SELECT COUNT(*) FROM classifications").fetchone() == (0,)
        assert classify_module.run_rule_classification(conn, config, level="thread", account_id=account_id)["classified"] == 1
        assert conn.execute("SELECT DISTINCT export_profile FROM classifications").fetchall() == [("exclude",)]
        assert _export_flags(conn, config, tmp_path / "current", account_id, "jsonl") == (False, False)


@pytest.mark.parametrize("stage, failure", [
    ("hash", "missing"), ("hash", "permission"), ("stat", "missing"),
    ("hash", "interrupt"), ("stat", "interrupt"),
])
def test_final_source_verification_failure_records_terminal_run_and_preserves_evidence(
    tmp_path, tmp_db, make_account, config, monkeypatch, stage, failure,
):
    make_account()
    path = tmp_path / "source.mbox"
    _write_source(path, "<old@example.test>", "Original")
    _ingest(path, tmp_db, config)
    with sqlite3.connect(tmp_db) as conn:
        old_messages = conn.execute("SELECT * FROM messages").fetchall()
        old_source = conn.execute("SELECT * FROM mbox_sources").fetchall()
    _write_source(path, "<new@example.test>", "Replacement")
    original_hash, original_stat = ingest_module._file_sha256, Path.stat
    hash_calls = 0
    stat_failure_armed = False

    def fail_verification():
        if failure == "missing":
            path.unlink()
        elif failure == "permission":
            raise PermissionError("synthetic private detail must not reach error record")
        else:
            raise KeyboardInterrupt

    def controlled_hash(source, *args, **kwargs):
        nonlocal hash_calls, stat_failure_armed
        hash_calls += 1
        if hash_calls == 2 and stage == "hash":
            fail_verification()
        value = original_hash(source, *args, **kwargs)
        if hash_calls == 2:
            stat_failure_armed = True
        return value

    def controlled_stat(source, *args, **kwargs):
        nonlocal stat_failure_armed
        if source == path and stage == "stat" and stat_failure_armed:
            stat_failure_armed = False
            fail_verification()
        return original_stat(source, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(ingest_module, "_file_sha256", controlled_hash)
        patch.setattr(Path, "stat", controlled_stat)
        result = _ingest(path, tmp_db, config, force=True)
    status = "interrupted" if failure == "interrupt" else "failed"
    assert result["status"] == status
    assert result["inserted"] == result["replaced"] == 0
    assert result["errors"] == (failure != "interrupt")
    with sqlite3.connect(tmp_db) as conn:
        assert conn.execute("SELECT * FROM messages").fetchall() == old_messages
        assert conn.execute("SELECT * FROM mbox_sources").fetchall() == old_source
        run = conn.execute("SELECT status,finished_at,last_mbox_key,errors_count FROM ingest_runs ORDER BY id DESC LIMIT 1").fetchone()
        assert run[0] == status and run[1] is not None and run[2] is None
        assert run[3] == result["errors"]
        errors = conn.execute("SELECT error_type,error_message FROM ingest_errors").fetchall()
        if failure == "interrupt":
            assert errors == []
        else:
            assert errors == [("PermissionError" if failure == "permission" else "FileNotFoundError",
                               "Failed to verify source identity after replacement.")]
