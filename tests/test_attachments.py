"""Tests for attachment extraction, filename safety, and path computation.

Covers the corrected nameless-attachment path logic (the former ``idx=0`` defect
in ``attachment_output_path``) plus the security-relevant behavior: filename
sanitization, SHA-256 hashing, dangerous/duplicate filenames, and the
empty/pending/error extraction statuses.
"""
from __future__ import annotations

import email
import hashlib
import sqlite3
from email.message import Message
from pathlib import Path

import pytest

from mboxer.attachments import attachment_output_path, extract_attachments


# ── fixtures / helpers ────────────────────────────────────────────────────────

@pytest.fixture
def conn(tmp_db: Path):
    c = sqlite3.connect(tmp_db)
    try:
        yield c
    finally:
        c.close()


@pytest.fixture
def make_msg(mime_factory):
    """Build a parsed email.message.Message with the given attachments."""
    def _make(**kwargs) -> Message:
        return email.message_from_string(mime_factory(**kwargs))
    return _make


def _extract(conn, msg, attachments_dir, *, extract=True, message_id="<m-001@example.com>"):
    return extract_attachments(
        msg,
        1,  # msg_db_id
        1,  # source_id
        account_id=1,
        account_key="acct",
        date_utc="2024-03-15",
        message_id=message_id,
        attachments_dir=attachments_dir,
        conn=conn,
        extract_to_disk=extract,
    )


# ── attachment_output_path: the idx=0 defect (now fixed) ──────────────────────

@pytest.mark.unit
def test_nameless_attachments_get_distinct_paths_by_idx():
    """Regression: each nameless attachment must map to attachment-<idx>,
    not collide on attachment-0."""
    common = dict(
        base_dir=Path("/exports"),
        account_key="a",
        date_str="2024-01-01",
        message_id="<m@x>",
        filename="",
    )
    p0 = attachment_output_path(**common, idx=0)
    p1 = attachment_output_path(**common, idx=1)
    p2 = attachment_output_path(**common, idx=2)

    assert p0.name == "attachment-0"
    assert p1.name == "attachment-1"
    assert p2.name == "attachment-2"
    assert len({p0, p1, p2}) == 3  # the defect made these identical


@pytest.mark.unit
def test_output_path_idx_defaults_to_zero():
    p = attachment_output_path(
        base_dir=Path("/x"), account_key="a", date_str=None,
        message_id="<m@x>", filename="",
    )
    assert p.name == "attachment-0"


# ── attachment_output_path: filename safety + provenance ──────────────────────

@pytest.mark.unit
def test_output_path_preserves_simple_filename():
    p = attachment_output_path(
        base_dir=Path("/x"), account_key="a", date_str="2024-05-02",
        message_id="<m@x>", filename="invoice.pdf",
    )
    assert p.name == "invoice.pdf"


@pytest.mark.unit
@pytest.mark.parametrize("dangerous", [
    "../../etc/passwd",
    "..\\..\\windows\\system32",
    "/abs/secret.key",
    "with/slash.txt",
])
def test_output_path_neutralizes_path_traversal(dangerous):
    base = Path("/exports")
    p = attachment_output_path(
        base_dir=base, account_key="a", date_str="2024-01-01",
        message_id="<m@x>", filename=dangerous,
    )
    # No separator survives in the final component and the path cannot escape base.
    assert "/" not in p.name
    assert "\\" not in p.name
    assert p.name not in ("", ".", "..")
    assert p.is_relative_to(base)


@pytest.mark.unit
def test_output_path_includes_account_and_year_for_provenance():
    p = attachment_output_path(
        base_dir=Path("/exports"), account_key="primary-gmail",
        date_str="2023-07-09", message_id="<m@x>", filename="x.pdf",
    )
    assert "primary-gmail" in p.parts
    assert "2023" in p.parts


@pytest.mark.unit
def test_output_path_undated_when_no_date():
    p = attachment_output_path(
        base_dir=Path("/x"), account_key="a", date_str=None,
        message_id="<m@x>", filename="x.pdf",
    )
    assert "undated" in p.parts


# ── extract_attachments: extraction, hashing, statuses ────────────────────────

@pytest.mark.integration
def test_extract_writes_file_with_correct_bytes_and_hash(conn, make_msg, tmp_path):
    payload = b"%PDF-1.4 synthetic invoice bytes"
    msg = make_msg(attachments=[("invoice.pdf", payload, "application/pdf")])
    adir = tmp_path / "attachments"

    rows = _extract(conn, msg, adir)

    assert len(rows) == 1
    row = rows[0]
    assert row["extraction_status"] == "extracted"
    assert row["safe_filename"] == "invoice.pdf"
    assert row["content_type"] == "application/pdf"
    assert row["size_bytes"] == len(payload)
    assert row["sha256"] == hashlib.sha256(payload).hexdigest()
    written = Path(row["storage_path"])
    assert written.read_bytes() == payload
    # persisted to the attachments table
    assert conn.execute("SELECT COUNT(*) FROM attachments").fetchone()[0] == 1


@pytest.mark.integration
def test_extract_two_nameless_attachments_match_output_path(conn, make_msg, tmp_path):
    """The extraction paths for nameless attachments must match what
    attachment_output_path(idx=...) predicts — the end-to-end idx contract."""
    msg = make_msg(attachments=[
        (None, b"first", "application/octet-stream"),
        (None, b"second", "application/octet-stream"),
    ])
    adir = tmp_path / "attachments"

    rows = _extract(conn, msg, adir, message_id="<two@example.com>")

    names = sorted(Path(r["storage_path"]).name for r in rows)
    assert names == ["attachment-0", "attachment-1"]
    for idx, row in enumerate(rows):
        predicted = attachment_output_path(
            base_dir=adir, account_key="acct", date_str="2024-03-15",
            message_id="<two@example.com>", filename="", idx=idx,
        )
        assert Path(row["storage_path"]) == predicted


@pytest.mark.integration
def test_extract_duplicate_filenames_do_not_overwrite(conn, make_msg, tmp_path):
    msg = make_msg(attachments=[
        ("report.pdf", b"one", "application/pdf"),
        ("report.pdf", b"two", "application/pdf"),
    ])
    adir = tmp_path / "attachments"

    rows = _extract(conn, msg, adir)

    paths = [Path(r["storage_path"]) for r in rows]
    assert paths[0].name == "report.pdf"
    assert paths[1].name == "report-1.pdf"
    assert paths[0] != paths[1]
    assert paths[0].read_bytes() == b"one"
    assert paths[1].read_bytes() == b"two"


@pytest.mark.integration
def test_extract_empty_payload_is_recorded_not_written(conn, make_msg, tmp_path):
    msg = make_msg(attachments=[("empty.bin", b"", "application/octet-stream")])
    adir = tmp_path / "attachments"

    rows = _extract(conn, msg, adir)

    assert rows[0]["extraction_status"] == "empty"
    assert rows[0]["sha256"] is None
    assert rows[0]["storage_path"] is None
    assert not adir.exists()  # nothing written


@pytest.mark.integration
def test_extract_to_disk_false_records_pending_without_writing(conn, make_msg, tmp_path):
    msg = make_msg(attachments=[("invoice.pdf", b"bytes", "application/pdf")])
    adir = tmp_path / "attachments"

    rows = _extract(conn, msg, adir, extract=False)

    assert rows[0]["extraction_status"] == "pending"
    assert rows[0]["storage_path"] is None
    # hash is still computed from the in-memory payload even without writing
    assert rows[0]["sha256"] == hashlib.sha256(b"bytes").hexdigest()
    assert not adir.exists()


@pytest.mark.integration
def test_extract_write_failure_records_error(conn, make_msg, tmp_path):
    blocked = tmp_path / "blocked"
    blocked.write_text("not a directory")  # force mkdir under it to fail
    msg = make_msg(attachments=[("invoice.pdf", b"bytes", "application/pdf")])

    rows = _extract(conn, msg, blocked)

    assert rows[0]["extraction_status"] == "error"
    assert rows[0]["error_message"]


@pytest.mark.integration
def test_extract_decodes_rfc2047_filename(conn, make_msg, tmp_path):
    """Non-ASCII attachment names arrive RFC-2047 encoded; they must be decoded,
    not stored as a raw =?utf-8?...?= token."""
    msg = make_msg(attachments=[("résumé.pdf", b"cv", "application/pdf")])
    adir = tmp_path / "attachments"

    rows = _extract(conn, msg, adir)

    assert "=?" not in (rows[0]["original_filename"] or "")
    assert "sum" in rows[0]["original_filename"]  # the decoded é-bearing name


@pytest.mark.integration
def test_extract_body_text_is_not_treated_as_attachment(conn, make_msg, tmp_path):
    msg = make_msg(body="Just a note, no files.", attachments=[])
    rows = _extract(conn, msg, tmp_path / "attachments")
    assert rows == []


@pytest.mark.unit
def test_output_path_truncates_overlong_filename_keeping_extension():
    name = "a" * 200 + ".pdf"
    p = attachment_output_path(
        base_dir=Path("/x"), account_key="a", date_str="2024-01-01",
        message_id="<m@x>", filename=name,
    )
    assert p.name.endswith(".pdf")
    assert len(p.name) <= 130  # MAX_FILENAME_STEM (120) + ".pdf"


@pytest.mark.unit
def test_output_path_truncates_overlong_extensionless_filename():
    p = attachment_output_path(
        base_dir=Path("/x"), account_key="a", date_str="2024-01-01",
        message_id="<m@x>", filename="b" * 200,
    )
    assert "." not in p.name
    assert len(p.name) <= 120


@pytest.mark.integration
def test_extract_duplicate_extensionless_names_get_suffixed(conn, make_msg, tmp_path):
    """A second extensionless file with the same name is suffixed as 'name-1'
    (not the former '-1.name'), and never clobbers the first."""
    msg = make_msg(attachments=[
        ("Makefile", b"one", "application/octet-stream"),
        ("Makefile", b"two", "application/octet-stream"),
    ])
    adir = tmp_path / "attachments"

    rows = _extract(conn, msg, adir)

    names = [Path(r["storage_path"]).name for r in rows]
    assert names == ["Makefile", "Makefile-1"]
    assert Path(rows[0]["storage_path"]).read_bytes() == b"one"
    assert Path(rows[1]["storage_path"]).read_bytes() == b"two"


@pytest.mark.integration
def test_extract_decodes_legacy_rfc2047_encoded_word(conn, tmp_path):
    """Gmail archives carry RFC-2047 encoded-word filenames; the decoder's
    bytes path must turn =?utf-8?b?...?= into the real name."""
    raw = (
        "From: a@b.com\n"
        "To: u@x.com\n"
        "Subject: s\n"
        "Date: Wed, 03 Jan 2024 09:00:00 +0000\n"
        "Message-ID: <enc@example.com>\n"
        "MIME-Version: 1.0\n"
        'Content-Type: multipart/mixed; boundary="B"\n'
        "\n"
        "--B\n"
        "Content-Type: text/plain\n"
        "\n"
        "body\n"
        "--B\n"
        "Content-Type: application/octet-stream\n"
        'Content-Disposition: attachment; filename="=?utf-8?b?cmVwb3J0LnBkZg==?="\n'
        "Content-Transfer-Encoding: base64\n"
        "\n"
        "ZGF0YQ==\n"
        "--B--\n"
    )
    msg = email.message_from_string(raw)

    rows = _extract(conn, msg, tmp_path / "attachments")

    assert len(rows) == 1
    assert rows[0]["original_filename"] == "report.pdf"  # decoded from the encoded-word
