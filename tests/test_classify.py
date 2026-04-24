import sqlite3
import textwrap
import mailbox
from pathlib import Path

from mboxer.accounts import create_account
from mboxer.classify import run_rule_classification
from mboxer.db import init_db
from mboxer.ingest import ingest_mbox


USPS_MSG = textwrap.dedent("""\
    From: auto-reply@usps.com
    To: user@example.com
    Subject: Your Informed Delivery Daily Digest
    Date: Mon, 1 Jan 2024 08:00:00 +0000
    Message-ID: <usps-001@usps.com>

    Here are your mail pieces for today.
""")

UNMATCHED_MSG = textwrap.dedent("""\
    From: friend@example.com
    To: user@example.com
    Subject: Catching up
    Date: Tue, 2 Jan 2024 10:00:00 +0000
    Message-ID: <friend-001@example.com>

    How are things?
""")

CONFIG = {
    "paths": {"attachments_dir": "/tmp/attachments"},
    "ingest": {"batch_commit_size": 10, "store_body_html": False, "max_body_chars": 50000},
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


def test_rule_classification(tmp_path):
    db_path = tmp_path / "test.sqlite"
    mbox_path = tmp_path / "test.mbox"
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    create_account(conn, "test-gmail")
    conn.close()

    _make_mbox(mbox_path, [USPS_MSG, UNMATCHED_MSG])
    ingest_mbox(mbox_path, config=CONFIG, db_path=db_path, account_key="test-gmail")

    conn = sqlite3.connect(db_path)
    try:
        account_id = conn.execute("SELECT id FROM accounts WHERE account_key = 'test-gmail'").fetchone()[0]
        result = run_rule_classification(conn, CONFIG, account_id=account_id)
        assert result["classified"] == 1
        row = conn.execute(
            "SELECT category_path FROM classifications WHERE classifier_type = 'rule'"
        ).fetchone()
        assert row[0] == "postal/usps-informed-delivery"
    finally:
        conn.close()


def test_classification_is_account_scoped(tmp_path):
    """Classifications for account A must not bleed into account B's results."""
    db_path = tmp_path / "test.sqlite"
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    create_account(conn, "dad-gmail")
    create_account(conn, "personal-gmail")
    conn.close()

    mbox_a = tmp_path / "dad.mbox"
    mbox_b = tmp_path / "personal.mbox"
    _make_mbox(mbox_a, [USPS_MSG])
    _make_mbox(mbox_b, [USPS_MSG])

    ingest_mbox(mbox_a, config=CONFIG, db_path=db_path, account_key="dad-gmail")
    ingest_mbox(mbox_b, config=CONFIG, db_path=db_path, account_key="personal-gmail")

    conn = sqlite3.connect(db_path)
    try:
        dad_id = conn.execute("SELECT id FROM accounts WHERE account_key = 'dad-gmail'").fetchone()[0]
        run_rule_classification(conn, CONFIG, account_id=dad_id)

        dad_count = conn.execute(
            "SELECT COUNT(*) FROM classifications WHERE account_id = ?", (dad_id,)
        ).fetchone()[0]
        personal_id = conn.execute(
            "SELECT id FROM accounts WHERE account_key = 'personal-gmail'"
        ).fetchone()[0]
        personal_count = conn.execute(
            "SELECT COUNT(*) FROM classifications WHERE account_id = ?", (personal_id,)
        ).fetchone()[0]
        assert dad_count == 1
        assert personal_count == 0
    finally:
        conn.close()
