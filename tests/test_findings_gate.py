from __future__ import annotations

import json
import mailbox
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from mboxer.accounts import create_account
from mboxer.db import init_db
from mboxer.exporters.jsonl import export_jsonl
from mboxer.exporters.notebooklm import export_notebooklm
from mboxer.ingest import ingest_mbox
from mboxer.limits import NotebookLMLimits
from mboxer.security.findings import ResidualFindingsBlocked

PHONE_BODY = "Call us at 555-867-5309 if you have questions."
SSN_BODY = "Your SSN on file is 123-45-6789."
CARD_BODY = "Charge to card 4111 1111 1111 1111 is confirmed."
EMAIL_BODY = "Reply to support@example.org for help."
CLEAN_BODY = "Thank you for your recent purchase. No sensitive info here."

PLANTED_TOKENS = [
    "555-867-5309",
    "123-45-6789",
    "4111 1111 1111 1111",
    "support@example.org",
]

EXPECTED_ALL_COUNTS = {
    "email_address": 1,
    "phone_number": 1,
    "ssn_like": 1,
    "credit_card_like": 1,
}

NLM_LIMITS = NotebookLMLimits(
    profile_name="test",
    max_sources=10,
    reserved_sources=0,
    target_sources=10,
    max_words_per_source=10_000,
    target_words_per_source=5_000,
    max_bytes_per_source=10_000_000,
    target_bytes_per_source=5_000_000,
    max_messages_per_source=100,
)


def _config(
    *,
    profile: str = "raw",
    on_residual_findings: str | None = None,
    redact_email_addresses: bool = True,
    redact_phone_numbers: bool = True,
    redact_ssn_like_numbers: bool = True,
    redact_credit_card_like_numbers: bool = True,
) -> dict[str, Any]:
    security: dict[str, Any] = {
        "default_export_profile": profile,
        "scrub_enabled": True,
        "redact_email_addresses": redact_email_addresses,
        "redact_phone_numbers": redact_phone_numbers,
        "redact_ssn_like_numbers": redact_ssn_like_numbers,
        "redact_credit_card_like_numbers": redact_credit_card_like_numbers,
    }
    if on_residual_findings is not None:
        security["on_residual_findings"] = on_residual_findings
    return {
        "paths": {"attachments_dir": "/tmp/test-findings-gate"},
        "ingest": {"batch_commit_size": 10, "store_body_html": False, "max_body_chars": 50000},
        "security": security,
        "exports": {
            "jsonl": {"include_classification": True},
            "notebooklm": {"format": {"extension": "md"}, "split_strategy": {}},
        },
    }


def _raw_message(subject: str, message_id: str, body: str) -> str:
    return (
        "From: sender@example.com\n"
        "To: user@example.com\n"
        f"Subject: {subject}\n"
        "Date: Mon, 01 Jan 2024 10:00:00 +0000\n"
        f"Message-ID: <{message_id}@example.com>\n"
        "\n"
        f"{body}"
    )


def _make_mbox(path: Path, messages: list[str]) -> None:
    mbox = mailbox.mbox(str(path), create=True)
    for raw in messages:
        mbox.add(mailbox.mboxMessage(raw))
    mbox.flush()
    mbox.close()


def _message_set(bodies: list[str]) -> list[str]:
    return [
        _raw_message(f"Finding gate {index}", f"finding-gate-{index}", body)
        for index, body in enumerate(bodies, start=1)
    ]


def _build_db(tmp_path: Path, account_messages: dict[str, list[str]]) -> Path:
    db_path = tmp_path / "mboxer.sqlite"
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    try:
        for account_key in account_messages:
            create_account(conn, account_key, display_name=account_key.title())
    finally:
        conn.close()

    for account_key, messages in account_messages.items():
        mbox_path = tmp_path / f"{account_key}.mbox"
        _make_mbox(mbox_path, messages)
        ingest_mbox(mbox_path, config=_config(), db_path=db_path, account_key=account_key)
    return db_path


def _account_id(db_path: Path, account_key: str = "test-account") -> int:
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(
            "SELECT id FROM accounts WHERE account_key = ?",
            (account_key,),
        ).fetchone()[0]
    finally:
        conn.close()


def _export_nlm(
    db_path: Path,
    out_dir: Path,
    config: dict[str, Any],
    *,
    account_key: str = "test-account",
    findings_policy: str | None = None,
) -> dict[str, Any]:
    conn = sqlite3.connect(db_path)
    try:
        return export_notebooklm(
            conn,
            config,
            NLM_LIMITS,
            out_dir,
            account_id=_account_id(db_path, account_key),
            account_key=account_key,
            account_display_name=account_key.title(),
            db_path=str(db_path),
            findings_policy=findings_policy,
        )
    finally:
        conn.close()


def _export_jsonl(
    db_path: Path,
    out_path: Path,
    config: dict[str, Any],
    *,
    account_key: str = "test-account",
    findings_policy: str | None = None,
) -> dict[str, Any]:
    conn = sqlite3.connect(db_path)
    try:
        return export_jsonl(
            conn,
            config,
            out_path,
            account_id=_account_id(db_path, account_key),
            account_key=account_key,
            account_display_name=account_key.title(),
            db_path=str(db_path),
            findings_policy=findings_policy,
        )
    finally:
        conn.close()


def _export(
    kind: str,
    db_path: Path,
    tmp_path: Path,
    config: dict[str, Any],
    *,
    account_key: str = "test-account",
    findings_policy: str | None = None,
    suffix: str = "out",
) -> tuple[dict[str, Any], Path]:
    if kind == "notebooklm":
        out_dir = tmp_path / f"nlm-{suffix}"
        return (
            _export_nlm(
                db_path,
                out_dir,
                config,
                account_key=account_key,
                findings_policy=findings_policy,
            ),
            out_dir,
        )
    out_path = tmp_path / f"jsonl-{suffix}" / account_key / "messages.jsonl"
    return (
        _export_jsonl(
            db_path,
            out_path,
            config,
            account_key=account_key,
            findings_policy=findings_policy,
        ),
        out_path,
    )


def _manifest_rows(kind: str, result: dict[str, Any]) -> list[dict[str, Any]]:
    if kind == "notebooklm":
        return json.loads(Path(result["manifest_json"]).read_text())
    return json.loads(Path(result["manifest_path"]).read_text())


def _manifest_text(kind: str, result: dict[str, Any]) -> str:
    if kind == "notebooklm":
        return (
            Path(result["manifest_csv"]).read_text(encoding="utf-8")
            + "\n"
            + Path(result["manifest_json"]).read_text(encoding="utf-8")
        )
    return Path(result["manifest_path"]).read_text(encoding="utf-8")


def _latest_metadata_json(db_path: Path) -> str:
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT metadata_json FROM exports ORDER BY id DESC LIMIT 1"
        ).fetchone()
    finally:
        conn.close()
    return row[0] if row else ""


def _export_count(db_path: Path) -> int:
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute("SELECT COUNT(*) FROM exports").fetchone()[0]
    finally:
        conn.close()


def _assert_no_planted_tokens(text: str) -> None:
    for token in PLANTED_TOKENS:
        assert token not in text


def _assert_manifest_hygiene(kind: str, result: dict[str, Any], db_path: Path) -> None:
    _assert_no_planted_tokens(_manifest_text(kind, result))
    _assert_no_planted_tokens(_latest_metadata_json(db_path))


def _assert_manifest_counts(
    kind: str,
    result: dict[str, Any],
    expected: dict[str, int],
    policy: str,
) -> None:
    rows = _manifest_rows(kind, result)
    assert rows
    for row in rows:
        assert row["residual_scan_performed"] is True
        assert row["residual_findings_total"] == sum(expected.values())
        assert json.loads(row["residual_findings_by_type_json"]) == expected
        assert row["residual_findings_policy"] == policy
        assert json.loads(row["detectors_json"]) == [{"kind": "regex", "name": "regex", "version": 1}]


def _exported_payload(kind: str, out_path: Path) -> str:
    if kind == "notebooklm":
        return "\n".join(path.read_text(encoding="utf-8") for path in sorted(out_path.rglob("*.md")))
    return out_path.read_text(encoding="utf-8")


@pytest.fixture()
def db_all_findings(tmp_path: Path) -> Path:
    return _build_db(
        tmp_path,
        {
            "test-account": _message_set([
                PHONE_BODY,
                SSN_BODY,
                CARD_BODY,
                EMAIL_BODY,
                CLEAN_BODY,
            ])
        },
    )


@pytest.mark.parametrize("kind", ["notebooklm", "jsonl"])
@pytest.mark.parametrize("policy_override", [None, "allow"])
def test_raw_profile_residual_counts_default_and_allow_export(
    tmp_path: Path,
    db_all_findings: Path,
    kind: str,
    policy_override: str | None,
) -> None:
    result, _ = _export(
        kind,
        db_all_findings,
        tmp_path,
        _config(profile="raw"),
        findings_policy=policy_override,
        suffix=f"raw-{policy_override or 'default'}",
    )

    expected_policy = policy_override or "warn"
    assert result["residual_findings"] == EXPECTED_ALL_COUNTS
    assert result["residual_findings_total"] == 4
    assert result["residual_findings_policy"] == expected_policy
    assert bool(result["warnings"]) is (expected_policy == "warn")
    _assert_manifest_counts(kind, result, EXPECTED_ALL_COUNTS, expected_policy)
    _assert_manifest_hygiene(kind, result, db_all_findings)


@pytest.mark.parametrize("kind", ["notebooklm", "jsonl"])
def test_scrubbed_matching_redaction_neutralizes_residuals(
    tmp_path: Path,
    db_all_findings: Path,
    kind: str,
) -> None:
    result, out_path = _export(kind, db_all_findings, tmp_path, _config(profile="scrubbed"))

    assert result["residual_findings"] == {}
    assert result["residual_findings_total"] == 0
    _assert_manifest_counts(kind, result, {}, "warn")
    _assert_manifest_hygiene(kind, result, db_all_findings)
    _assert_no_planted_tokens(_exported_payload(kind, out_path))


@pytest.mark.parametrize("kind", ["notebooklm", "jsonl"])
def test_scrubbed_email_redaction_disabled_leaves_email_residual(
    tmp_path: Path,
    kind: str,
) -> None:
    db_path = _build_db(tmp_path, {"test-account": _message_set([EMAIL_BODY])})
    config = _config(profile="scrubbed", redact_email_addresses=False)
    result, out_path = _export(kind, db_path, tmp_path, config)

    assert result["residual_findings"] == {"email_address": 1}
    assert result["residual_findings_total"] == 1
    assert "support@example.org" in _exported_payload(kind, out_path)
    _assert_manifest_counts(kind, result, {"email_address": 1}, "warn")
    _assert_manifest_hygiene(kind, result, db_path)


@pytest.mark.parametrize("kind", ["notebooklm", "jsonl"])
def test_metadata_only_drops_body_and_residuals(
    tmp_path: Path,
    db_all_findings: Path,
    kind: str,
) -> None:
    result, out_path = _export(kind, db_all_findings, tmp_path, _config(profile="metadata-only"))

    assert result["residual_findings"] == {}
    assert result["residual_findings_total"] == 0
    _assert_manifest_counts(kind, result, {}, "warn")
    _assert_manifest_hygiene(kind, result, db_all_findings)
    _assert_no_planted_tokens(_exported_payload(kind, out_path))


@pytest.mark.parametrize("kind", ["notebooklm", "jsonl"])
def test_block_policy_aborts_pre_write_and_counts_only(
    tmp_path: Path,
    db_all_findings: Path,
    kind: str,
) -> None:
    config = _config(profile="raw")
    out_path = tmp_path / "blocked-nlm" if kind == "notebooklm" else tmp_path / "blocked.jsonl"

    with pytest.raises(ResidualFindingsBlocked) as exc_info:
        if kind == "notebooklm":
            _export_nlm(db_all_findings, out_path, config, findings_policy="block")
        else:
            _export_jsonl(db_all_findings, out_path, config, findings_policy="block")

    assert exc_info.value.counts == EXPECTED_ALL_COUNTS
    _assert_no_planted_tokens(str(exc_info.value))
    assert not out_path.exists()
    assert _export_count(db_all_findings) == 0


@pytest.mark.parametrize("kind", ["notebooklm", "jsonl"])
def test_warn_policy_writes_and_warning_is_counts_only(
    tmp_path: Path,
    db_all_findings: Path,
    kind: str,
) -> None:
    result, out_path = _export(
        kind,
        db_all_findings,
        tmp_path,
        _config(profile="raw"),
        findings_policy="warn",
        suffix="warn",
    )

    assert out_path.exists()
    assert result["residual_findings"] == EXPECTED_ALL_COUNTS
    assert len(result["warnings"]) == 1
    assert result["warnings"][0].startswith("residual detected-sensitive items in export: ")
    for finding_type in EXPECTED_ALL_COUNTS:
        assert finding_type in result["warnings"][0]
    for warning in result["warnings"]:
        _assert_no_planted_tokens(warning)
    _assert_manifest_hygiene(kind, result, db_all_findings)


class _FixedDateTime:
    @classmethod
    def now(cls, tz: timezone | None = None) -> datetime:
        return datetime(2024, 1, 1, 0, 0, 0, tzinfo=tz or timezone.utc)


def _normalized_manifest(kind: str, result: dict[str, Any]) -> list[dict[str, Any]]:
    rows = _manifest_rows(kind, result)
    normalized: list[dict[str, Any]] = []
    for row in rows:
        copy = dict(row)
        copy.pop("created_at", None)
        normalized.append(copy)
    return normalized


def _nlm_output_bytes(out_dir: Path) -> dict[str, bytes]:
    account_dir = out_dir / "test-account"
    return {
        path.relative_to(account_dir).as_posix(): path.read_bytes()
        for path in sorted(account_dir.rglob("*.md"))
    }


@pytest.mark.parametrize("kind", ["notebooklm", "jsonl"])
def test_export_output_and_manifest_are_deterministic(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    db_all_findings: Path,
    kind: str,
) -> None:
    if kind == "notebooklm":
        monkeypatch.setattr("mboxer.exporters.notebooklm.datetime", _FixedDateTime)
    else:
        monkeypatch.setattr("mboxer.exporters.jsonl.datetime", _FixedDateTime)
    config = _config(profile="scrubbed")

    result_a, out_a = _export(kind, db_all_findings, tmp_path, config, suffix="det-a")
    result_b, out_b = _export(kind, db_all_findings, tmp_path, config, suffix="det-b")

    if kind == "notebooklm":
        assert _nlm_output_bytes(out_a) == _nlm_output_bytes(out_b)
    else:
        assert out_a.read_bytes() == out_b.read_bytes()
    assert _normalized_manifest(kind, result_a) == _normalized_manifest(kind, result_b)


@pytest.mark.parametrize("kind", ["notebooklm", "jsonl"])
def test_residual_assessment_is_account_scoped(tmp_path: Path, kind: str) -> None:
    db_path = _build_db(
        tmp_path,
        {
            "clean-account": _message_set([CLEAN_BODY]),
            "leaky-account": _message_set([PHONE_BODY]),
        },
    )

    clean_result, _ = _export(
        kind,
        db_path,
        tmp_path,
        _config(profile="raw"),
        account_key="clean-account",
        findings_policy="allow",
        suffix="clean",
    )
    leaky_result, _ = _export(
        kind,
        db_path,
        tmp_path,
        _config(profile="raw"),
        account_key="leaky-account",
        findings_policy="allow",
        suffix="leaky",
    )

    assert clean_result["residual_findings"] == {}
    assert leaky_result["residual_findings"] == {"phone_number": 1}


def _write_cli_config(tmp_path: Path, policy: str) -> Path:
    path = tmp_path / f"cli-{policy}.yaml"
    path.write_text(
        "\n".join([
            "security:",
            "  default_export_profile: raw",
            "  scrub_enabled: true",
            f"  on_residual_findings: {policy}",
            "exports:",
            "  jsonl:",
            "    include_classification: true",
            "",
        ]),
        encoding="utf-8",
    )
    return path


def test_cli_jsonl_block_exits_counts_only_and_writes_nothing(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    from mboxer.cli import main as cli_main

    db_path = _build_db(tmp_path, {"test-account": _message_set([PHONE_BODY])})
    requested_out_path = tmp_path / "cli" / "messages.jsonl"
    actual_out_path = tmp_path / "cli" / "test-account" / "messages.jsonl"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "mboxer",
            "export",
            "jsonl",
            "--db",
            str(db_path),
            "--config",
            str(_write_cli_config(tmp_path, "warn")),
            "--account",
            "test-account",
            "--out",
            str(requested_out_path),
            "--findings-policy",
            "block",
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        cli_main()

    captured = capsys.readouterr()
    assert exc_info.value.code == 2
    assert "BLOCKED: would export residual detected-sensitive items {'phone_number': 1}" in (
        captured.err
    )
    _assert_no_planted_tokens(captured.err + captured.out)
    assert not requested_out_path.exists()
    assert not actual_out_path.exists()
    assert _export_count(db_path) == 0


def test_cli_jsonl_warn_prints_counts_only(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    from mboxer.cli import main as cli_main

    db_path = _build_db(tmp_path, {"test-account": _message_set([PHONE_BODY])})
    requested_out_path = tmp_path / "cli" / "messages.jsonl"
    actual_out_path = tmp_path / "cli" / "test-account" / "messages.jsonl"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "mboxer",
            "export",
            "jsonl",
            "--db",
            str(db_path),
            "--config",
            str(_write_cli_config(tmp_path, "warn")),
            "--account",
            "test-account",
            "--out",
            str(requested_out_path),
        ],
    )

    cli_main()

    captured = capsys.readouterr()
    assert "WARNING: residual detected-sensitive items in export: {'phone_number': 1}" in (
        captured.out
    )
    _assert_no_planted_tokens(captured.err + captured.out)
    assert actual_out_path.exists()
