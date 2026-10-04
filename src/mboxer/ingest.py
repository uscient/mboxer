from __future__ import annotations

import json
import mailbox
import sqlite3
from pathlib import Path
from typing import Any

from .accounts import AccountError, get_account, validate_account_key
from .attachments import extract_attachments
from .config import ensure_parent_dir, get_path, get_setting
from .db import init_db
from .files import sha256_file as _file_sha256
from .naming import slugify
from .normalize import compute_body_hash, normalize_message
from .records import loads_address_list


class SourceIdentityError(RuntimeError):
    """Raised when an existing source path no longer matches its recorded content hash."""


class AttachmentError(RuntimeError):
    """An attachment could not be stored with its message."""


def _get_or_create_source(
    conn: sqlite3.Connection,
    file_path: Path,
    source_name: str,
    account_id: int,
    *,
    force: bool = False,
) -> tuple[int, str]:
    source_slug = slugify(source_name)
    stat = file_path.stat()
    file_sha256 = _file_sha256(file_path)

    row = conn.execute(
        "SELECT id, file_sha256 FROM mbox_sources WHERE account_id = ? AND file_path = ?",
        (account_id, str(file_path)),
    ).fetchone()
    if row:
        source_id, recorded_sha256 = row
        if recorded_sha256 and recorded_sha256 != file_sha256 and not force:
            raise SourceIdentityError(
                "Source MBOX content hash changed for this account/path; "
                "rerun with --force to replace local message evidence."
            )
        if force:
            # Publish replacement identity only in the transaction that stores
            # the complete replacement source, never before it is read.
            return source_id, file_sha256
        conn.execute(
            """
            UPDATE mbox_sources
            SET file_size = ?, file_sha256 = ?, source_mtime = ?
            WHERE id = ?
            """,
            (stat.st_size, file_sha256, stat.st_mtime, source_id),
        )
        conn.commit()
        return source_id, file_sha256

    conn.execute(
        """
        INSERT INTO mbox_sources
          (account_id, source_name, source_slug, file_path, file_size, file_sha256, source_mtime)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            account_id,
            source_name,
            source_slug,
            str(file_path),
            stat.st_size,
            file_sha256,
            stat.st_mtime,
        ),
    )
    conn.commit()
    source_id = conn.execute(
        "SELECT id FROM mbox_sources WHERE account_id = ? AND file_path = ?",
        (account_id, str(file_path)),
    ).fetchone()[0]
    return source_id, file_sha256


def _create_run(conn: sqlite3.Connection, source_id: int, account_id: int) -> int:
    conn.execute(
        "INSERT INTO ingest_runs (account_id, source_id, status) VALUES (?, ?, 'running')",
        (account_id, source_id),
    )
    conn.commit()
    return conn.execute(
        "SELECT id FROM ingest_runs WHERE source_id = ? ORDER BY id DESC LIMIT 1",
        (source_id,),
    ).fetchone()[0]


def _get_resume_run(conn: sqlite3.Connection, source_id: int) -> tuple[int, str | None] | None:
    row = conn.execute(
        """
        SELECT id, last_mbox_key FROM ingest_runs
        WHERE source_id = ? AND status IN ('running', 'interrupted')
        ORDER BY id DESC LIMIT 1
        """,
        (source_id,),
    ).fetchone()
    return (row[0], row[1]) if row else None


def _update_run(conn: sqlite3.Connection, run_id: int, **kwargs: Any) -> None:
    allowed = {
        "status", "last_mbox_key", "messages_seen", "messages_inserted",
        "messages_skipped", "errors_count",
    }
    if not kwargs or not kwargs.keys() <= allowed:
        raise ValueError("Unsupported ingest-run update fields")
    sets = ", ".join(f"{k} = :{k}" for k in kwargs)
    # Only literal column names from the allowlist above enter this statement.
    conn.execute(f"UPDATE ingest_runs SET {sets} WHERE id = :_id", {"_id": run_id, **kwargs})  # nosec B608


def _record_ingest_error(
    conn: sqlite3.Connection,
    *,
    account_id: int,
    run_id: int,
    source_id: int,
    mbox_key: str | None,
    error_type: str,
    error_message: str,
) -> None:
    conn.execute(
        """
        INSERT INTO ingest_errors
          (account_id, ingest_run_id, source_id, mbox_key, error_type, error_message)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (account_id, run_id, source_id, mbox_key, error_type, error_message),
    )


def _upsert_thread(
    conn: sqlite3.Connection,
    account_id: int,
    source_id: int,
    thread_key: str,
    subject: str | None,
    date_utc: str | None,
    participants: list[str],
) -> None:
    existing = conn.execute(
        "SELECT id, message_count, first_date_utc, last_date_utc FROM threads "
        "WHERE account_id = ? AND thread_key = ? AND source_id = ?",
        (account_id, thread_key, source_id),
    ).fetchone()

    if existing:
        tid, mc, first_date, last_date = existing
        new_first = min(filter(None, [first_date, date_utc])) if (first_date or date_utc) else None
        new_last = max(filter(None, [last_date, date_utc])) if (last_date or date_utc) else None
        conn.execute(
            "UPDATE threads SET message_count = ?, first_date_utc = ?, last_date_utc = ?, "
            "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (mc + 1, new_first, new_last, tid),
        )
    else:
        conn.execute(
            """
            INSERT INTO threads
              (account_id, source_id, thread_key, subject, message_count, first_date_utc, last_date_utc, participants_json)
            VALUES (?, ?, ?, ?, 1, ?, ?, ?)
            """,
            (account_id, source_id, thread_key, subject, date_utc, date_utc, json.dumps(participants[:20])),
        )


def _delete_message_dependents(conn: sqlite3.Connection, msg_db_id: int) -> None:
    """Delete all dependent rows for a message and the message itself.

    Source replacement separately invalidates affected thread classifications.
    """
    thread_info = conn.execute(
        "SELECT thread_key, account_id, source_id FROM messages WHERE id = ?",
        (msg_db_id,),
    ).fetchone()

    conn.execute("DELETE FROM export_items WHERE message_db_id = ?", (msg_db_id,))
    conn.execute(
        "DELETE FROM security_findings WHERE message_db_id = ? OR attachment_id IN "
        "(SELECT id FROM attachments WHERE message_db_id = ?)",
        (msg_db_id, msg_db_id),
    )
    conn.execute(
        "DELETE FROM classifications WHERE message_db_id = ? AND target_type = 'message'",
        (msg_db_id,),
    )
    conn.execute("DELETE FROM message_labels WHERE message_db_id = ?", (msg_db_id,))
    conn.execute("DELETE FROM attachments WHERE message_db_id = ?", (msg_db_id,))
    conn.execute("DELETE FROM messages WHERE id = ?", (msg_db_id,))

    if thread_info:
        thread_key, account_id, source_id = thread_info
        if thread_key:
            conn.execute(
                "UPDATE threads SET message_count = MAX(0, message_count - 1) "
                "WHERE account_id = ? AND thread_key = ? AND source_id = ?",
                (account_id, thread_key, source_id),
            )


def _store_labels(
    conn: sqlite3.Connection,
    account_id: int,
    msg_db_id: int,
    labels: list[str],
) -> None:
    for label_name in labels:
        normalized = label_name.lower().replace(" ", "-")
        conn.execute(
            "INSERT OR IGNORE INTO labels (account_id, label_name, normalized_name) VALUES (?, ?, ?)",
            (account_id, label_name, normalized),
        )
        label_id = conn.execute(
            "SELECT id FROM labels WHERE account_id = ? AND label_name = ?",
            (account_id, label_name),
        ).fetchone()[0]
        conn.execute(
            "INSERT OR IGNORE INTO message_labels (account_id, message_db_id, label_id) VALUES (?, ?, ?)",
            (account_id, msg_db_id, label_id),
        )


def ingest_mbox(
    mbox_path: str | Path,
    *,
    config: dict[str, Any],
    db_path: Path,
    account_key: str,
    source_name: str | None = None,
    resume: bool = False,
    extract_attachments_flag: bool = False,
    force: bool = False,
    create_account_if_missing: bool = False,
) -> dict[str, Any]:
    if extract_attachments_flag:
        validate_account_key(account_key)
    mbox_path = Path(mbox_path).resolve()
    if not mbox_path.exists():
        raise FileNotFoundError(f"MBOX file not found: {mbox_path}")

    ensure_parent_dir(db_path)
    init_db(db_path)

    if source_name is None:
        source_name = mbox_path.stem

    batch_size = int(get_setting(config, "ingest.batch_commit_size"))
    attachments_dir = get_path(config, "paths.attachments_dir", fallback_on_empty=False)
    store_body_html = bool(get_setting(config, "ingest.store_body_html"))
    max_body_chars = int(get_setting(config, "ingest.max_body_chars"))
    if batch_size <= 0 or max_body_chars < 0:
        raise ValueError("batch_commit_size must be positive and max_body_chars nonnegative")

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    mbox = None
    created_paths: set[Path] = set()

    try:
        account = get_account(conn, account_key)
        if not account:
            if create_account_if_missing:
                from .accounts import create_account as _create_account
                _create_account(conn, account_key)
                account = get_account(conn, account_key)
                print(f"Created account: {account_key}")
            else:
                raise AccountError(
                    f"Account '{account_key}' not found.\n"
                    f"Run: mboxer account add {account_key}\n"
                    "Or pass --create-account to create it automatically."
                )

        account_id: int = account["id"]  # type: ignore[index]
        source_id, expected_source_hash = _get_or_create_source(
            conn, mbox_path, source_name, account_id, force=force
        )

        if force:
            print(
                "Warning: --force enabled; existing messages from this account/source may be replaced."
            )

        resume_run_id: int | None = None
        resume_key: str | None = None

        if resume and not force:
            existing = _get_resume_run(conn, source_id)
            if existing:
                resume_run_id, resume_key = existing
                print(f"Resuming run {resume_run_id} from key {resume_key!r}")

        if resume_run_id is not None:
            run_id = resume_run_id
            _update_run(conn, run_id, status="running")
            conn.commit()
        else:
            if not resume or force:
                conn.execute(
                    "UPDATE ingest_runs SET status = 'interrupted' "
                    "WHERE source_id = ? AND status = 'running'",
                    (source_id,),
                )
                conn.commit()
            run_id = _create_run(conn, source_id, account_id)

        counts: dict[str, Any] = {"seen": 0, "inserted": 0, "skipped": 0, "replaced": 0, "errors": 0}
        errors: list[dict[str, Any]] = []
        checkpoint_blocked = False

        def record_error(**details: Any) -> None:
            nonlocal checkpoint_blocked
            checkpoint_blocked = True
            counts["errors"] += 1
            event = dict(account_id=account_id, run_id=run_id, source_id=source_id, **details)
            errors.append(event)
            _record_ingest_error(conn, **event)

        def rollback_replacement(status: str) -> None:
            conn.rollback()
            for path in created_paths:
                path.unlink(missing_ok=True)
            created_paths.clear()
            counts["inserted"] = counts["replaced"] = 0
            counts["status"] = status
            for event in errors:
                _record_ingest_error(conn, **event)
            _update_run(
                conn, run_id, status=status, last_mbox_key=None,
                messages_seen=counts["seen"], messages_inserted=0,
                messages_skipped=counts["skipped"], errors_count=counts["errors"],
            )
            conn.execute("UPDATE ingest_runs SET finished_at = CURRENT_TIMESTAMP WHERE id = ?", (run_id,))
            conn.commit()

        mbox = mailbox.mbox(str(mbox_path), factory=None, create=False)
        try:
            keys = list(mbox.keys())
        except Exception as exc:
            _update_run(conn, run_id, status="failed")
            conn.commit()
            raise RuntimeError(f"Failed to open MBOX: {exc}") from exc

        if resume_key is not None and resume_key not in {str(key) for key in keys}:
            counts["errors"] += 1
            _record_ingest_error(
                conn,
                account_id=account_id,
                run_id=run_id,
                source_id=source_id,
                mbox_key=resume_key,
                error_type="InvalidResumeCheckpoint",
                error_message=(
                    f"Resume checkpoint {resume_key!r} was not found; restarted from beginning."
                ),
            )
            resume_key = None

        last_key_processed: str | None = resume_key
        past_resume_key = resume_key is None

        if not conn.in_transaction:
            conn.execute("BEGIN IMMEDIATE")
        if force:
            # Replacement starts from the complete source, including keys that
            # disappeared when an archive shrank. The entire transaction is
            # rolled back on any failed message or interruption.
            conn.execute(
                "DELETE FROM classifications WHERE account_id = ? "
                "AND target_type = 'thread' "
                "AND thread_key IN (SELECT thread_key FROM messages WHERE account_id = ? AND source_id = ?)",
                (account_id, account_id, source_id),
            )
            old_ids = conn.execute(
                "SELECT id FROM messages WHERE account_id = ? AND source_id = ?",
                (account_id, source_id),
            ).fetchall()
            for (old_id,) in old_ids:
                _delete_message_dependents(conn, old_id)
            counts["replaced"] = len(old_ids)
            conn.execute("DELETE FROM threads WHERE account_id = ? AND source_id = ?", (account_id, source_id))

        try:
            for mbox_key in keys:
                str_key = str(mbox_key)

                if not past_resume_key:
                    if str_key == resume_key:
                        past_resume_key = True
                    counts["skipped"] += 1
                    continue

                counts["seen"] += 1

                try:
                    raw_msg = mbox.get_message(mbox_key)
                except Exception as exc:  # noqa: BLE001 -- isolate malformed archive entries
                    record_error(
                        mbox_key=str_key,
                        error_type=type(exc).__name__,
                        error_message="Failed to read message from source MBOX.",
                    )
                    continue

                try:
                    record = normalize_message(raw_msg, source_id, str_key, account_id)
                except Exception as exc:  # noqa: BLE001 -- retain safe per-message failure evidence
                    record_error(
                        mbox_key=str_key,
                        error_type=type(exc).__name__,
                        error_message="Failed to normalize message.",
                    )
                    continue

                if not store_body_html:
                    record["body_html"] = None
                if record.get("body_text") and len(record["body_text"]) > max_body_chars:
                    record["body_text"] = record["body_text"][:max_body_chars]
                    body = record["body_text"]
                    record.update(body_hash=compute_body_hash(body), body_chars=len(body),
                                  body_word_count=len(body.split()))

                gmail_labels = record.pop("gmail_labels", [])

                if not conn.in_transaction:
                    conn.execute("BEGIN IMMEDIATE")
                conn.execute("SAVEPOINT message_write")
                msg_db_id = None
                try:
                    cursor = conn.execute(
                        """
                        INSERT INTO messages
                          (account_id, source_id, mbox_key, message_id, thread_key, subject, sender,
                           recipients_json, cc_json, bcc_json, date_header, date_utc,
                           body_text, body_html, body_hash, body_chars, body_word_count,
                           attachment_count, raw_headers_json)
                        VALUES
                          (:account_id, :source_id, :mbox_key, :message_id, :thread_key, :subject, :sender,
                           :recipients_json, :cc_json, :bcc_json, :date_header, :date_utc,
                           :body_text, :body_html, :body_hash, :body_chars, :body_word_count,
                           :attachment_count, :raw_headers_json)
                        ON CONFLICT(source_id, mbox_key) DO NOTHING
                        """,
                        record,
                    )
                    if cursor.rowcount > 0:
                        msg_db_id = cursor.lastrowid
                        if msg_db_id is None:
                            raise RuntimeError("INSERT succeeded but cursor.lastrowid is None")

                        if record.get("thread_key"):
                            if force:
                                # Keep untouched messages' inherited export
                                # restrictions until reclassification succeeds.
                                conn.execute(
                                    "DELETE FROM classifications WHERE account_id = ? AND thread_key = ? "
                                    "AND target_type = 'thread'",
                                    (account_id, record["thread_key"]),
                                )
                            participants = loads_address_list(record["recipients_json"])
                            if record.get("sender"):
                                participants = [record["sender"]] + participants
                            _upsert_thread(
                                conn, account_id, source_id,
                                record["thread_key"], record.get("subject"),
                                record.get("date_utc"), participants,
                            )

                        if gmail_labels:
                            _store_labels(conn, account_id, msg_db_id, gmail_labels)

                        if extract_attachments_flag and record.get("attachment_count", 0) > 0:
                            try:
                                attachments = extract_attachments(
                                    raw_msg, msg_db_id, source_id,
                                    account_id=account_id,
                                    account_key=account_key,
                                    date_utc=record.get("date_utc"),
                                    message_id=record.get("message_id") or str_key,
                                    attachments_dir=attachments_dir,
                                    conn=conn,
                                    extract_to_disk=True,
                                )
                                if any(a["extraction_status"] == "error" for a in attachments):
                                    raise AttachmentError("Attachment storage failed")
                            except Exception as exc:
                                raise AttachmentError("Attachment storage failed") from exc
                    if msg_db_id is not None:
                        created_paths.update(Path(row[0]) for row in conn.execute(
                            "SELECT storage_path FROM attachments WHERE message_db_id = ? AND storage_path IS NOT NULL",
                            (msg_db_id,),
                        ))
                    conn.execute("RELEASE message_write")
                    counts["inserted" if cursor.rowcount > 0 else "skipped"] += 1

                except BaseException as exc:
                    # Roll back incomplete evidence even on interrupt: the outer
                    # KeyboardInterrupt handler commits completed messages and
                    # the checkpoint. Non-Exception exits propagate after cleanup.
                    failed_paths = [Path(row[0]) for row in conn.execute(
                        "SELECT storage_path FROM attachments WHERE message_db_id = ? AND storage_path IS NOT NULL",
                        (msg_db_id,),
                    )] if msg_db_id is not None else []
                    conn.execute("ROLLBACK TO message_write")
                    conn.execute("RELEASE message_write")
                    for path in failed_paths:
                        path.unlink(missing_ok=True)
                    if not isinstance(exc, Exception):
                        raise
                    record_error(
                        mbox_key=str_key,
                        error_type=type(exc).__name__,
                        error_message="Failed to store normalized message evidence.",
                    )
                    continue

                if not checkpoint_blocked:
                    last_key_processed = str_key
                total_done = counts["inserted"] + counts["skipped"] + counts["errors"]
                if not force and total_done % batch_size == 0:
                    _update_run(
                        conn, run_id,
                        last_mbox_key=last_key_processed,
                        messages_seen=counts["seen"],
                        messages_inserted=counts["inserted"],
                        messages_skipped=counts["skipped"],
                        errors_count=counts["errors"],
                    )
                    conn.commit()
                    created_paths.clear()

        except KeyboardInterrupt:
            if force:
                rollback_replacement("interrupted")
                print("\nReplacement interrupted; previous source evidence retained. Rerun with --force.")
                return counts
            _update_run(
                conn, run_id, status="interrupted",
                last_mbox_key=last_key_processed,
                messages_seen=counts["seen"],
                messages_inserted=counts["inserted"],
                messages_skipped=counts["skipped"],
                errors_count=counts["errors"],
            )
            conn.commit()
            created_paths.clear()
            counts["status"] = "interrupted"
            print("\nInterrupted. Run with --resume to continue.")
            return counts

        if force:
            try:
                current_source_hash = _file_sha256(mbox_path)
                stat = mbox_path.stat()
            except OSError as exc:
                record_error(
                    mbox_key=None, error_type=type(exc).__name__,
                    error_message="Failed to verify source identity after replacement.",
                )
            except KeyboardInterrupt:
                rollback_replacement("interrupted")
                print("\nReplacement interrupted; previous source evidence retained. Rerun with --force.")
                return counts
            else:
                if current_source_hash != expected_source_hash:
                    record_error(mbox_key=None, error_type="SourceIdentityError",
                                 error_message="Source changed while replacement was running.")
                else:
                    conn.execute(
                        "UPDATE mbox_sources SET file_size = ?, file_sha256 = ?, source_mtime = ? WHERE id = ?",
                        (stat.st_size, expected_source_hash, stat.st_mtime, source_id),
                    )
            if counts["errors"]:
                rollback_replacement("failed")
                print("Replacement failed; previous source evidence retained. Rerun with --force.")
                return counts

        _update_run(
            conn, run_id, status="completed",
            last_mbox_key=last_key_processed,
            messages_seen=counts["seen"],
            messages_inserted=counts["inserted"],
            messages_skipped=counts["skipped"],
            errors_count=counts["errors"],
        )
        conn.execute(
            "UPDATE ingest_runs SET finished_at = CURRENT_TIMESTAMP WHERE id = ?", (run_id,)
        )
        conn.commit()
        created_paths.clear()
        counts["status"] = "completed"

        replaced_note = f" ({counts['replaced']} replaced)" if force and counts["replaced"] else ""
        print(
            f"Ingest complete [{account_key}]: {counts['inserted']} inserted{replaced_note}, "
            f"{counts['skipped']} skipped, {counts['errors']} errors"
        )
        return counts

    finally:
        conn.rollback()
        for path in created_paths:
            path.unlink(missing_ok=True)
        if mbox is not None:
            close = getattr(mbox, "close", None)
            if close:
                close()
        conn.close()
