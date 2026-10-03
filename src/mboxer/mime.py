"""MIME decoding shared by message normalization and attachment extraction."""
from __future__ import annotations

from collections.abc import Iterator
from email.header import decode_header
from email.message import Message


def decode_bytes(payload: bytes, charset: str | None) -> str:
    """Decode with replacement and retain the historical unknown-charset fallback."""
    try:
        return payload.decode(charset or "utf-8", errors="replace")
    except LookupError:
        return payload.decode("latin-1", errors="replace")


def decode_header_parts(value: str | None) -> list[str]:
    """Decode header parts; callers retain their field-specific joining rules."""
    if not value:
        return []
    return [
        decode_bytes(encoded, charset) if isinstance(encoded, bytes) else encoded
        for encoded, charset in decode_header(value)
    ]


def iter_attachments(msg: Message) -> Iterator[Message]:
    """Select the same MIME parts when counting and extracting attachments."""
    for part in msg.walk():
        disposition = (part.get_content_disposition() or "").lower()
        if "attachment" in disposition or part.get_filename() is not None:
            yield part
