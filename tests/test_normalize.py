import email
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
