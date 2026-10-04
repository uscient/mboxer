"""Long Unicode attachment names must not discard otherwise valid messages."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from mboxer.ingest import ingest_mbox


@pytest.mark.integration
def test_ingest_preserves_messages_with_long_multibyte_attachment_names(
    tmp_db, make_account, config, mime_factory, mbox_factory,
):
    make_account()
    filename = "界" * 120 + ".pdf"
    source = mbox_factory([
        mime_factory(
            message_id="<unicode@example.test>",
            attachments=[
                (filename, b"first", "application/pdf"),
                (filename, b"second", "application/pdf"),
                ("a." + "界" * 100, b"third", "application/octet-stream"),
            ],
        ),
        mime_factory(message_id="<following@example.test>", body="Following message."),
    ])

    result = ingest_mbox(
        source, db_path=tmp_db, config=config, account_key="test-gmail",
        extract_attachments_flag=True,
    )

    assert result["status"] == "completed"
    assert result["inserted"] == 2
    assert result["errors"] == 0
    with sqlite3.connect(tmp_db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 2
        rows = conn.execute(
            "SELECT extraction_status, storage_path FROM attachments ORDER BY id"
        ).fetchall()
        assert conn.execute("SELECT COUNT(*) FROM ingest_errors").fetchone()[0] == 0
    assert [status for status, _ in rows] == ["extracted"] * 3
    paths = [Path(path) for _, path in rows]
    assert [path.read_bytes() for path in paths] == [b"first", b"second", b"third"]
    assert all(len(path.name.encode("utf-8")) <= 255 for path in paths)
