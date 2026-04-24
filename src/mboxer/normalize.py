from __future__ import annotations

import hashlib
import json
import re
from email.header import decode_header
from email.message import Message
from email.utils import parseaddr, parsedate_to_datetime
from typing import Any


def _decode_header_value(value: str | None) -> str:
    if not value:
        return ""
    parts: list[str] = []
    for encoded, charset in decode_header(value):
        if isinstance(encoded, bytes):
            enc = charset or "utf-8"
            try:
                parts.append(encoded.decode(enc, errors="replace"))
            except LookupError:
                parts.append(encoded.decode("latin-1", errors="replace"))
        else:
            parts.append(encoded)
    return " ".join(parts).strip()


def _parse_address_list(header_value: str | None) -> list[str]:
    if not header_value:
        return []
    addrs: list[str] = []
    for segment in re.split(r",(?=(?:[^\"]*\"[^\"]*\")*[^\"]*$)", header_value):
        _, email_addr = parseaddr(segment.strip())
        if email_addr:
            addrs.append(email_addr.lower())
    return addrs


def normalize_date(date_str: str | None) -> str | None:
    if not date_str:
        return None
    try:
        dt = parsedate_to_datetime(date_str)
        return dt.isoformat()
    except Exception:
        return None


def _extract_bodies(msg: Message) -> tuple[str | None, str | None]:
    plain: str | None = None
    html: str | None = None

    def _decode_part(part: Message) -> str | None:
        payload = part.get_payload(decode=True)
        if not payload:
            return None
        charset = part.get_content_charset("utf-8") or "utf-8"
        try:
            return payload.decode(charset, errors="replace")
        except LookupError:
            return payload.decode("latin-1", errors="replace")

    if msg.is_multipart():
        for part in msg.walk():
            cd = (part.get_content_disposition() or "").lower()
            if "attachment" in cd:
                continue
            ct = part.get_content_type()
            if ct == "text/plain" and plain is None:
                plain = _decode_part(part)
            elif ct == "text/html" and html is None:
                html = _decode_part(part)
    else:
        ct = msg.get_content_type()
        text = _decode_part(msg)
        if ct == "text/plain":
            plain = text
        elif ct == "text/html":
            html = text

    return plain, html


def _html_to_text(html: str) -> str:
    html = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<br\s*/?>", "\n", html, flags=re.IGNORECASE)
    html = re.sub(r"<[^>]+>", " ", html)
    html = re.sub(r"[ \t]+", " ", html)
    html = re.sub(r"\n{3,}", "\n\n", html)
    return html.strip()


def compute_body_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _count_attachments(msg: Message) -> int:
    count = 0
    for part in msg.walk():
        cd = (part.get_content_disposition() or "").lower()
        if "attachment" in cd:
            count += 1
    return count


def parse_gmail_labels(msg: Message) -> list[str]:
    """Parse X-Gmail-Labels header into a list of raw label names."""
    raw = msg.get("X-Gmail-Labels") or ""
    if not raw:
        return []
    return [label.strip() for label in raw.split(",") if label.strip()]


def normalize_message(msg: Message, source_id: int, mbox_key: str, account_id: int | None = None) -> dict[str, Any]:
    subject = _decode_header_value(msg.get("Subject"))
    from_raw = _decode_header_value(msg.get("From"))
    _, sender = parseaddr(from_raw)

    date_header = msg.get("Date")
    date_utc = normalize_date(date_header)

    message_id = (msg.get("Message-ID") or "").strip()

    references = (msg.get("References") or "").strip()
    in_reply_to = (msg.get("In-Reply-To") or "").strip()
    if references:
        thread_key = references.split()[0].strip()
    elif in_reply_to:
        thread_key = in_reply_to.strip()
    else:
        thread_key = message_id

    recipients = _parse_address_list(_decode_header_value(msg.get("To")))
    cc = _parse_address_list(_decode_header_value(msg.get("Cc")))
    bcc = _parse_address_list(_decode_header_value(msg.get("Bcc")))

    plain, html = _extract_bodies(msg)
    body_text = plain
    if body_text is None and html is not None:
        body_text = _html_to_text(html)

    body_hash = compute_body_hash(body_text) if body_text else None
    body_chars = len(body_text) if body_text else 0
    body_word_count = len(body_text.split()) if body_text else 0
    attachment_count = _count_attachments(msg)

    raw_headers = {k: v for k, v in msg.items()}
    gmail_labels = parse_gmail_labels(msg)

    return {
        "account_id": account_id,
        "source_id": source_id,
        "mbox_key": mbox_key,
        "message_id": message_id or None,
        "thread_key": thread_key or None,
        "subject": subject or None,
        "sender": sender.lower() if sender else None,
        "recipients_json": json.dumps(recipients),
        "cc_json": json.dumps(cc),
        "bcc_json": json.dumps(bcc),
        "date_header": date_header or None,
        "date_utc": date_utc,
        "body_text": body_text,
        "body_html": None,
        "body_hash": body_hash,
        "body_chars": body_chars,
        "body_word_count": body_word_count,
        "attachment_count": attachment_count,
        "raw_headers_json": json.dumps(raw_headers),
        "gmail_labels": gmail_labels,
    }
