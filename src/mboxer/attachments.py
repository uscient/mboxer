from __future__ import annotations

import hashlib
import re
import sqlite3
from email.message import Message
from pathlib import Path
from typing import Any

from .naming import slugify

MAX_FILENAME_STEM = 120


def _safe_attachment_filename(original: str | None, idx: int) -> str:
    if original:
        original = re.sub(r"[^\w.\-]", "_", original).strip("._")
        original = re.sub(r"_+", "_", original)
        if len(original) > MAX_FILENAME_STEM + 10:
            stem, _, ext = original.rpartition(".")
            if ext and len(ext) <= 10:
                original = stem[:MAX_FILENAME_STEM] + "." + ext
            else:
                original = original[:MAX_FILENAME_STEM]
    if not original:
        original = f"attachment-{idx}"
    return original


def _resolve_storage_path(
    attachments_dir: Path,
    account_key: str,
    year: str,
    msg_slug: str,
    safe_filename: str,
) -> Path:
    dest_dir = attachments_dir / account_key / year / msg_slug
    dest_dir.mkdir(parents=True, exist_ok=True)
    candidate = dest_dir / safe_filename
    if not candidate.exists():
        return candidate
    stem, _, ext = safe_filename.rpartition(".")
    if not ext:
        stem, ext = safe_filename, ""
    counter = 1
    while True:
        name = f"{stem}-{counter}.{ext}" if ext else f"{stem}-{counter}"
        candidate = dest_dir / name
        if not candidate.exists():
            return candidate
        counter += 1


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def extract_attachments(
    msg: Message,
    msg_db_id: int,
    source_id: int,
    *,
    account_id: int | None = None,
    account_key: str = "default",
    date_utc: str | None = None,
    message_id: str = "",
    attachments_dir: Path,
    conn: sqlite3.Connection,
    extract_to_disk: bool = True,
) -> list[dict[str, Any]]:
    year = (date_utc[:4] if date_utc else None) or "undated"
    msg_slug = slugify(message_id, max_length=60) if message_id else f"msg-{msg_db_id}"
    results: list[dict[str, Any]] = []
    idx = 0

    for part in msg.walk():
        cd = (part.get_content_disposition() or "").lower()
        if "attachment" not in cd and part.get_filename() is None:
            continue
        ct = part.get_content_type()
        original_filename = part.get_filename()

        if original_filename:
            from email.header import decode_header as _dh
            decoded_parts = _dh(original_filename)
            fname_parts: list[str] = []
            for encoded, charset in decoded_parts:
                if isinstance(encoded, bytes):
                    enc = charset or "utf-8"
                    try:
                        fname_parts.append(encoded.decode(enc, errors="replace"))
                    except LookupError:
                        fname_parts.append(encoded.decode("latin-1", errors="replace"))
                else:
                    fname_parts.append(encoded)
            original_filename = "".join(fname_parts)

        payload = part.get_payload(decode=True)
        if not isinstance(payload, bytes):
            payload = b""

        content_hash = _sha256_bytes(payload) if payload else None
        safe_filename = _safe_attachment_filename(original_filename, idx)
        idx += 1

        storage_path: str | None = None
        extraction_status = "pending"
        error_message: str | None = None

        if extract_to_disk and payload:
            try:
                dest = _resolve_storage_path(
                    attachments_dir, account_key, year, msg_slug, safe_filename
                )
                dest.write_bytes(payload)
                storage_path = str(dest)
                extraction_status = "extracted"
            except Exception as exc:
                extraction_status = "error"
                error_message = str(exc)
        elif not payload:
            extraction_status = "empty"

        row: dict[str, Any] = {
            "account_id": account_id,
            "message_db_id": msg_db_id,
            "source_id": source_id,
            "original_filename": original_filename,
            "safe_filename": safe_filename,
            "content_type": ct,
            "content_disposition": cd,
            "size_bytes": len(payload),
            "sha256": content_hash,
            "storage_path": storage_path,
            "extraction_status": extraction_status,
            "error_message": error_message,
        }
        conn.execute(
            """
            INSERT INTO attachments
              (account_id, message_db_id, source_id, original_filename, safe_filename,
               content_type, content_disposition, size_bytes, sha256,
               storage_path, extraction_status, error_message)
            VALUES
              (:account_id, :message_db_id, :source_id, :original_filename, :safe_filename,
               :content_type, :content_disposition, :size_bytes, :sha256,
               :storage_path, :extraction_status, :error_message)
            """,
            row,
        )
        results.append(row)

    return results
