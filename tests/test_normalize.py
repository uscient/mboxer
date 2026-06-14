import email
import json

from mboxer.normalize import normalize_message, normalize_date, compute_body_hash


def test_normalize_date_valid():
    result = normalize_date("Mon, 1 Jan 2024 12:00:00 +0000")
    assert result is not None
    assert "2024" in result


def test_normalize_date_none():
    assert normalize_date(None) is None
    assert normalize_date("") is None


def test_body_hash_deterministic():
    h1 = compute_body_hash("hello world")
    h2 = compute_body_hash("hello world")
    assert h1 == h2


def test_normalize_message_basic():
    raw = (
        "From: alice@example.com\r\n"
        "To: bob@example.com\r\n"
        "Subject: Test\r\n"
        "Date: Mon, 1 Jan 2024 10:00:00 +0000\r\n"
        "Message-ID: <abc@example.com>\r\n"
        "\r\n"
        "Hello there.\r\n"
    )
    msg = email.message_from_string(raw)
    record = normalize_message(msg, source_id=1, mbox_key="0")
    assert record["subject"] == "Test"
    assert record["sender"] == "alice@example.com"
    assert "Hello there" in (record["body_text"] or "")
    assert record["body_hash"] is not None
    assert record["body_chars"] > 0
    assert record["body_word_count"] >= 2


def test_normalize_message_html_fallback():
    raw = (
        "From: alice@example.com\r\n"
        "Content-Type: text/html\r\n"
        "\r\n"
        "<html><body><p>Hello from HTML</p></body></html>\r\n"
    )
    msg = email.message_from_string(raw)
    record = normalize_message(msg, source_id=1, mbox_key="0")
    assert "Hello from HTML" in (record["body_text"] or "")


def test_normalize_message_address_lists_are_lowercase_arrays():
    raw = (
        "From: Sender <SENDER@Example.COM>\r\n"
        'To: "Recipient, One" <USER@Example.COM>, Team <TEAM@Example.ORG>\r\n'
        "Cc: Undisclosed recipients:;\r\n"
        'Bcc: "Hidden, Person" <HIDDEN@Example.NET>\r\n'
        "Subject: Address invariant\r\n"
        "\r\n"
        "Body.\r\n"
    )
    msg = email.message_from_string(raw)
    record = normalize_message(msg, source_id=1, mbox_key="0")

    assert json.loads(record["recipients_json"]) == ["user@example.com", "team@example.org"]
    assert json.loads(record["cc_json"]) == []
    assert json.loads(record["bcc_json"]) == ["hidden@example.net"]


# ── Encoded headers, odd dates, and body extraction edge cases ────────────────

def test_normalize_decodes_rfc2047_encoded_subject():
    raw = "From: a@example.com\nSubject: =?UTF-8?Q?caf=C3=A9?=\n\nbody\n"
    msg = email.message_from_string(raw)
    record = normalize_message(msg, source_id=1, mbox_key="0")
    assert record["subject"] == "café"  # decoded, not the raw =?...?= token


def test_normalize_date_garbage_returns_none():
    assert normalize_date("not a real date") is None
    assert normalize_date("Mon, 99 Zzz 9999 99:99:99") is None


def test_normalize_message_garbage_date_keeps_header_but_no_utc():
    raw = "From: a@example.com\nSubject: s\nDate: total garbage\n\nbody\n"
    msg = email.message_from_string(raw)
    record = normalize_message(msg, source_id=1, mbox_key="0")
    assert record["date_utc"] is None
    assert record["date_header"] == "total garbage"


def test_normalize_multipart_html_only_falls_back_to_stripped_text():
    raw = (
        'Content-Type: multipart/alternative; boundary="B"\n'
        "From: a@example.com\nSubject: s\n\n"
        "--B\n"
        "Content-Type: text/html\n\n"
        "<p>Hello <b>world</b></p>\n"
        "--B--\n"
    )
    msg = email.message_from_string(raw)
    record = normalize_message(msg, source_id=1, mbox_key="0")
    assert "Hello" in record["body_text"]
    assert "world" in record["body_text"]
    assert "<" not in record["body_text"]  # tags stripped


def test_normalize_multipart_empty_plain_part_yields_no_body():
    raw = (
        'Content-Type: multipart/mixed; boundary="B"\n'
        "From: a@example.com\nSubject: s\n\n"
        "--B\n"
        "Content-Type: text/plain\n\n"
        "--B--\n"
    )
    msg = email.message_from_string(raw)
    record = normalize_message(msg, source_id=1, mbox_key="0")
    assert record["body_text"] is None
    assert record["body_word_count"] == 0


def test_normalize_non_text_message_has_no_body():
    raw = "Content-Type: application/octet-stream\nFrom: a@example.com\nSubject: s\n\nrawbytes\n"
    msg = email.message_from_string(raw)
    record = normalize_message(msg, source_id=1, mbox_key="0")
    assert record["body_text"] is None


def test_normalize_unknown_charset_falls_back_to_latin1():
    raw = 'Content-Type: text/plain; charset="bogus-charset"\nFrom: a@example.com\nSubject: s\n\nhello\n'
    msg = email.message_from_string(raw)
    record = normalize_message(msg, source_id=1, mbox_key="0")
    assert "hello" in record["body_text"]


def test_normalize_encoded_header_unknown_charset_does_not_crash():
    raw = "From: a@example.com\nSubject: =?bogus-charset?Q?caf=C3=A9?=\n\nbody\n"
    msg = email.message_from_string(raw)
    record = normalize_message(msg, source_id=1, mbox_key="0")
    assert record["subject"]            # recovered via latin-1 fallback, no exception
    assert "=?" not in record["subject"]  # still decoded out of the encoded-word form
