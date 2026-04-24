import mailbox
import sqlite3
import textwrap
from pathlib import Path

import pytest
from mboxer.accounts import create_account
from mboxer.db import init_db
from mboxer.ingest import ingest_mbox


def _make_mbox(path: Path, messages: list[str]) -> None:
    mbox = mailbox.mbox(str(path), create=True)
    for raw in messages:
        mbox.add(mailbox.mboxMessage(raw))
    mbox.flush()
    mbox.close()


SIMPLE_MSG = textwrap.dedent("""\
    From: sender@example.com
    To: recipient@example.com
    Subject: Hello World
    Date: Mon, 1 Jan 2024 12:00:00 +0000
    Message-ID: <test-001@example.com>

    This is the body of the email.
""")

REPLY_MSG = textwrap.dedent("""\
    From: recipient@example.com
    To: sender@example.com
    Subject: Re: Hello World
    Date: Mon, 1 Jan 2024 13:00:00 +0000
    Message-ID: <test-002@example.com>
    In-Reply-To: <test-001@example.com>

    Thanks for your message.
""")

GMAIL_MSG = textwrap.dedent("""\
    From: news@example.com
    To: user@example.com
    Subject: Newsletter
    Date: Tue, 2 Jan 2024 10:00:00 +0000
    Message-ID: <news-001@example.com>
    X-Gmail-Labels: Inbox,Important,newsletter

    Here is the newsletter.
""")


@pytest.fixture()
def config(tmp_path):
    return {
        "paths": {"attachments_dir": str(tmp_path / "attachments")},
        "ingest": {"batch_commit_size": 10, "store_body_html": False, "max_body_chars": 50000},
    }


@pytest.fixture()
def db_with_account(tmp_path):
    db_path = tmp_path / "mboxer.sqlite"
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    create_account(conn, "test-gmail", display_name="Test Gmail")
    conn.close()
    return db_path


def test_ingest_creates_messages(tmp_path, config, db_with_account):
    mbox_path = tmp_path / "test.mbox"
    _make_mbox(mbox_path, [SIMPLE_MSG, REPLY_MSG])
    counts = ingest_mbox(mbox_path, config=config, db_path=db_with_account, account_key="test-gmail")
    assert counts["inserted"] == 2
    assert counts["errors"] == 0


def test_ingest_idempotent(tmp_path, config, db_with_account):
    mbox_path = tmp_path / "test.mbox"
    _make_mbox(mbox_path, [SIMPLE_MSG])
    ingest_mbox(mbox_path, config=config, db_path=db_with_account, account_key="test-gmail")
    counts2 = ingest_mbox(mbox_path, config=config, db_path=db_with_account, account_key="test-gmail")
    assert counts2["inserted"] == 0
    assert counts2["skipped"] == 1


def test_ingest_creates_completed_run(tmp_path, config, db_with_account):
    mbox_path = tmp_path / "test.mbox"
    _make_mbox(mbox_path, [SIMPLE_MSG])
    ingest_mbox(mbox_path, config=config, db_path=db_with_account, account_key="test-gmail")
    conn = sqlite3.connect(db_with_account)
    row = conn.execute("SELECT status FROM ingest_runs").fetchone()
    conn.close()
    assert row[0] == "completed"


def test_ingest_threads_populated(tmp_path, config, db_with_account):
    mbox_path = tmp_path / "test.mbox"
    _make_mbox(mbox_path, [SIMPLE_MSG, REPLY_MSG])
    ingest_mbox(mbox_path, config=config, db_path=db_with_account, account_key="test-gmail")
    conn = sqlite3.connect(db_with_account)
    thread_count = conn.execute("SELECT COUNT(*) FROM threads").fetchone()[0]
    conn.close()
    assert thread_count >= 1


def test_ingest_gmail_labels_stored(tmp_path, config, db_with_account):
    mbox_path = tmp_path / "test.mbox"
    _make_mbox(mbox_path, [GMAIL_MSG])
    ingest_mbox(mbox_path, config=config, db_path=db_with_account, account_key="test-gmail")
    conn = sqlite3.connect(db_with_account)
    label_count = conn.execute("SELECT COUNT(*) FROM labels").fetchone()[0]
    ml_count = conn.execute("SELECT COUNT(*) FROM message_labels").fetchone()[0]
    conn.close()
    assert label_count == 3   # Inbox, Important, newsletter
    assert ml_count == 3


def test_ingest_missing_file(tmp_path, config, db_with_account):
    with pytest.raises(FileNotFoundError):
        ingest_mbox(tmp_path / "nonexistent.mbox", config=config, db_path=db_with_account,
                    account_key="test-gmail")


def test_ingest_unknown_account_raises(tmp_path, config, db_with_account):
    mbox_path = tmp_path / "test.mbox"
    _make_mbox(mbox_path, [SIMPLE_MSG])
    from mboxer.accounts import AccountError
    with pytest.raises(AccountError, match="not found"):
        ingest_mbox(mbox_path, config=config, db_path=db_with_account, account_key="ghost-account")


def test_ingest_create_account_flag(tmp_path, config):
    db_path = tmp_path / "test.sqlite"
    init_db(db_path)
    mbox_path = tmp_path / "test.mbox"
    _make_mbox(mbox_path, [SIMPLE_MSG])
    counts = ingest_mbox(mbox_path, config=config, db_path=db_path,
                         account_key="new-gmail", create_account_if_missing=True)
    assert counts["inserted"] == 1

    conn = sqlite3.connect(db_path)
    from mboxer.accounts import get_account
    assert get_account(conn, "new-gmail") is not None
    conn.close()


def test_same_message_id_different_accounts(tmp_path, config):
    """The same Message-ID must be allowed under separate accounts."""
    db_path = tmp_path / "test.sqlite"
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    create_account(conn, "dad-gmail")
    create_account(conn, "personal-gmail")
    conn.close()

    mbox1 = tmp_path / "dad.mbox"
    mbox2 = tmp_path / "personal.mbox"
    _make_mbox(mbox1, [SIMPLE_MSG])
    _make_mbox(mbox2, [SIMPLE_MSG])

    c1 = ingest_mbox(mbox1, config=config, db_path=db_path, account_key="dad-gmail")
    c2 = ingest_mbox(mbox2, config=config, db_path=db_path, account_key="personal-gmail")

    assert c1["inserted"] == 1
    assert c2["inserted"] == 1

    conn = sqlite3.connect(db_path)
    total = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
    conn.close()
    assert total == 2
