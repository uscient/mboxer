"""Competing classification policies must resolve before export publication.

All mail is generated in temporary directories. These tests use the public
exporters so the same contract applies to buffered and streaming implementations.
"""
from __future__ import annotations

import email
import json
import sqlite3

import pytest
from _factories import make_attachment_message, make_mbox

from mboxer.accounts import create_account
from mboxer.classify import run_rule_classification
from mboxer.config import ConfigError, load_config
from mboxer.exporters.classification import ExportPolicyConflict, resolve_message_classification
from mboxer.exporters.jsonl import export_jsonl
from mboxer.exporters.notebooklm import export_notebooklm
from mboxer.ingest import ingest_mbox
from mboxer.limits import resolve_notebooklm_limits

EXPORTERS = ("jsonl-hidden", "jsonl-shown", "notebooklm")
BODY = "Synthetic body marker ALPHA-ONLY."
OTHER_BODY = "Synthetic body marker BETA-ONLY."


def _message(*, body=BODY, subject="Synthetic policy message", message_id="policy-1",
             sender="sender@example.invalid", reply_to=None):
    message = email.message_from_string(make_attachment_message(
        subject=subject,
        sender=sender,
        to="recipient@example.invalid",
        message_id=f"<{message_id}@example.invalid>",
        body=body,
    ))
    if reply_to:
        message["In-Reply-To"] = f"<{reply_to}@example.invalid>"
        message["References"] = f"<{reply_to}@example.invalid>"
    return message.as_string()


@pytest.fixture
def policy_mail(tmp_db, tmp_path):
    config = load_config()
    config["security"].update(default_export_profile="raw", on_residual_findings="allow")
    conn = sqlite3.connect(tmp_db)
    account_id = create_account(conn, "synthetic-policy")
    path = tmp_path / "mail.mbox"
    make_mbox(path, [_message()])
    ingest_mbox(path, config=config, db_path=tmp_db, account_key="synthetic-policy")
    message_id = conn.execute("SELECT id FROM messages").fetchone()[0]
    try:
        yield conn, config, account_id, message_id, tmp_db
    finally:
        conn.close()


def _classify(conn, account_id, message_id, profile, confidence, classifier_type="rule",
              *, category="synthetic/policy"):
    conn.execute(
        "INSERT INTO classifications "
        "(account_id, target_type, message_db_id, category_path, export_profile, "
        "confidence, classifier_type, classifier_name) "
        "VALUES (?, 'message', ?, ?, ?, ?, ?, 'synthetic-classifier-marker')",
        (account_id, message_id, category, profile, confidence, classifier_type),
    )
    conn.commit()


def _export(conn, config, output, exporter, account_id, *, override=None):
    if exporter.startswith("jsonl"):
        config["exports"]["jsonl"]["include_classification"] = exporter == "jsonl-shown"
        return export_jsonl(
            conn, config, output / "messages.jsonl", account_id=account_id,
            account_key="synthetic-policy", export_profile=override,
        )
    return export_notebooklm(
        conn, config, resolve_notebooklm_limits(config), output,
        account_id=account_id, account_key="synthetic-policy", export_profile=override,
    )


def _content(output, exporter):
    if exporter.startswith("jsonl"):
        return (output / "messages.jsonl").read_text()
    return "\n".join(path.read_text() for path in sorted(output.rglob("*.md")))


def _written(result, exporter):
    return result["messages_written" if exporter.startswith("jsonl") else "messages_exported"]


def _assert_counts(conn, result, exporter, candidates, excluded, written):
    assert result["candidate_message_count"] == candidates
    assert result["excluded_message_count"] == excluded
    assert _written(result, exporter) == written
    message_count, metadata_json = conn.execute(
        "SELECT message_count, metadata_json FROM exports ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert message_count == written
    metadata = json.loads(metadata_json)
    assert metadata["candidate_message_count"] == candidates
    assert metadata["excluded_message_count"] == excluded


@pytest.mark.parametrize("exporter", EXPORTERS)
@pytest.mark.parametrize("reverse_messages", [False, True])
def test_thread_inheritance_replaces_weaker_message_policy(
    policy_mail, tmp_path, exporter, reverse_messages,
):
    conn, config, account_id, _, db_path = policy_mail
    # Use a fresh source/thread: the restrictive participant only joins in reply.
    messages = [
        _message(message_id="thread-start", subject="Synthetic thread", body=BODY),
        _message(message_id="thread-reply", subject="Re: Synthetic thread", body=OTHER_BODY,
                 sender="sender@restricted.invalid", reply_to="thread-start"),
    ]
    path = tmp_path / "thread.mbox"
    make_mbox(path, list(reversed(messages)) if reverse_messages else messages)
    ingest_mbox(path, config=config, db_path=db_path, account_key="synthetic-policy")
    config["rules"] = [
        {"name": "restrictive-participant", "match": {"from_domain": ["restricted.invalid"]},
         "assign": {"category_path": "synthetic/restricted", "export_profile": "exclude"}},
        {"name": "weak-subject-hint", "match": {"subject_contains": ["synthetic thread"]},
         "assign_hint": {"category_path": "synthetic/hint", "export_profile": "raw"}},
    ]
    run_rule_classification(conn, config, level="message", account_id=account_id)
    run_rule_classification(conn, config, level="thread", account_id=account_id)
    first_id = conn.execute(
        "SELECT id FROM messages WHERE message_id = '<thread-start@example.invalid>'"
    ).fetchone()[0]
    evidence = conn.execute(
        "SELECT classifier_type, export_profile, confidence FROM classifications "
        "WHERE message_db_id = ? ORDER BY id", (first_id,),
    ).fetchall()
    assert evidence == [("rule_hint", "raw", 0.75), ("rule_inherited", "exclude", 1.0)]
    output = tmp_path / "export"
    result = _export(conn, config, output, exporter, account_id)
    # The unrelated original message remains; the two thread messages are excluded.
    _assert_counts(conn, result, exporter, candidates=3, excluded=2, written=1)
    assert OTHER_BODY not in _content(output, exporter)
    if exporter.startswith("jsonl"):
        records = [json.loads(line) for line in _content(output, exporter).splitlines()]
        assert [record["message_id"] for record in records] == ["<policy-1@example.invalid>"]
    else:
        assert "<thread-start@example.invalid>" not in _content(output, exporter)
    assert conn.execute(
        "SELECT classifier_type, export_profile, confidence FROM classifications "
        "WHERE message_db_id = ? ORDER BY id", (first_id,),
    ).fetchall() == evidence


@pytest.mark.parametrize("exporter", EXPORTERS)
@pytest.mark.parametrize("reverse_rows", [False, True])
@pytest.mark.parametrize("winner_type,winner_confidence,loser_type,loser_confidence", [
    ("rule", 0.75, "rule_inherited", 0.75),
    ("rule_hint", 0.75, "rule_inherited", 0.75),
    ("rule_inherited", 1.0, "rule_hint", 0.75),
    ("rule", -1.0, "rule", None),
])
def test_confidence_then_explicit_rule_rank_is_independent_of_insertion_order(
    policy_mail, tmp_path, exporter, reverse_rows,
    winner_type, winner_confidence, loser_type, loser_confidence,
):
    conn, config, account_id, message_id, _ = policy_mail
    rows = [("metadata-only", winner_confidence, winner_type),
            ("raw", loser_confidence, loser_type)]
    for profile, confidence, kind in reversed(rows) if reverse_rows else rows:
        _classify(conn, account_id, message_id, profile, confidence, kind)
    output = tmp_path / "export"
    result = _export(conn, config, output, exporter, account_id)
    _assert_counts(conn, result, exporter, candidates=1, excluded=0, written=1)
    assert BODY not in _content(output, exporter)
    if exporter.startswith("jsonl"):
        record = json.loads(_content(output, exporter))
        assert record["body_text"] is None
        assert ("classification" in record) == (exporter == "jsonl-shown")
        if exporter == "jsonl-shown":
            assert record["classification"]["classifier_type"] == winner_type
            assert record["classification"]["export_profile"] == "metadata-only"


@pytest.mark.parametrize("exporter", EXPORTERS)
@pytest.mark.parametrize("reverse_rows", [False, True])
def test_conflicting_winning_policies_preserve_prior_files_and_export_history(
    policy_mail, tmp_path, exporter, reverse_rows,
):
    conn, config, account_id, message_id, db_path = policy_mail
    _classify(conn, account_id, message_id, "raw", 1.0)
    path = tmp_path / "second.mbox"
    make_mbox(path, [_message(message_id="policy-2", subject="Synthetic conflict subject",
                             body=OTHER_BODY)])
    ingest_mbox(path, config=config, db_path=db_path, account_key="synthetic-policy")
    second_id = conn.execute("SELECT MAX(id) FROM messages").fetchone()[0]
    output = tmp_path / "export"
    _export(conn, config, output, exporter, account_id)
    before_files = {path.relative_to(output): path.read_bytes()
                    for path in output.rglob("*") if path.is_file()}
    before_exports = conn.execute("SELECT * FROM exports ORDER BY id").fetchall()
    before_items = conn.execute("SELECT * FROM export_items ORDER BY id").fetchall()
    for profile in ("exclude", "raw") if reverse_rows else ("raw", "exclude"):
        _classify(conn, account_id, second_id, profile, 1.0,
                  category="synthetic/private-category-marker")
    before_classifications = conn.execute("SELECT * FROM classifications ORDER BY id").fetchall()
    with pytest.raises(ConfigError) as raised:
        _export(conn, config, output, exporter, account_id)
    error = str(raised.value)
    assert error
    for marker in (BODY, OTHER_BODY, "Synthetic conflict subject", "sender@example.invalid",
                   "private-category-marker", "synthetic-classifier-marker", "policy-2"):
        assert marker not in error
    assert {path.relative_to(output): path.read_bytes()
            for path in output.rglob("*") if path.is_file()} == before_files
    assert conn.execute("SELECT * FROM exports ORDER BY id").fetchall() == before_exports
    assert conn.execute("SELECT * FROM export_items ORDER BY id").fetchall() == before_items
    assert conn.execute("SELECT * FROM classifications ORDER BY id").fetchall() == before_classifications


@pytest.mark.parametrize("exporter", EXPORTERS)
def test_explicit_raw_override_resolves_competing_policy_content(policy_mail, tmp_path, exporter):
    conn, config, account_id, message_id, _ = policy_mail
    _classify(conn, account_id, message_id, "exclude", 1.0)
    _classify(conn, account_id, message_id, "raw", 1.0)
    output = tmp_path / "export"
    result = _export(conn, config, output, exporter, account_id, override="raw")
    _assert_counts(conn, result, exporter, candidates=1, excluded=0, written=1)
    assert _content(output, exporter).count(BODY) == 1


@pytest.mark.parametrize("exporter", EXPORTERS)
@pytest.mark.parametrize("first_profile", [None, "unrecognized-legacy-profile", "raw"])
def test_equal_rank_equivalent_effective_policies_export_once(
    policy_mail, tmp_path, exporter, first_profile,
):
    conn, config, account_id, message_id, _ = policy_mail
    _classify(conn, account_id, message_id, first_profile, 1.0, category="synthetic/first")
    _classify(conn, account_id, message_id, "raw", 1.0, category="synthetic/second")
    output = tmp_path / "export"
    result = _export(conn, config, output, exporter, account_id)
    _assert_counts(conn, result, exporter, candidates=1, excluded=0, written=1)
    assert _content(output, exporter).count(BODY) == 1
    if exporter == "jsonl-shown":
        assert json.loads(_content(output, exporter))["classification"]["category_path"] == "synthetic/first"
    elif exporter == "notebooklm":
        assert "category: synthetic/first" in _content(output, exporter)
        assert "category: synthetic/second" not in _content(output, exporter)


@pytest.mark.parametrize("exporter", EXPORTERS)
def test_legacy_single_classification_without_confidence_keeps_policy(policy_mail, tmp_path, exporter):
    conn, config, account_id, message_id, _ = policy_mail
    _classify(conn, account_id, message_id, "metadata-only", None)
    output = tmp_path / "export"
    result = _export(conn, config, output, exporter, account_id)
    _assert_counts(conn, result, exporter, candidates=1, excluded=0, written=1)
    assert BODY not in _content(output, exporter)


@pytest.mark.parametrize("exporter", EXPORTERS)
@pytest.mark.parametrize("all_accounts", [False, True])
@pytest.mark.parametrize("has_own_classification", [False, True])
def test_classification_account_must_match_owning_message(
    policy_mail, tmp_path, exporter, all_accounts, has_own_classification,
):
    conn, config, account_id, message_id, db_path = policy_mail
    other_id = create_account(conn, "other-synthetic")
    other_path = tmp_path / "other.mbox"
    # Same RFC Message-ID in a different account is still a different message.
    make_mbox(other_path, [_message(body=OTHER_BODY)])
    ingest_mbox(other_path, config=config, db_path=db_path, account_key="other-synthetic")
    other_message_id = conn.execute(
        "SELECT id FROM messages WHERE account_id = ?", (other_id,),
    ).fetchone()[0]
    if has_own_classification:
        _classify(conn, account_id, message_id, "raw", 0.75)
    _classify(conn, other_id, message_id, "exclude", 1.0, category="synthetic/mismatched")
    _classify(conn, other_id, other_message_id, "exclude", 1.0)
    output = tmp_path / "export"
    result = _export(conn, config, output, exporter, None if all_accounts else account_id)
    _assert_counts(conn, result, exporter, candidates=2 if all_accounts else 1,
                   excluded=1 if all_accounts else 0, written=1)
    assert _content(output, exporter).count(BODY) == 1
    assert OTHER_BODY not in _content(output, exporter)
    assert "synthetic/mismatched" not in _content(output, exporter)


@pytest.mark.parametrize("exporter", EXPORTERS)
@pytest.mark.parametrize("reverse_rows", [False, True])
def test_lower_rank_policy_conflict_does_not_override_clear_winner(
    policy_mail, tmp_path, exporter, reverse_rows,
):
    conn, config, account_id, message_id, _ = policy_mail
    rows = [("raw", 0.5), ("exclude", 0.5), ("metadata-only", 1.0)]
    for profile, confidence in reversed(rows) if reverse_rows else rows:
        _classify(conn, account_id, message_id, profile, confidence)
    output = tmp_path / "export"
    result = _export(conn, config, output, exporter, account_id)
    _assert_counts(conn, result, exporter, candidates=1, excluded=0, written=1)
    assert BODY not in _content(output, exporter)


@pytest.mark.parametrize("exporter", EXPORTERS)
def test_missing_profile_uses_config_default_when_checking_conflicts(policy_mail, tmp_path, exporter):
    conn, config, account_id, message_id, _ = policy_mail
    config["security"]["default_export_profile"] = "exclude"
    _classify(conn, account_id, message_id, None, None)
    _classify(conn, account_id, message_id, "raw", None)
    output = tmp_path / "export"
    with pytest.raises(ExportPolicyConflict):
        _export(conn, config, output, exporter, account_id)
    assert not output.exists()
    assert conn.execute("SELECT COUNT(*) FROM exports").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM export_items").fetchone()[0] == 0


@pytest.mark.parametrize("confidence", [float("inf"), float("-inf"), "synthetic-invalid-confidence"])
def test_invalid_confidence_cannot_silently_choose_an_export_policy(policy_mail, confidence):
    conn, _, account_id, message_id, _ = policy_mail
    _classify(conn, account_id, message_id, "raw", confidence)
    with pytest.raises(ExportPolicyConflict) as raised:
        resolve_message_classification(conn, message_id, "raw")
    assert "synthetic-invalid-confidence" not in str(raised.value)


@pytest.mark.parametrize("exporter", EXPORTERS)
@pytest.mark.parametrize("override", ["TYPO", ""])
def test_invalid_override_cannot_erase_conflicting_policies(policy_mail, tmp_path, exporter, override):
    conn, config, account_id, message_id, _ = policy_mail
    _classify(conn, account_id, message_id, "raw", 1.0)
    _classify(conn, account_id, message_id, "exclude", 1.0)
    output = tmp_path / "export"
    with pytest.raises(ConfigError):
        _export(conn, config, output, exporter, account_id, override=override)
    assert not output.exists()
    assert conn.execute("SELECT COUNT(*) FROM exports").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM export_items").fetchone()[0] == 0


def test_notebooklm_dry_run_preserves_pending_caller_transaction(policy_mail, tmp_path):
    conn, config, account_id, message_id, _ = policy_mail
    _classify(conn, account_id, message_id, "raw", 1.0)
    conn.execute("UPDATE messages SET body_text = ? WHERE id = ?", (OTHER_BODY, message_id))
    assert conn.in_transaction
    output = tmp_path / "export"
    result = export_notebooklm(
        conn, config, resolve_notebooklm_limits(config), output,
        account_id=account_id, account_key="synthetic-policy", dry_run=True,
    )
    assert result["candidate_message_count"] == 1
    assert result["would_write"] == 1
    assert conn.in_transaction
    assert conn.execute("SELECT body_text FROM messages WHERE id = ?", (message_id,)).fetchone()[0] == OTHER_BODY
    assert conn.execute("SELECT COUNT(*) FROM exports").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM export_items").fetchone()[0] == 0
    assert not output.exists()
    conn.rollback()
    assert conn.execute("SELECT body_text FROM messages WHERE id = ?", (message_id,)).fetchone()[0].strip() == BODY
