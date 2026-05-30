from __future__ import annotations

import json
import sqlite3
import textwrap
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..limits import NotebookLMLimits
from ..naming import category_to_directory, normalize_category_path, source_pack_filename
from ..security.policy import is_exportable, metadata_only, needs_scrub, resolve_export_profile
from ..security.scrub import scrub_text


def _date_band(date_utc: str | None) -> str:
    if date_utc:
        try:
            return date_utc[:4]
        except Exception:
            pass
    return "undated"


def _render_message_md(record: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("---")
    if record.get("subject"):
        lines.append(f"subject: {record['subject']}")
    if record.get("sender"):
        lines.append(f"from: {record['sender']}")
    if record.get("date_utc"):
        lines.append(f"date: {record['date_utc']}")
    if record.get("message_id"):
        lines.append(f"message_id: {record['message_id']}")
    lines.append("---")
    lines.append("")
    body = (record.get("body_text") or "").strip()
    lines.append(body if body else "*(no body)*")
    lines.append("")
    return "\n".join(lines)


def _source_header(
    account_key: str,
    account_email: str | None,
    category_path: str,
    date_band: str,
    sequence: int,
    message_count: int,
    db_path: str,
) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    account_email_present = str(bool(account_email)).lower()
    source_database_present = str(bool(db_path)).lower()
    return textwrap.dedent(f"""\
        # mboxer export
        account: {account_key}
        account_email_present: {account_email_present}
        category: {category_path}
        date_band: {date_band}
        sequence: {sequence}
        messages: {message_count}
        exported_at: {now}
        source_database_present: {source_database_present}

        ---

    """).lstrip()


def _fetch_classified_messages(
    conn: sqlite3.Connection,
    account_id: int | None,
) -> list[dict[str, Any]]:
    if account_id is not None:
        rows = conn.execute(
            """
            SELECT m.id, m.message_id, m.thread_key, m.subject, m.sender,
                   m.date_utc, m.body_text, m.body_chars, m.body_word_count,
                   c.category_path, c.export_profile, c.sensitivity
            FROM messages m
            JOIN classifications c ON c.message_db_id = m.id
            WHERE c.target_type = 'message' AND m.account_id = ?
            ORDER BY c.category_path, m.date_utc NULLS LAST, m.id
            """,
            (account_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT m.id, m.message_id, m.thread_key, m.subject, m.sender,
                   m.date_utc, m.body_text, m.body_chars, m.body_word_count,
                   c.category_path, c.export_profile, c.sensitivity
            FROM messages m
            JOIN classifications c ON c.message_db_id = m.id
            WHERE c.target_type = 'message'
            ORDER BY c.category_path, m.date_utc NULLS LAST, m.id
            """
        ).fetchall()
    cols = [
        "id", "message_id", "thread_key", "subject", "sender",
        "date_utc", "body_text", "body_chars", "body_word_count",
        "category_path", "export_profile", "sensitivity",
    ]
    return [dict(zip(cols, row)) for row in rows]


def _fetch_unclassified_messages(
    conn: sqlite3.Connection,
    account_id: int | None,
) -> list[dict[str, Any]]:
    if account_id is not None:
        rows = conn.execute(
            """
            SELECT m.id, m.message_id, m.thread_key, m.subject, m.sender,
                   m.date_utc, m.body_text, m.body_chars, m.body_word_count
            FROM messages m
            LEFT JOIN classifications c ON c.message_db_id = m.id
            WHERE c.id IS NULL AND m.account_id = ?
            ORDER BY m.date_utc NULLS LAST, m.id
            """,
            (account_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT m.id, m.message_id, m.thread_key, m.subject, m.sender,
                   m.date_utc, m.body_text, m.body_chars, m.body_word_count
            FROM messages m
            LEFT JOIN classifications c ON c.message_db_id = m.id
            WHERE c.id IS NULL
            ORDER BY m.date_utc NULLS LAST, m.id
            """
        ).fetchall()
    cols = [
        "id", "message_id", "thread_key", "subject", "sender",
        "date_utc", "body_text", "body_chars", "body_word_count",
    ]
    return [
        {**dict(zip(cols, row)), "category_path": "unclassified", "export_profile": None, "sensitivity": None}
        for row in rows
    ]


def _prepare_records_for_export(
    records: list[dict[str, Any]],
    config: dict[str, Any],
    override_profile: str | None,
) -> list[dict[str, Any]]:
    """Apply export-profile filtering and scrubbing to every record.

    Returns only exportable records, each annotated with '_was_scrubbed'.
    When override_profile is set it applies to all records regardless of
    their per-record export_profile.
    """
    security = config.get("security") or {}
    config_default = security.get("default_export_profile", "raw")
    scrub_enabled = security.get("scrub_enabled", True)
    result: list[dict[str, Any]] = []
    for rec in records:
        effective = override_profile or resolve_export_profile(
            rec.get("export_profile"), config_default
        )
        if not is_exportable(effective):
            continue
        rec = dict(rec)
        was_scrubbed = False
        if scrub_enabled and needs_scrub(effective):
            original = rec.get("body_text") or ""
            scrubbed = scrub_text(original, config)
            was_scrubbed = scrubbed != original
            rec["body_text"] = scrubbed
        elif metadata_only(effective):
            rec["body_text"] = None
        rec["_was_scrubbed"] = was_scrubbed
        result.append(rec)
    return result


def _group_by_category_and_band(
    records: list[dict[str, Any]],
) -> dict[tuple[str, str], list[dict[str, Any]]]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for rec in records:
        key = (
            normalize_category_path(rec.get("category_path") or "unclassified"),
            _date_band(rec.get("date_utc")),
        )
        groups.setdefault(key, []).append(rec)
    return groups


class _SourceWriter:
    def __init__(
        self,
        out_dir: Path,
        account_key: str,
        account_email: str | None,
        category_path: str,
        date_band: str,
        limits: NotebookLMLimits,
        db_path: str,
    ) -> None:
        self.out_dir = out_dir
        self.account_key = account_key
        self.account_email = account_email
        self.category_path = category_path
        self.date_band = date_band
        self.limits = limits
        self.db_path = db_path
        self.sequence = 1
        self.current_words = 0
        self.current_bytes = 0
        self.current_msgs = 0
        self._buf: list[str] = []
        self._active = False
        self.file_stats: list[dict[str, Any]] = []
        self._current_thread_keys: set[str] = set()
        self._current_date_min: str | None = None
        self._current_date_max: str | None = None
        self._current_has_scrubbed: bool = False

    def _flush(self) -> None:
        if not self._active:
            return
        base = self.out_dir / self.account_key
        target_dir = category_to_directory(base, self.category_path, self.date_band)
        target_dir.mkdir(parents=True, exist_ok=True)
        fname = source_pack_filename(self.category_path, self.date_band, self.sequence)
        fpath = target_dir / fname
        header = _source_header(
            self.account_key, self.account_email,
            self.category_path, self.date_band,
            self.sequence, self.current_msgs, self.db_path,
        )
        fpath.write_text(header + "\n".join(self._buf), encoding="utf-8")
        self.file_stats.append({
            "path": fpath,
            "category_path": self.category_path,
            "date_band": self.date_band,
            "message_count": self.current_msgs,
            "thread_count": len(self._current_thread_keys),
            "word_count": self.current_words,
            "byte_count": fpath.stat().st_size,
            "date_min": self._current_date_min,
            "date_max": self._current_date_max,
            "contains_scrubbed_content": self._current_has_scrubbed,
        })
        self.sequence += 1
        self._buf = []
        self._active = False
        self.current_words = 0
        self.current_bytes = 0
        self.current_msgs = 0
        self._current_thread_keys = set()
        self._current_date_min = None
        self._current_date_max = None
        self._current_has_scrubbed = False

    def add_message(self, record: dict[str, Any]) -> None:
        chunk = _render_message_md(record)
        chunk_words = len(chunk.split())
        chunk_bytes = len(chunk.encode("utf-8"))

        should_split = self._active and (
            self.current_words + chunk_words > self.limits.max_words_per_source
            or self.current_bytes + chunk_bytes > self.limits.max_bytes_per_source
            or self.current_msgs + 1 > self.limits.max_messages_per_source
            or self.current_words >= self.limits.target_words_per_source
            or self.current_bytes >= self.limits.target_bytes_per_source
        )
        if should_split:
            self._flush()

        self._buf.append(chunk)
        self._active = True
        self.current_words += chunk_words
        self.current_bytes += chunk_bytes
        self.current_msgs += 1

        if record.get("_was_scrubbed"):
            self._current_has_scrubbed = True
        if record.get("thread_key"):
            self._current_thread_keys.add(record["thread_key"])
        date = record.get("date_utc")
        if date:
            if self._current_date_min is None or date < self._current_date_min:
                self._current_date_min = date
            if self._current_date_max is None or date > self._current_date_max:
                self._current_date_max = date

    def finish(self) -> list[dict[str, Any]]:
        if self._active:
            self._flush()
        return self.file_stats


def export_notebooklm(
    conn: sqlite3.Connection,
    config: dict[str, Any],
    limits: NotebookLMLimits,
    out_dir: Path,
    *,
    account_id: int | None = None,
    account_key: str = "default",
    account_email: str | None = None,
    account_display_name: str | None = None,
    export_profile: str | None = None,
    dry_run: bool = False,
    db_path: str = "",
    config_path: str | None = None,
    warnings: list[str] | None = None,
    include_unclassified: bool = True,
) -> dict[str, Any]:
    records = _fetch_classified_messages(conn, account_id)
    if include_unclassified:
        records += _fetch_unclassified_messages(conn, account_id)

    candidate_message_count = len(records)
    records = _prepare_records_for_export(records, config, export_profile)
    excluded_message_count = candidate_message_count - len(records)
    groups = _group_by_category_and_band(records)
    effective_budget = limits.effective_source_budget
    security = config.get("security") or {}
    security_profile = security.get("default_export_profile")
    effective_profile = export_profile or security_profile or "raw"
    notebooklm_config = (config.get("exports") or {}).get("notebooklm") or {}

    stats: dict[str, Any] = {
        "account_key": account_key,
        "groups": len(groups),
        "files_written": 0,
        "messages_exported": 0,
        "candidate_message_count": candidate_message_count,
        "excluded_message_count": excluded_message_count,
        "warnings_count": len(warnings or []),
        "budget_used": 0,
        "dry_run": dry_run,
    }

    if dry_run:
        stats["would_write"] = len(groups)
        stats["manifest_csv"] = str(out_dir / account_key / "manifest.csv")
        stats["manifest_json"] = str(out_dir / account_key / "manifest.json")
        return stats

    out_dir.mkdir(parents=True, exist_ok=True)
    export_id = _start_export_run(
        conn, "notebooklm", str(out_dir), effective_profile, limits.profile_name, account_id
    )

    all_file_stats: list[dict[str, Any]] = []
    budget_used = 0
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    for (cat_path, band), msgs in sorted(groups.items()):
        if budget_used >= effective_budget:
            break

        writer = _SourceWriter(
            out_dir, account_key, account_email, cat_path, band, limits, db_path
        )
        for msg in msgs:
            writer.add_message(msg)

        written = writer.finish()
        all_file_stats.extend(written)
        budget_used += len(written)
        stats["messages_exported"] += len(msgs)

        for fstat in written:
            # Local operational reference, not safe lineage/event metadata.
            conn.execute(
                "INSERT INTO export_items (account_id, export_id, output_file, category_path) "
                "VALUES (?, ?, ?, ?)",
                (account_id, export_id, str(fstat["path"]), cat_path),
            )

    conn.execute(
        "UPDATE exports SET status = 'completed', finished_at = CURRENT_TIMESTAMP, "
        "source_count = ?, message_count = ?, metadata_json = ? WHERE id = ?",
        (
            len(all_file_stats),
            stats["messages_exported"],
            _export_metadata_json(
                config=config,
                limits=limits,
                db_path=db_path,
                config_path=config_path,
                output_path=out_dir,
                account_key=account_key,
                account_display_name=account_display_name,
                account_email_address=account_email,
                export_profile=export_profile,
                effective_profile=effective_profile,
                candidate_message_count=candidate_message_count,
                excluded_message_count=excluded_message_count,
                file_count=len(all_file_stats),
                message_count=stats["messages_exported"],
                warnings=warnings,
            ),
            export_id,
        ),
    )
    conn.commit()

    from .manifest import (
        build_notebooklm_manifest_rows,
        security_manifest_posture,
        write_notebooklm_manifest,
    )
    scrub_enabled, redaction_policy = security_manifest_posture(config)
    manifest_rows = build_notebooklm_manifest_rows(
        all_file_stats,
        account_key=account_key,
        account_display_name=account_display_name,
        account_email_address=account_email,
        export_profile=export_profile,
        security_profile=security_profile,
        created_at=now,
        source_database_path=db_path,
        source_config_path=config_path,
        scrub_enabled=scrub_enabled,
        redaction_policy=redaction_policy,
        limit_profile=limits.profile_name,
        limit_settings=asdict(limits),
        split_strategy=notebooklm_config.get("split_strategy") or {},
        export_format=notebooklm_config.get("format") or {},
        candidate_message_count=candidate_message_count,
        excluded_message_count=excluded_message_count,
        warnings=warnings,
    )
    csv_path, json_path = write_notebooklm_manifest(out_dir, account_key, manifest_rows)

    stats["files_written"] = len(all_file_stats)
    stats["budget_used"] = budget_used
    stats["manifest_csv"] = str(csv_path)
    stats["manifest_json"] = str(json_path)
    return stats


def _export_metadata_json(
    *,
    config: dict[str, Any],
    limits: NotebookLMLimits,
    db_path: str,
    config_path: str | None,
    output_path: Path,
    account_key: str,
    account_display_name: str | None,
    account_email_address: str | None,
    export_profile: str | None,
    effective_profile: str,
    candidate_message_count: int,
    excluded_message_count: int,
    file_count: int,
    message_count: int,
    warnings: list[str] | None,
) -> str:
    from .manifest import build_safe_export_run_metadata, security_manifest_posture

    scrub_enabled, redaction_policy = security_manifest_posture(config)
    notebooklm_config = (config.get("exports") or {}).get("notebooklm") or {}
    metadata = build_safe_export_run_metadata(
        export_kind="notebooklm",
        account_key=account_key,
        account_display_name=account_display_name,
        account_email_address=account_email_address,
        source_database_path=db_path,
        source_config_path=config_path,
        output_path=output_path,
        export_profile=export_profile,
        effective_profile=effective_profile,
        security_profile=(config.get("security") or {}).get("default_export_profile"),
        scrub_enabled=scrub_enabled,
        redaction_policy=redaction_policy,
        limit_profile=limits.profile_name,
        limit_settings=asdict(limits),
        split_strategy=notebooklm_config.get("split_strategy") or {},
        export_format=notebooklm_config.get("format") or {},
        candidate_message_count=candidate_message_count,
        excluded_message_count=excluded_message_count,
        source_count=file_count,
        message_count=message_count,
        warnings=warnings,
    )
    return json.dumps(metadata, ensure_ascii=False, sort_keys=True)


def _start_export_run(
    conn: sqlite3.Connection,
    export_type: str,
    output_path: str,
    export_profile: str,
    profile: str,
    account_id: int | None,
) -> int:
    conn.execute(
        "INSERT INTO exports "
        "(account_id, export_type, export_profile, output_path, notebooklm_limit_profile) "
        "VALUES (?, ?, ?, ?, ?)",
        (account_id, export_type, export_profile, output_path, profile),
    )
    conn.commit()
    return conn.execute("SELECT last_insert_rowid()").fetchone()[0]
