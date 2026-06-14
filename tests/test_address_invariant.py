from __future__ import annotations

import json
import sqlite3
import textwrap
from pathlib import Path

import pytest

from mboxer.accounts import create_account
from mboxer.classify import run_rule_classification
from mboxer.db import init_db
from mboxer.exporters.jsonl import export_jsonl
from mboxer.exporters.notebooklm import export_notebooklm
from mboxer.ingest import ingest_mbox
from mboxer.limits import NotebookLMLimits
from mboxer.records import decode_address_fields, loads_address_list

from _factories import base_config, make_mbox as _make_mbox


MSG_1 = textwrap.dedent("""\
    From: alerts@example.com
    To: user@example.com
    Subject: Address invariant alert
    Date: Mon, 01 Jan 2024 10:00:00 +0000
    Message-ID: <address-invariant-001@example.com>

    Synthetic message body.
""")

MSG_2 = textwrap.dedent("""\
    From: user@example.com
    To: alerts@example.com
    Subject: Re: Address invariant alert
    Date: Mon, 01 Jan 2024 11:00:00 +0000
    Message-ID: <address-invariant-002@example.com>
    In-Reply-To: <address-invariant-001@example.com>

    Synthetic reply body.
""")

CONFIG = base_config(
    security={"default_export_profile": "raw", "scrub_enabled": False},
    rules=[
        {
            "name": "address-invariant-alert",
            "match": {
                "from_domain": ["example.com"],
                "subject_contains": ["address invariant"],
            },
            "assign": {
                "category_path": "system/address-invariant",
                "export_profile": "raw",
            },
        }
    ],
)


def _setup_db(tmp_path: Path, *, suffix: str = "") -> tuple[Path, int, str]:
    account_key = f"account{suffix or '-default'}"
    db_path = tmp_path / f"address{suffix}.sqlite"
    mbox_path = tmp_path / f"address{suffix}.mbox"
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    try:
        account_id = create_account(conn, account_key)
    finally:
        conn.close()
    _make_mbox(mbox_path, [MSG_1, MSG_2])
    ingest_mbox(mbox_path, config=CONFIG, db_path=db_path, account_key=account_key)
    return db_path, account_id, account_key


def _corrupt_recipients_json(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA ignore_check_constraints = ON")
    conn.execute("UPDATE messages SET recipients_json = '{}' WHERE id = (SELECT MIN(id) FROM messages)")
    conn.commit()
    conn.execute("PRAGMA ignore_check_constraints = OFF")


def test_loads_address_list_round_trips_valid_array():
    assert loads_address_list('["one@example.com", "two@example.com"]') == [
        "one@example.com",
        "two@example.com",
    ]


@pytest.mark.parametrize("value", ["not json", "{}", '"x"', '["ok@example.com", 3]'])
def test_loads_address_list_raises_on_invalid_values(value: str):
    with pytest.raises((json.JSONDecodeError, TypeError, ValueError)):
        loads_address_list(value)


def test_decode_address_fields_replaces_json_fields_with_lists():
    record = {
        "id": 1,
        "recipients_json": '["to@example.com"]',
        "cc_json": "[]",
        "bcc_json": '["hidden@example.com"]',
    }

    decoded = decode_address_fields(record)

    assert decoded is record
    assert decoded["recipients"] == ["to@example.com"]
    assert decoded["cc"] == []
    assert decoded["bcc"] == ["hidden@example.com"]
    assert "recipients_json" not in decoded
    assert "cc_json" not in decoded
    assert "bcc_json" not in decoded


def test_classify_raises_on_corrupt_recipients_json(tmp_path):
    db_path, account_id, _account_key = _setup_db(tmp_path, suffix="-classify")
    conn = sqlite3.connect(db_path)
    try:
        _corrupt_recipients_json(conn)
        with pytest.raises(ValueError, match="address-list JSON must be an array"):
            run_rule_classification(conn, CONFIG, account_id=account_id)
    finally:
        conn.close()


def test_jsonl_export_raises_on_corrupt_recipients_json(tmp_path):
    db_path, account_id, account_key = _setup_db(tmp_path, suffix="-jsonl")
    conn = sqlite3.connect(db_path)
    try:
        _corrupt_recipients_json(conn)
        with pytest.raises(ValueError, match="address-list JSON must be an array"):
            export_jsonl(
                conn,
                CONFIG,
                tmp_path / "messages.jsonl",
                account_id=account_id,
                account_key=account_key,
            )
    finally:
        conn.close()


@pytest.mark.parametrize("level", ["message", "thread"])
def test_ingest_classify_and_exports_end_to_end_with_address_lists(tmp_path, level: str):
    db_path, account_id, account_key = _setup_db(tmp_path, suffix=f"-{level}")
    conn = sqlite3.connect(db_path)
    try:
        classify_result = run_rule_classification(conn, CONFIG, level=level, account_id=account_id)
        assert classify_result["classified"] >= 1

        out_path = tmp_path / f"{level}.jsonl"
        jsonl_result = export_jsonl(
            conn,
            CONFIG,
            out_path,
            account_id=account_id,
            account_key=account_key,
        )
        records = [json.loads(line) for line in out_path.read_text().splitlines()]
        assert jsonl_result["messages_written"] == 2
        assert records[0]["recipients"] == ["user@example.com"]
        assert records[0]["cc"] == []
        assert records[0]["bcc"] == []

        limits = NotebookLMLimits(
            profile_name="test",
            max_sources=10,
            reserved_sources=0,
            target_sources=10,
            max_words_per_source=100000,
            target_words_per_source=50000,
            max_bytes_per_source=1_000_000,
            target_bytes_per_source=500_000,
            max_messages_per_source=100,
        )
        notebook_result = export_notebooklm(
            conn,
            CONFIG,
            limits,
            tmp_path / f"notebook-{level}",
            account_id=account_id,
            account_key=account_key,
            include_unclassified=False,
            db_path=str(db_path),
        )
        assert notebook_result["messages_exported"] >= 1
    finally:
        conn.close()
