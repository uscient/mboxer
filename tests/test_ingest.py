import hashlib
import mailbox
import sqlite3
import textwrap
from email.message import EmailMessage
from pathlib import Path

import pytest
import mboxer.ingest as ingest_module
from mboxer.accounts import create_account
from mboxer.db import init_db
from mboxer.ingest import ingest_mbox

from _factories import make_mbox as _make_mbox


def _remake_mbox(path: Path, messages: list[str]) -> None:
    """Overwrite an existing mbox file with fresh content (truncates first)."""
    path.unlink(missing_ok=True)
    _make_mbox(path, messages)


ATTACHMENT_PAYLOAD = b"synthetic attachment payload"


def _make_attachment_mbox(path: Path) -> None:
    msg = EmailMessage()
    msg["From"] = "sender@example.com"
    msg["To"] = "recipient@example.com"
    msg["Subject"] = "Attachment Boundary"
    msg["Date"] = "Thu, 4 Jan 2024 10:00:00 +0000"
    msg["Message-ID"] = "<attachment-001@example.com>"
    msg.set_content("Message body for attachment metadata boundary.")
    msg.add_attachment(
        ATTACHMENT_PAYLOAD,
        maintype="application",
        subtype="octet-stream",
        filename="evidence.bin",
    )

    mbox = mailbox.mbox(str(path), create=True)
    mbox.add(mailbox.mboxMessage(msg))
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


def test_source_record_reused_and_hash_tracks_content_with_force(tmp_path, config, db_with_account):
    mbox_path = tmp_path / "test.mbox"
    _make_mbox(mbox_path, [SIMPLE_MSG])

    ingest_mbox(mbox_path, config=config, db_path=db_with_account, account_key="test-gmail")
    conn = sqlite3.connect(db_with_account)
    source_before = conn.execute(
        "SELECT id, file_size, file_sha256 FROM mbox_sources"
    ).fetchone()
    conn.close()

    expected_hash = hashlib.sha256(mbox_path.read_bytes()).hexdigest()
    assert source_before[1] == mbox_path.stat().st_size
    assert source_before[2] == expected_hash

    ingest_mbox(mbox_path, config=config, db_path=db_with_account, account_key="test-gmail")
    conn = sqlite3.connect(db_with_account)
    sources_after_rerun = conn.execute(
        "SELECT id, file_sha256 FROM mbox_sources ORDER BY id"
    ).fetchall()
    conn.close()
    assert sources_after_rerun == [(source_before[0], expected_hash)]

    _remake_mbox(mbox_path, [MODIFIED_MSG])
    changed_hash = hashlib.sha256(mbox_path.read_bytes()).hexdigest()
    assert changed_hash != expected_hash

    with pytest.raises(RuntimeError, match="Source MBOX content hash changed"):
        ingest_mbox(mbox_path, config=config, db_path=db_with_account, account_key="test-gmail")

    counts = ingest_mbox(
        mbox_path,
        config=config,
        db_path=db_with_account,
        account_key="test-gmail",
        force=True,
    )
    assert counts["inserted"] == 1
    assert counts["replaced"] == 1

    conn = sqlite3.connect(db_with_account)
    source_after_force = conn.execute(
        "SELECT id, file_sha256 FROM mbox_sources"
    ).fetchone()
    source_count = conn.execute("SELECT COUNT(*) FROM mbox_sources").fetchone()[0]
    conn.close()
    assert source_count == 1
    assert source_after_force == (source_before[0], changed_hash)


def test_ingest_creates_completed_run(tmp_path, config, db_with_account):
    mbox_path = tmp_path / "test.mbox"
    _make_mbox(mbox_path, [SIMPLE_MSG])
    ingest_mbox(mbox_path, config=config, db_path=db_with_account, account_key="test-gmail")
    conn = sqlite3.connect(db_with_account)
    row = conn.execute("SELECT status FROM ingest_runs").fetchone()
    conn.close()
    assert row[0] == "completed"


def test_completed_run_records_counts_checkpoint_without_raw_body(tmp_path, config, db_with_account):
    mbox_path = tmp_path / "test.mbox"
    _make_mbox(mbox_path, [SIMPLE_MSG, REPLY_MSG])

    ingest_mbox(mbox_path, config=config, db_path=db_with_account, account_key="test-gmail")

    conn = sqlite3.connect(db_with_account)
    row = conn.execute(
        """
        SELECT status, finished_at, last_mbox_key, messages_seen, messages_inserted,
               messages_skipped, errors_count
        FROM ingest_runs
        ORDER BY id DESC
        LIMIT 1
        """
    ).fetchone()
    conn.close()

    assert row[0] == "completed"
    assert row[1] is not None
    assert row[2] == "1"
    assert row[3:] == (2, 2, 0, 0)
    assert "This is the body of the email" not in " ".join(str(value) for value in row)


def test_normalization_errors_store_safe_evidence(tmp_path, config, db_with_account, monkeypatch):
    mbox_path = tmp_path / "test.mbox"
    _make_mbox(mbox_path, [SIMPLE_MSG])

    def fail_normalize(*_args, **_kwargs):
        raise RuntimeError("leaked body: This is the body of the email.")

    monkeypatch.setattr(ingest_module, "normalize_message", fail_normalize)

    counts = ingest_module.ingest_mbox(
        mbox_path,
        config=config,
        db_path=db_with_account,
        account_key="test-gmail",
    )

    assert counts["inserted"] == 0
    assert counts["errors"] == 1

    conn = sqlite3.connect(db_with_account)
    row = conn.execute(
        "SELECT mbox_key, error_type, error_message FROM ingest_errors"
    ).fetchone()
    run = conn.execute(
        "SELECT status, errors_count FROM ingest_runs"
    ).fetchone()
    conn.close()

    assert row[0] == "0"
    assert row[1] == "RuntimeError"
    assert "This is the body of the email" not in row[2]
    assert "leaked body" not in row[2]
    assert run == ("completed", 1)


def test_resume_invalid_checkpoint_restarts_without_duplicates(tmp_path, config, db_with_account):
    mbox_path = tmp_path / "test.mbox"
    _make_mbox(mbox_path, [SIMPLE_MSG, REPLY_MSG])
    ingest_mbox(mbox_path, config=config, db_path=db_with_account, account_key="test-gmail")

    conn = sqlite3.connect(db_with_account)
    account_id, source_id = conn.execute(
        "SELECT account_id, id FROM mbox_sources"
    ).fetchone()
    conn.execute("DELETE FROM messages WHERE mbox_key = '1'")
    conn.execute(
        """
        INSERT INTO ingest_runs
          (account_id, source_id, status, last_mbox_key, messages_seen, messages_inserted)
        VALUES (?, ?, 'interrupted', 'missing-key', 1, 1)
        """,
        (account_id, source_id),
    )
    conn.commit()
    conn.close()

    counts = ingest_mbox(
        mbox_path,
        config=config,
        db_path=db_with_account,
        account_key="test-gmail",
        resume=True,
    )

    assert counts["inserted"] == 1
    assert counts["skipped"] == 1
    assert counts["errors"] == 1

    conn = sqlite3.connect(db_with_account)
    keys = conn.execute("SELECT mbox_key FROM messages ORDER BY mbox_key").fetchall()
    resume_error = conn.execute(
        "SELECT error_type, error_message FROM ingest_errors ORDER BY id DESC LIMIT 1"
    ).fetchone()
    run = conn.execute(
        """
        SELECT status, last_mbox_key, messages_seen, messages_inserted,
               messages_skipped, errors_count
        FROM ingest_runs
        ORDER BY id DESC
        LIMIT 1
        """
    ).fetchone()
    conn.close()

    assert keys == [("0",), ("1",)]
    assert resume_error[0] == "InvalidResumeCheckpoint"
    assert "missing-key" in resume_error[1]
    assert run == ("completed", "1", 2, 1, 1, 1)


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


# ---------------------------------------------------------------------------
# --force tests
# ---------------------------------------------------------------------------

MODIFIED_MSG = textwrap.dedent("""\
    From: sender@example.com
    To: recipient@example.com
    Subject: Hello World
    Date: Mon, 1 Jan 2024 12:00:00 +0000
    Message-ID: <test-001@example.com>

    This body has been updated.
""")

LABELED_MSG = textwrap.dedent("""\
    From: news@example.com
    To: user@example.com
    Subject: Force Label Test
    Date: Wed, 3 Jan 2024 09:00:00 +0000
    Message-ID: <force-label-001@example.com>
    X-Gmail-Labels: Inbox,Starred

    Body for label force test.
""")


def test_duplicate_skips_without_force(tmp_path, config, db_with_account):
    mbox_path = tmp_path / "test.mbox"
    _make_mbox(mbox_path, [SIMPLE_MSG])
    ingest_mbox(mbox_path, config=config, db_path=db_with_account, account_key="test-gmail")
    counts2 = ingest_mbox(mbox_path, config=config, db_path=db_with_account, account_key="test-gmail")
    assert counts2["inserted"] == 0
    assert counts2["skipped"] == 1
    conn = sqlite3.connect(db_with_account)
    total = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
    conn.close()
    assert total == 1


def test_force_replaces_existing_message(tmp_path, config, db_with_account):
    mbox_path = tmp_path / "test.mbox"
    _make_mbox(mbox_path, [SIMPLE_MSG])
    ingest_mbox(mbox_path, config=config, db_path=db_with_account, account_key="test-gmail")

    conn = sqlite3.connect(db_with_account)
    original_hash = conn.execute("SELECT body_hash FROM messages").fetchone()[0]
    conn.close()

    # Replace mbox with modified body at the same position (key=0).
    _remake_mbox(mbox_path, [MODIFIED_MSG])
    counts2 = ingest_mbox(
        mbox_path, config=config, db_path=db_with_account,
        account_key="test-gmail", force=True,
    )

    assert counts2["inserted"] == 1
    assert counts2["replaced"] == 1

    conn = sqlite3.connect(db_with_account)
    total = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
    new_hash = conn.execute("SELECT body_hash FROM messages").fetchone()[0]
    conn.close()

    assert total == 1
    assert new_hash != original_hash


def test_force_is_account_scoped(tmp_path, config):
    """Force-reingest of account A must not touch account B's messages."""
    db_path = tmp_path / "test.sqlite"
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    create_account(conn, "acct-alpha")
    create_account(conn, "acct-beta")
    conn.close()

    mbox_a = tmp_path / "alpha.mbox"
    mbox_b = tmp_path / "beta.mbox"
    _make_mbox(mbox_a, [SIMPLE_MSG])
    _make_mbox(mbox_b, [SIMPLE_MSG])

    ingest_mbox(mbox_a, config=config, db_path=db_path, account_key="acct-alpha")
    ingest_mbox(mbox_b, config=config, db_path=db_path, account_key="acct-beta")

    conn = sqlite3.connect(db_path)
    beta_id = conn.execute(
        "SELECT m.id FROM messages m JOIN accounts a ON m.account_id = a.id "
        "WHERE a.account_key = 'acct-beta'"
    ).fetchone()[0]
    conn.close()

    # Force-reingest alpha with a modified message.
    _remake_mbox(mbox_a, [MODIFIED_MSG])
    ingest_mbox(mbox_a, config=config, db_path=db_path, account_key="acct-alpha", force=True)

    conn = sqlite3.connect(db_path)
    total = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
    still_beta = conn.execute("SELECT id FROM messages WHERE id = ?", (beta_id,)).fetchone()
    conn.close()

    assert total == 2
    assert still_beta is not None


def test_force_is_source_scoped(tmp_path, config, db_with_account):
    """Force-reingest of source A must not touch messages from source B."""
    mbox1 = tmp_path / "source1.mbox"
    mbox2 = tmp_path / "source2.mbox"
    _make_mbox(mbox1, [SIMPLE_MSG])
    _make_mbox(mbox2, [REPLY_MSG])

    ingest_mbox(mbox1, config=config, db_path=db_with_account, account_key="test-gmail")
    ingest_mbox(mbox2, config=config, db_path=db_with_account, account_key="test-gmail")

    conn = sqlite3.connect(db_with_account)
    src2_msg_id = conn.execute(
        "SELECT m.id FROM messages m JOIN mbox_sources s ON m.source_id = s.id "
        "WHERE s.file_path LIKE '%source2%'"
    ).fetchone()[0]
    conn.close()

    _remake_mbox(mbox1, [MODIFIED_MSG])
    ingest_mbox(mbox1, config=config, db_path=db_with_account, account_key="test-gmail", force=True)

    conn = sqlite3.connect(db_with_account)
    total = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
    still_src2 = conn.execute("SELECT id FROM messages WHERE id = ?", (src2_msg_id,)).fetchone()
    conn.close()

    assert total == 2
    assert still_src2 is not None


def test_force_replaces_dependent_message_labels(tmp_path, config, db_with_account):
    mbox_path = tmp_path / "test.mbox"
    _make_mbox(mbox_path, [LABELED_MSG])
    ingest_mbox(mbox_path, config=config, db_path=db_with_account, account_key="test-gmail")

    conn = sqlite3.connect(db_with_account)
    ml_before = conn.execute("SELECT COUNT(*) FROM message_labels").fetchone()[0]
    conn.close()
    assert ml_before == 2  # Inbox, Starred

    _remake_mbox(mbox_path, [LABELED_MSG])
    ingest_mbox(
        mbox_path, config=config, db_path=db_with_account,
        account_key="test-gmail", force=True,
    )

    conn = sqlite3.connect(db_with_account)
    ml_after = conn.execute("SELECT COUNT(*) FROM message_labels").fetchone()[0]
    msg_count = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
    conn.close()

    assert msg_count == 1
    assert ml_after == 2


def test_force_replaces_dependent_classifications(tmp_path, config, db_with_account):
    mbox_path = tmp_path / "test.mbox"
    _make_mbox(mbox_path, [SIMPLE_MSG])
    ingest_mbox(mbox_path, config=config, db_path=db_with_account, account_key="test-gmail")

    conn = sqlite3.connect(db_with_account)
    msg_id = conn.execute("SELECT id FROM messages").fetchone()[0]
    conn.execute(
        "INSERT INTO classifications "
        "(account_id, target_type, message_db_id, category_path, classifier_type) "
        "VALUES (1, 'message', ?, 'test/category', 'rule')",
        (msg_id,),
    )
    conn.commit()
    clf_before = conn.execute(
        "SELECT COUNT(*) FROM classifications WHERE target_type = 'message'"
    ).fetchone()[0]
    conn.close()
    assert clf_before == 1

    _remake_mbox(mbox_path, [MODIFIED_MSG])
    ingest_mbox(
        mbox_path, config=config, db_path=db_with_account,
        account_key="test-gmail", force=True,
    )

    conn = sqlite3.connect(db_with_account)
    clf_after = conn.execute(
        "SELECT COUNT(*) FROM classifications WHERE target_type = 'message'"
    ).fetchone()[0]
    conn.close()

    assert clf_after == 0


def test_force_replaces_message_level_export_and_security_evidence(tmp_path, config, db_with_account):
    mbox_path = tmp_path / "test.mbox"
    _make_mbox(mbox_path, [SIMPLE_MSG])
    ingest_mbox(mbox_path, config=config, db_path=db_with_account, account_key="test-gmail")

    conn = sqlite3.connect(db_with_account)
    msg_id = conn.execute("SELECT id FROM messages").fetchone()[0]
    conn.execute(
        """
        INSERT INTO exports (account_id, export_type, export_profile, output_path, status)
        VALUES (1, 'jsonl', 'scrubbed', 'synthetic.jsonl', 'completed')
        """
    )
    export_id = conn.execute("SELECT id FROM exports").fetchone()[0]
    conn.execute(
        """
        INSERT INTO export_items (account_id, export_id, output_file, message_db_id, sequence)
        VALUES (1, ?, 'synthetic.jsonl', ?, 1)
        """,
        (export_id, msg_id),
    )
    conn.execute(
        """
        INSERT INTO security_findings
          (account_id, target_type, message_db_id, finding_type, severity, detector)
        VALUES (1, 'message', ?, 'synthetic', 'low', 'test')
        """,
        (msg_id,),
    )
    conn.commit()
    conn.close()

    _remake_mbox(mbox_path, [MODIFIED_MSG])
    ingest_mbox(
        mbox_path,
        config=config,
        db_path=db_with_account,
        account_key="test-gmail",
        force=True,
    )

    conn = sqlite3.connect(db_with_account)
    export_items = conn.execute("SELECT COUNT(*) FROM export_items").fetchone()[0]
    findings = conn.execute("SELECT COUNT(*) FROM security_findings").fetchone()[0]
    export_runs = conn.execute("SELECT COUNT(*) FROM exports").fetchone()[0]
    conn.close()

    assert export_items == 0
    assert findings == 0
    assert export_runs == 1


def test_force_thread_classification_preserved(tmp_path, config, db_with_account):
    """Thread-level classifications are NOT deleted on force; re-classify refreshes them."""
    mbox_path = tmp_path / "test.mbox"
    _make_mbox(mbox_path, [SIMPLE_MSG])
    ingest_mbox(mbox_path, config=config, db_path=db_with_account, account_key="test-gmail")

    conn = sqlite3.connect(db_with_account)
    thread_key = conn.execute("SELECT thread_key FROM messages").fetchone()[0]
    conn.execute(
        "INSERT INTO classifications "
        "(account_id, target_type, thread_key, category_path, classifier_type) "
        "VALUES (1, 'thread', ?, 'test/thread-category', 'rule')",
        (thread_key,),
    )
    conn.commit()
    conn.close()

    _remake_mbox(mbox_path, [MODIFIED_MSG])
    ingest_mbox(
        mbox_path, config=config, db_path=db_with_account,
        account_key="test-gmail", force=True,
    )

    conn = sqlite3.connect(db_with_account)
    thread_clf = conn.execute(
        "SELECT COUNT(*) FROM classifications WHERE target_type = 'thread'"
    ).fetchone()[0]
    conn.close()

    assert thread_clf == 1


def test_normal_ingest_idempotent_after_force(tmp_path, config, db_with_account):
    """After a force-ingest, a subsequent normal ingest still skips duplicates."""
    mbox_path = tmp_path / "test.mbox"
    _make_mbox(mbox_path, [SIMPLE_MSG])
    ingest_mbox(mbox_path, config=config, db_path=db_with_account,
                account_key="test-gmail", force=True)
    counts = ingest_mbox(mbox_path, config=config, db_path=db_with_account, account_key="test-gmail")
    assert counts["inserted"] == 0
    assert counts["skipped"] == 1


def test_attachment_metadata_boundary_excludes_payload_from_ingest_evidence(
    tmp_path, config, db_with_account
):
    mbox_path = tmp_path / "attachment.mbox"
    _make_attachment_mbox(mbox_path)

    ingest_mbox(
        mbox_path,
        config=config,
        db_path=db_with_account,
        account_key="test-gmail",
        extract_attachments_flag=True,
    )

    conn = sqlite3.connect(db_with_account)
    attachment = conn.execute(
        """
        SELECT safe_filename, content_type, size_bytes, sha256, storage_path,
               extraction_status, error_message
        FROM attachments
        """
    ).fetchone()
    run_rows = conn.execute("SELECT * FROM ingest_runs").fetchall()
    source_rows = conn.execute("SELECT * FROM mbox_sources").fetchall()
    error_rows = conn.execute("SELECT * FROM ingest_errors").fetchall()
    message_rows = conn.execute("SELECT body_text, raw_headers_json FROM messages").fetchall()
    conn.close()

    expected_hash = hashlib.sha256(ATTACHMENT_PAYLOAD).hexdigest()
    assert attachment[0] == "evidence.bin"
    assert attachment[1] == "application/octet-stream"
    assert attachment[2] == len(ATTACHMENT_PAYLOAD)
    assert attachment[3] == expected_hash
    assert attachment[4] is not None
    assert Path(attachment[4]).exists()
    assert attachment[5] == "extracted"
    assert attachment[6] is None

    payload_text = ATTACHMENT_PAYLOAD.decode("utf-8")
    evidence_text = "\n".join(
        str(value)
        for rows in (run_rows, source_rows, error_rows, message_rows)
        for row in rows
        for value in row
    )
    assert payload_text not in evidence_text
