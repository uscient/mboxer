"""Importable test helpers shared across the suite.

These are plain functions (not fixtures) so existing module-level constants and
helpers (e.g. ``CONFIG = base_config(...)``) can use them without restructuring.
``conftest.py`` wraps the ones that need ``tmp_path`` into fixtures
(``mbox_factory``, ``config``, ``mime_factory``).
"""
from __future__ import annotations

import mailbox
from email.message import EmailMessage
from pathlib import Path
from typing import Any


def make_mbox(path: Path, messages: list[str]) -> None:
    """Write raw RFC-822 message strings into an mbox file at *path*.

    Consolidates the byte-identical ``_make_mbox`` helper previously duplicated
    across eight test modules.
    """
    mbox = mailbox.mbox(str(path), create=True)
    for raw in messages:
        mbox.add(mailbox.mboxMessage(raw))
    mbox.flush()
    mbox.close()


# Shared ingest defaults previously copy-pasted into every test module's CONFIG.
_INGEST_DEFAULTS: dict[str, Any] = {
    "batch_commit_size": 10,
    "store_body_html": False,
    "max_body_chars": 50000,
}


def base_config(**sections: Any) -> dict[str, Any]:
    """Return a minimal mboxer config dict with the shared ingest defaults.

    Pass section overrides as keyword args, e.g.
    ``base_config(rules=[...], taxonomy={...})``.

    No ``paths.attachments_dir`` is set: ``ingest`` falls back to its own default
    and never touches it unless a test actually extracts attachments. Tests that
    DO extract should use the ``config`` fixture, which roots it under tmp_path.
    """
    cfg: dict[str, Any] = {"ingest": dict(_INGEST_DEFAULTS)}
    cfg.update(sections)
    return cfg


def make_attachment_message(
    *,
    subject: str = "Attachment test",
    sender: str = "files@example.com",
    to: str = "user@example.com",
    date: str = "Wed, 03 Jan 2024 09:00:00 +0000",
    message_id: str = "<attach-001@example.com>",
    body: str = "See attached.",
    attachments: list[tuple[str | None, bytes, str]] | None = None,
) -> str:
    """Build a raw multipart message string with optional attachments.

    Each attachment is ``(filename_or_None, payload_bytes, content_type)``.
    ``filename=None`` yields a nameless attachment part (Content-Disposition:
    attachment, no filename) — useful for exercising the nameless-attachment
    path logic. Returns a string suitable for :func:`make_mbox`.
    """
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = to
    msg["Subject"] = subject
    msg["Date"] = date
    msg["Message-ID"] = message_id
    msg.set_content(body)
    for filename, payload, content_type in attachments or []:
        maintype, _, subtype = content_type.partition("/")
        msg.add_attachment(
            payload,
            maintype=maintype or "application",
            subtype=subtype or "octet-stream",
            filename=filename,
        )
    return msg.as_string()
