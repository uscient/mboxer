from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import textwrap
from collections.abc import Iterator
from contextlib import closing
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory, TemporaryFile
from typing import Any

from ..accounts import validate_account_key
from ..limits import ExportLimitError, NotebookLMLimits, validate_notebooklm_limits
from ..naming import category_to_directory, normalize_category_path, source_pack_filename
from ..security.findings import ResidualFindingsBlocked, merge_counts
from ..security.policy import default_export_profile, resolve_export_profile, resolve_findings_policy
from .classification import resolve_message_classification
from .manifest import (
    build_notebooklm_manifest_rows,
    build_safe_export_run_metadata,
    security_manifest_posture,
    write_notebooklm_manifest,
)
from .projection import prepare_projection
from .publication import publish_notebooklm


def _date_band(date_utc: str | None) -> str:
    return date_utc[:4] if date_utc else "undated"


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
    created_at: str | None = None,
) -> str:
    now = created_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
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


def _iter_messages(
    conn: sqlite3.Connection,
    account_id: int | None,
    include_unclassified: bool,
    config_default: str | None,
    override_profile: str | None,
) -> Iterator[dict[str, Any]]:
    # Never join bodies to all retained classifications: one message has one
    # effective policy, and the source cursor must not materialize bodies.
    query = """
        SELECT id, message_id, thread_key, subject, sender, date_utc, body_text
        FROM messages WHERE (? IS NULL OR account_id = ?)
    """
    cursor = conn.execute(query, (account_id, account_id))
    columns = [description[0] for description in cursor.description]
    try:
        for row in cursor:
            record = dict(zip(columns, row))
            classification = resolve_message_classification(
                conn, record["id"], config_default, override_profile=override_profile,
            )
            if classification is None and not include_unclassified:
                continue
            record.update(classification or {
                "category_path": "unclassified", "export_profile": None,
            })
            record["_unclassified"] = classification is None
            yield record
    finally:
        cursor.close()


def _spool_projection(
    conn: sqlite3.Connection,
    spool: sqlite3.Connection,
    config: dict[str, Any],
    account_id: int | None,
    include_unclassified: bool,
    export_profile: str | None,
) -> tuple[int, int, dict[str, int]]:
    # Keep SQLite's cache bounded; payloads and temporary sort structures live
    # on disk. Thread cardinality is tracked here rather than in a Python set.
    spool.execute("PRAGMA cache_size = -2048")
    spool.execute("PRAGMA temp_store = FILE")
    spool.execute("""
        CREATE TABLE projected (
            ordinal INTEGER PRIMARY KEY, category TEXT, band TEXT,
            phase INTEGER, original_category TEXT, date_utc TEXT,
            message_db_id INTEGER, chunk BLOB, words INTEGER,
            thread_key TEXT, scrubbed INTEGER
        )
    """)
    spool.execute("CREATE TABLE source_threads (thread_key TEXT PRIMARY KEY)")
    candidates = excluded = 0
    residual: dict[str, int] = {}
    config_default = (config.get("security") or {}).get("default_export_profile")
    for record in _iter_messages(
        conn, account_id, include_unclassified, config_default, export_profile,
    ):
        candidates += 1
        projected = prepare_projection(record, config, override_profile=export_profile)
        if projected is None:
            excluded += 1
            continue
        record = projected.record
        merge_counts(residual, projected.residual)
        chunk = _render_message_md(record)
        original_category = record.get("category_path") or "unclassified"
        spool.execute(
            "INSERT INTO projected VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                candidates, normalize_category_path(original_category),
                _date_band(record.get("date_utc")),
                int(record["_unclassified"]), original_category,
                record.get("date_utc"), record["id"], chunk.encode("utf-8"),
                len(chunk.split()), record.get("thread_key"), projected.was_scrubbed,
            ),
        )
    spool.execute("""
        CREATE INDEX projected_order ON projected
          (category, band, phase, original_category, date_utc IS NULL,
           date_utc, message_db_id, ordinal)
    """)
    spool.commit()
    return candidates, excluded, residual


class _SourceBudgetExceeded(ExportLimitError):
    """Internal signal allowing a retry without soft splitting targets."""


class _SourceWriter:
    """Pack one category/year using a disk body stream and exact rendered limits."""

    def __init__(
        self, work_dir: Path, stage_root: Path, out_dir: Path,
        account_key: str, account_email: str | None, category_path: str,
        date_band: str, limits: NotebookLMLimits, db_path: str,
        created_at: str, spool: sqlite3.Connection,
        file_stats: list[dict[str, Any]], staged: dict[str, Path], honor_targets: bool,
    ) -> None:
        self.stage_root, self.out_dir = stage_root, out_dir
        self.account_key, self.account_email = account_key, account_email
        self.category_path, self.date_band = category_path, date_band
        self.limits, self.db_path, self.created_at = limits, db_path, created_at
        self.spool, self.file_stats, self.staged = spool, file_stats, staged
        self.honor_targets = honor_targets
        self.sequence = 1
        self.body = TemporaryFile(mode="w+b", dir=work_dir)
        self._reset()

    def _reset(self) -> None:
        self.current_msgs = self.body_bytes = self.body_words = 0
        self.date_min: str | None = None
        self.date_max: str | None = None
        self.has_scrubbed = False
        self.spool.execute("DELETE FROM source_threads")
        self.body.seek(0)
        self.body.truncate()

    def _header(self, messages: int) -> bytes:
        return _source_header(
            self.account_key, self.account_email, self.category_path,
            self.date_band, self.sequence, messages, self.db_path, self.created_at,
        ).encode("utf-8")

    def _size(self, messages: int, body_bytes: int, body_words: int) -> tuple[int, int]:
        header = self._header(messages)
        return len(header) + body_bytes, len(header.decode("utf-8").split()) + body_words

    def _over_hard_limit(self, size: tuple[int, int], messages: int) -> bool:
        return (
            size[0] > self.limits.max_bytes_per_source
            or size[1] > self.limits.max_words_per_source
            or messages > self.limits.max_messages_per_source
        )

    def add_message(self, row: tuple[Any, ...]) -> None:
        chunk, words, thread_key, date, scrubbed = row
        separator = 1 if self.current_msgs else 0
        proposed = self._size(
            self.current_msgs + 1, self.body_bytes + separator + len(chunk),
            self.body_words + words,
        )
        current = self._size(self.current_msgs, self.body_bytes, self.body_words)
        at_target = self.honor_targets and (
            current[0] >= self.limits.target_bytes_per_source
            or current[1] >= self.limits.target_words_per_source
        )
        if self.current_msgs and (
            self._over_hard_limit(proposed, self.current_msgs + 1) or at_target
        ):
            self.flush()
            separator = 0
            proposed = self._size(1, len(chunk), words)
        if self._over_hard_limit(proposed, self.current_msgs + 1):
            raise ExportLimitError(
                "A rendered message cannot fit one NotebookLM source: "
                f"{proposed[0]} bytes / {proposed[1]} words; configured maxima are "
                f"{self.limits.max_bytes_per_source} bytes / "
                f"{self.limits.max_words_per_source} words. No export published."
            )
        if separator:
            self.body.write(b"\n")
        self.body.write(chunk)
        self.body_bytes += separator + len(chunk)
        self.body_words += words
        self.current_msgs += 1
        self.has_scrubbed = self.has_scrubbed or bool(scrubbed)
        if thread_key:
            self.spool.execute("INSERT OR IGNORE INTO source_threads VALUES (?)", (thread_key,))
        if date:
            self.date_min = min(self.date_min, date) if self.date_min else date
            self.date_max = max(self.date_max, date) if self.date_max else date

    def flush(self) -> None:
        if not self.current_msgs:
            return
        if len(self.file_stats) >= self.limits.effective_source_budget:
            raise _SourceBudgetExceeded(
                "NotebookLM source budget exceeded: the full export requires more than "
                f"{self.limits.effective_source_budget} sources. No export published."
            )
        relative_dir = category_to_directory(Path(), self.category_path, self.date_band)
        relative = relative_dir / source_pack_filename(
            self.category_path, self.date_band, self.sequence,
        )
        key = relative.as_posix()
        if key in self.staged:
            raise ExportLimitError("NotebookLM source paths collide. No export published.")
        path = self.stage_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        header = self._header(self.current_msgs)
        digest = hashlib.sha256(header)
        self.body.seek(0)
        with path.open("xb") as handle:
            handle.write(header)
            while chunk := self.body.read(1024 * 1024):
                handle.write(chunk)
                digest.update(chunk)
        byte_count, word_count = self._size(
            self.current_msgs, self.body_bytes, self.body_words,
        )
        self.file_stats.append({
            "path": self.out_dir / self.account_key / relative,
            "sha256": digest.hexdigest(),
            "category_path": self.category_path, "date_band": self.date_band,
            "message_count": self.current_msgs,
            "thread_count": self.spool.execute("SELECT COUNT(*) FROM source_threads").fetchone()[0],
            "word_count": word_count, "byte_count": byte_count,
            "date_min": self.date_min, "date_max": self.date_max,
            "contains_scrubbed_content": self.has_scrubbed,
        })
        self.staged[key] = path
        self.sequence += 1
        self._reset()

    def close(self) -> None:
        self.body.close()


def _pack_sources(
    spool: sqlite3.Connection, work_dir: Path, stage_root: Path, out_dir: Path,
    account_key: str, account_email: str | None, limits: NotebookLMLimits,
    db_path: str, created_at: str, *, honor_targets: bool = True,
) -> tuple[list[dict[str, Any]], dict[str, Path]]:
    file_stats: list[dict[str, Any]] = []
    staged: dict[str, Path] = {}
    cursor = spool.execute("""
        SELECT category, band, chunk, words, thread_key, date_utc, scrubbed
        FROM projected
        ORDER BY category, band, phase, original_category,
                 date_utc IS NULL, date_utc, message_db_id, ordinal
    """)
    writer: _SourceWriter | None = None
    group: tuple[str, str] | None = None
    try:
        for row in cursor:
            next_group = row[:2]
            if writer is None or next_group != group:
                if writer is not None:
                    writer.flush()
                    writer.close()
                group = next_group
                writer = _SourceWriter(
                    work_dir, stage_root, out_dir, account_key, account_email,
                    group[0], group[1], limits, db_path, created_at, spool,
                    file_stats, staged, honor_targets,
                )
            writer.add_message(row[2:])
        if writer is not None:
            writer.flush()
    finally:
        cursor.close()
        if writer is not None:
            writer.close()
    return file_stats, staged


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
    findings_policy: str | None = None,
) -> dict[str, Any]:
    validate_account_key(account_key)
    # CLI confirmation flags govern service safety recommendations; the actual
    # configured packing limits remain mandatory for every direct API call.
    validate_notebooklm_limits(limits, allow_full_source_budget=True, force=True)
    warnings = list(warnings or [])
    security = config.get("security") or {}
    policy = resolve_findings_policy(security.get("on_residual_findings"), override=findings_policy)
    security_profile = default_export_profile(security.get("default_export_profile"))
    effective_profile = resolve_export_profile(export_profile, security_profile)
    notebooklm_config = (config.get("exports") or {}).get("notebooklm") or {}
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    conn.execute("SAVEPOINT notebooklm_export")
    try:
        with TemporaryDirectory(prefix="mboxer-notebooklm-") as temporary:
            work_dir = Path(temporary)
            stage_root = work_dir / "stage" / account_key
            with closing(sqlite3.connect(work_dir / "projection.sqlite")) as spool:
                candidates, excluded, residual = _spool_projection(
                    conn, spool, config, account_id, include_unclassified, export_profile,
                )
                if policy == "block" and residual:
                    raise ResidualFindingsBlocked(residual)
                if policy == "warn" and residual:
                    warnings.append(f"residual detected-sensitive items in export: {residual}")
                groups = spool.execute(
                    "SELECT COUNT(*) FROM (SELECT 1 FROM projected GROUP BY category, band)"
                ).fetchone()[0]
                try:
                    file_stats, staged = _pack_sources(
                        spool, work_dir, stage_root, out_dir, account_key, account_email,
                        limits, db_path, now,
                    )
                except _SourceBudgetExceeded:
                    # Soft targets yield to the hard source budget. Repack the
                    # already projected spool; do not silently omit any messages.
                    if stage_root.exists():
                        shutil.rmtree(stage_root)
                    file_stats, staged = _pack_sources(
                        spool, work_dir, stage_root, out_dir, account_key, account_email,
                        limits, db_path, now, honor_targets=False,
                    )

            stats: dict[str, Any] = {
                "account_key": account_key, "groups": groups,
                "files_written": 0, "messages_exported": candidates - excluded,
                "candidate_message_count": candidates, "excluded_message_count": excluded,
                "warnings_count": len(warnings), "warnings": warnings,
                "residual_findings": residual, "residual_findings_total": sum(residual.values()),
                "residual_findings_policy": policy, "budget_used": len(file_stats),
                "dry_run": dry_run,
                "manifest_csv": str(out_dir / account_key / "manifest.csv"),
                "manifest_json": str(out_dir / account_key / "manifest.json"),
            }
            if dry_run:
                stats["would_write"] = len(file_stats)
                stats["would_export"] = candidates - excluded
                return stats

            scrub_enabled, redaction_policy = security_manifest_posture(config)
            lineage: dict[str, Any] = dict(
                account_key=account_key, account_display_name=account_display_name,
                account_email_address=account_email, export_profile=export_profile,
                security_profile=security_profile,
                source_database_path=db_path, source_config_path=config_path,
                scrub_enabled=scrub_enabled, redaction_policy=redaction_policy,
                limit_profile=limits.profile_name, limit_settings=asdict(limits),
                split_strategy=notebooklm_config.get("split_strategy") or {},
                export_format=notebooklm_config.get("format") or {},
                candidate_message_count=candidates, excluded_message_count=excluded,
                warnings=warnings, residual_scan_performed=True,
                residual_findings_total=sum(residual.values()), residual_findings_by_type=residual,
                residual_findings_policy=policy,
            )
            manifest_rows = build_notebooklm_manifest_rows(file_stats, **lineage, created_at=now)
            csv_path, json_path = write_notebooklm_manifest(stage_root.parent, account_key, manifest_rows)
            staged["manifest.csv"], staged["manifest.json"] = csv_path, json_path
            metadata = build_safe_export_run_metadata(
                **lineage, export_kind="notebooklm", output_path=out_dir,
                effective_profile=effective_profile, source_count=len(file_stats),
                message_count=candidates - excluded,
            )
            cursor = conn.execute(
                "INSERT INTO exports "
                "(account_id, export_type, export_profile, output_path, notebooklm_limit_profile, "
                "status, finished_at, source_count, message_count, metadata_json) "
                "VALUES (?, 'notebooklm', ?, ?, ?, 'completed', CURRENT_TIMESTAMP, ?, ?, ?)",
                (account_id, effective_profile, str(out_dir), limits.profile_name,
                 len(file_stats), candidates - excluded,
                 json.dumps(metadata, ensure_ascii=False, sort_keys=True)),
            )
            export_id = cursor.lastrowid
            for stat in file_stats:
                conn.execute(
                    "INSERT INTO export_items (account_id, export_id, output_file, category_path) "
                    "VALUES (?, ?, ?, ?)",
                    (account_id, export_id, str(stat["path"]), stat["category_path"]),
                )
            publish_notebooklm(out_dir / account_key, staged, commit=conn.commit)
            stats["files_written"] = len(file_stats)
            return stats
    finally:
        # Successful publication commits the transaction. Dry runs and failures
        # release only this savepoint, preserving any earlier caller changes.
        if conn.in_transaction:
            conn.execute("ROLLBACK TO notebooklm_export")
            conn.execute("RELEASE notebooklm_export")
