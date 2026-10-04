from __future__ import annotations

import hashlib
import re
import sqlite3
from email.message import Message
from pathlib import Path
from typing import Any

from .accounts import validate_account_key
from .mime import decode_header_parts, iter_attachments
from .naming import slugify

MAX_FILENAME_STEM = 120
MAX_FILENAME_BYTES = 255


def _fit_filename_bytes(filename: str, suffix: str = "") -> str:
    """Keep a UTF-8 component within filesystem limits, including collision suffixes."""
    stem, sep, ext = filename.rpartition(".")
    if not sep:
        stem, ext = filename, ""
    else:
        ext = "." + ext if ext or not suffix else ""
    budget = MAX_FILENAME_BYTES - len(suffix.encode("utf-8")) - len(ext.encode("utf-8"))
    if budget < len(stem[:1].encode("utf-8")):
        # An oversized extension cannot be kept intact alongside even one stem
        # character. Truncate the whole name instead, still reserving the suffix.
        stem, ext = filename, ""
        budget = MAX_FILENAME_BYTES - len(suffix.encode("utf-8"))
    stem = stem.encode("utf-8")[:budget].decode("utf-8", errors="ignore")
    return f"{stem}{suffix}{ext}"


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
    return _fit_filename_bytes(original)


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
    counter = 1
    while True:
        name = _fit_filename_bytes(safe_filename, suffix=f"-{counter}")
        candidate = dest_dir / name
        if not candidate.exists():
            return candidate
        counter += 1


def attachment_output_path(
    *,
    base_dir: Path,
    account_key: str,
    date_str: str | None,
    message_id: str,
    filename: str,
    idx: int = 0,
) -> Path:
    """Return the expected storage path for an attachment (does not create directories).

    ``idx`` is the attachment's running index within the message and must match
    the index ``extract_attachments`` assigns (0 for the first attachment, 1 for
    the second, ...). It only affects nameless attachments, whose fallback name
    is ``attachment-<idx>``; passing the running ``idx`` here yields the distinct
    path extraction actually writes, so multiple nameless attachments no longer
    collide on a single ``attachment-0`` path.
    """
    validate_account_key(account_key)
    year = (date_str[:4] if date_str else None) or "undated"
    msg_slug = slugify(message_id, max_length=60) if message_id else "unknown"
    safe = _safe_attachment_filename(filename, idx)
    return base_dir / account_key / year / msg_slug / safe


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
    if extract_to_disk:
        validate_account_key(account_key)
    year = (date_utc[:4] if date_utc else None) or "undated"
    msg_slug = slugify(message_id, max_length=60) if message_id else f"msg-{msg_db_id}"
    results: list[dict[str, Any]] = []
    idx = 0

    for part in iter_attachments(msg):
        cd = (part.get_content_disposition() or "").lower()
        ct = part.get_content_type()
        original_filename = part.get_filename()

        if original_filename:
            original_filename = "".join(decode_header_parts(original_filename))

        payload = part.get_payload(decode=True)
        if not isinstance(payload, bytes):
            payload = b""

        content_hash = hashlib.sha256(payload).hexdigest() if payload else None
        safe_filename = _safe_attachment_filename(original_filename, idx)
        idx += 1

        storage_path: str | None = None
        extraction_status = "pending"
        error_message: str | None = None
        dest: Path | None = None
        dest_created = False

        if extract_to_disk and payload:
            try:
                dest = _resolve_storage_path(
                    attachments_dir, account_key, year, msg_slug, safe_filename
                )
                # Exclusive creation protects a path selected before another
                # extractor wrote it. Cleanup must only remove our own file.
                with dest.open("xb") as handle:
                    dest_created = True
                    handle.write(payload)
                storage_path = str(dest)
                extraction_status = "extracted"
            except BaseException as exc:
                # Interrupts also require partial-file cleanup, then propagate.
                if dest_created and dest is not None:
                    dest.unlink(missing_ok=True)
                if not isinstance(exc, Exception):
                    raise
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
        try:
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
        except BaseException:
            # Remove our file on any failed INSERT, including an interrupt;
            # successful inserts must retain their extracted attachment.
            if dest_created and dest is not None:
                dest.unlink(missing_ok=True)
            raise
        results.append(row)

    return results
