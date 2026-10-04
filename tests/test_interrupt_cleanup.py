"""Interruptions unwind incomplete evidence while retaining completed work."""
from __future__ import annotations

import email
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

import mboxer.ingest as ingest_module
from mboxer.attachments import extract_attachments


def _extract(conn, raw_message, directory):
    return extract_attachments(
        email.message_from_string(raw_message), 1, 1,
        account_key="synthetic", date_utc="2024-01-03", message_id="synthetic-message",
        attachments_dir=directory, conn=conn,
    )


@pytest.mark.parametrize("interrupt_type", [KeyboardInterrupt, SystemExit])
def test_interrupted_partial_attachment_write_removes_only_new_file(
    tmp_path, tmp_db, mime_factory, monkeypatch, interrupt_type,
):
    directory = tmp_path / "attachments"
    directory.mkdir()
    preserved = directory / "existing.bin"
    preserved.write_bytes(b"Previously retained evidence")
    interruption = interrupt_type("synthetic write interruption")
    real_open = Path.open
    partial_paths = []

    class InterruptedWriter:
        def __init__(self, handle, path):
            self.handle = handle
            self.path = path

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            self.handle.close()

        def write(self, payload):
            self.handle.write(payload[:3])
            self.handle.flush()
            assert self.path.read_bytes() == payload[:3]
            partial_paths.append(self.path)
            raise interruption

    def interrupted_open(path, mode="r", *args, **kwargs):
        handle = real_open(path, mode, *args, **kwargs)
        if mode == "xb" and path.is_relative_to(directory):
            return InterruptedWriter(handle, path)
        return handle

    raw = mime_factory(attachments=[("payload.bin", b"Synthetic payload", "application/octet-stream")])
    monkeypatch.setattr(Path, "open", interrupted_open)
    with closing(sqlite3.connect(tmp_db)) as conn:
        with pytest.raises(interrupt_type) as raised:
            _extract(conn, raw, directory)
        assert raised.value is interruption
        assert conn.execute("SELECT COUNT(*) FROM attachments").fetchone() == (0,)
    assert len(partial_paths) == 1
    assert not partial_paths[0].exists()
    assert preserved.read_bytes() == b"Previously retained evidence"
    assert [path for path in directory.rglob("*") if path.is_file()] == [preserved]


@pytest.mark.parametrize("interrupt_type", [KeyboardInterrupt, SystemExit])
def test_interrupted_attachment_insert_cleans_file_and_success_retains_it(
    tmp_path, tmp_db, mime_factory, interrupt_type,
):
    directory = tmp_path / "attachments"
    interruption = interrupt_type("synthetic insert interruption")
    attempted_paths = []

    class InterruptedConnection(sqlite3.Connection):
        interrupt_insert = False

        def execute(self, statement, parameters=()):
            if self.interrupt_insert and statement.lstrip().startswith("INSERT INTO attachments"):
                path = Path(parameters["storage_path"])
                assert path.read_bytes() == b"Synthetic payload"
                attempted_paths.append(path)
                raise interruption
            return super().execute(statement, parameters)

    raw = mime_factory(attachments=[("payload.bin", b"Synthetic payload", "application/octet-stream")])
    with closing(sqlite3.connect(tmp_db, factory=InterruptedConnection)) as conn:
        successful = _extract(conn, raw, directory)
        conn.commit()
        preserved = Path(successful[0]["storage_path"])
        assert preserved.read_bytes() == b"Synthetic payload"
        conn.interrupt_insert = True
        with pytest.raises(interrupt_type) as raised:
            _extract(conn, raw, directory)
        assert raised.value is interruption
        assert conn.execute("SELECT storage_path, extraction_status FROM attachments").fetchall() == [
            (str(preserved), "extracted"),
        ]
    assert len(attempted_paths) == 1
    assert attempted_paths[0] != preserved
    assert not attempted_paths[0].exists()
    assert preserved.read_bytes() == b"Synthetic payload"
    assert [path for path in directory.rglob("*") if path.is_file()] == [preserved]


@pytest.mark.parametrize("interrupt_type", [KeyboardInterrupt, SystemExit])
def test_ingest_interruption_rolls_back_partial_evidence_and_retains_checkpoint(
    tmp_path, tmp_db, make_account, config, mime_factory, mbox_factory,
    monkeypatch, interrupt_type,
):
    make_account()
    config["ingest"]["batch_commit_size"] = 1
    raw_messages = []
    for subject in ("Completed", "Interrupted"):
        message = email.message_from_string(mime_factory(
            subject=subject, message_id=f"<{subject.lower()}@example.test>",
            attachments=[("payload.bin", subject.encode(), "application/octet-stream")],
        ))
        message["X-Gmail-Labels"] = subject
        raw_messages.append(message.as_string())
    archive = mbox_factory(raw_messages)
    interruption = interrupt_type("synthetic partial-evidence interruption")
    real_extract = ingest_module.extract_attachments
    incomplete_paths = []

    def interrupted_extract(message, msg_db_id, source_id, **kwargs):
        rows = real_extract(message, msg_db_id, source_id, **kwargs)
        if message["Subject"] == "Interrupted":
            conn = kwargs["conn"]
            # Interrupt after evidence and payload exist, before ingestion has
            # released the message savepoint or registered its created paths.
            for table in ("messages", "threads", "labels", "message_labels", "attachments"):
                assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone() == (2,)
            incomplete_paths.extend(Path(row["storage_path"]) for row in rows)
            assert all(path.read_bytes() == b"Interrupted" for path in incomplete_paths)
            raise interruption
        return rows

    monkeypatch.setattr(ingest_module, "extract_attachments", interrupted_extract)
    kwargs = dict(
        db_path=tmp_db, config=config, account_key="test-gmail", extract_attachments_flag=True,
    )
    if interrupt_type is KeyboardInterrupt:
        result = ingest_module.ingest_mbox(archive, **kwargs)
        assert result["status"] == "interrupted"
        assert result["inserted"] == 1
    else:
        with pytest.raises(SystemExit) as raised:
            ingest_module.ingest_mbox(archive, **kwargs)
        assert raised.value is interruption

    with closing(sqlite3.connect(tmp_db)) as conn:
        assert conn.execute("SELECT subject FROM messages").fetchall() == [("Completed",)]
        assert conn.execute("SELECT subject, message_count FROM threads").fetchall() == [("Completed", 1)]
        for table in ("labels", "message_labels", "attachments"):
            assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone() == (1,)
        assert conn.execute("SELECT last_mbox_key FROM ingest_runs").fetchone() == ("0",)
        preserved = Path(conn.execute("SELECT storage_path FROM attachments").fetchone()[0])
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    assert len(incomplete_paths) == 1
    assert not incomplete_paths[0].exists()
    assert preserved.read_bytes() == b"Completed"
    directory = tmp_path / "attachments"
    assert [path for path in directory.rglob("*") if path.is_file()] == [preserved]
