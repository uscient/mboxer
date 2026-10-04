"""Complete rendered-source limits and bounded projection behavior."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest

from mboxer.accounts import create_account
from mboxer.config import ConfigError
from mboxer.db import init_db
from mboxer.exporters.notebooklm import export_notebooklm
from mboxer.limits import ExportLimitError, NotebookLMLimits, validate_notebooklm_limits
from mboxer.security.findings import ResidualFindingsBlocked


CONFIG = {"security": {"default_export_profile": "raw", "on_residual_findings": "allow"}}
LIMITS = NotebookLMLimits(
    "synthetic", 100, 0, 100, 100_000, 90_000, 10_000_000, 9_000_000, 1000,
)


class FixedDateTime:
    @classmethod
    def now(cls, tz=None):
        return datetime(2024, 1, 1, tzinfo=tz or timezone.utc)


@pytest.fixture
def archive(tmp_path, monkeypatch):
    monkeypatch.setattr("mboxer.exporters.notebooklm.datetime", FixedDateTime)
    db_path = tmp_path / "synthetic.sqlite"
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    aid = create_account(conn, "synthetic")
    conn.execute(
        "INSERT INTO mbox_sources (account_id, source_name, source_slug, file_path) "
        "VALUES (?, 'synthetic', 'synthetic', 'synthetic.mbox')", (aid,),
    )
    source_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    def add(*, body="Synthetic text.", category=None, profile="raw", date="2024-01-01", thread=None):
        index = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        cursor = conn.execute(
            "INSERT INTO messages "
            "(account_id, source_id, mbox_key, message_id, thread_key, subject, sender, "
            "date_utc, body_text, body_word_count) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (aid, source_id, str(index), f"message-{index}", thread or f"thread-{index}",
             f"Synthetic {index}", "synthetic-sender", date, body, len(body.split())),
        )
        if category is not None:
            conn.execute(
                "INSERT INTO classifications "
                "(account_id, message_db_id, category_path, export_profile, classifier_type) "
                "VALUES (?, ?, ?, ?, 'rule')", (aid, cursor.lastrowid, category, profile),
            )
        conn.commit()

    def export(out, limits=LIMITS, **kwargs):
        return export_notebooklm(conn, CONFIG, limits, out, account_id=aid,
                                 account_key="synthetic", db_path=str(db_path), **kwargs)

    yield add, export, conn
    conn.close()


def _packs(out):
    return sorted(out.rglob("*.md"))


def _assert_manifest_matches_bytes(result):
    rows = json.loads(Path(result["manifest_json"]).read_text())
    account_root = Path(result["manifest_json"]).parent
    for row in rows:
        path = account_root / row["category_path"] / row["date_band"] / row["generated_file"]
        content = path.read_bytes()
        assert row["byte_count"] == len(content)
        assert row["word_count"] == len(content.decode("utf-8").split())
        assert row["generated_sha256"] == hashlib.sha256(content).hexdigest()


@pytest.mark.parametrize("dimension", ["bytes", "words"])
def test_exact_full_rendered_limit_and_one_less_split(archive, tmp_path, dimension):
    add, export, _ = archive
    for index in range(10):
        add(body=f"Unique body {index}: 世界 🔒 café")
    baseline = tmp_path / "baseline"
    export(baseline)
    content = _packs(baseline)[0].read_bytes()
    count = len(content) if dimension == "bytes" else len(content.decode().split())
    field = f"max_{dimension}_per_source"
    exact = replace(LIMITS, **{field: count})
    result = export(tmp_path / "exact", exact)
    assert result["files_written"] == 1
    assert _packs(tmp_path / "exact")[0].read_bytes() == content
    _assert_manifest_matches_bytes(result)

    smaller = replace(exact, **{field: count - 1})
    result = export(tmp_path / "split", smaller)
    assert result["files_written"] == 2
    assert result["messages_exported"] == 10
    for path in _packs(tmp_path / "split"):
        payload = path.read_bytes()
        actual = len(payload) if dimension == "bytes" else len(payload.decode().split())
        assert actual <= count - 1
    _assert_manifest_matches_bytes(result)


@pytest.mark.parametrize("dry_run", [False, True])
@pytest.mark.parametrize("dimension", ["bytes", "words"])
def test_oversized_singleton_rejected_without_publishing(archive, tmp_path, dimension, dry_run):
    add, export, conn = archive
    add(body="Synthetic Unicode text: 🔒 世界 " * 12)
    baseline = tmp_path / "baseline"
    export(baseline)
    original = _packs(baseline)[0].read_bytes()
    count = len(original) if dimension == "bytes" else len(original.decode().split())
    limits = replace(LIMITS, **{f"max_{dimension}_per_source": count - 1})
    before = conn.execute("SELECT COUNT(*) FROM exports").fetchone()[0]
    with pytest.raises(ExportLimitError, match="rendered message cannot fit"):
        export(tmp_path / "rejected", limits, dry_run=dry_run)
    assert not (tmp_path / "rejected").exists()
    assert conn.execute("SELECT COUNT(*) FROM exports").fetchone()[0] == before
    assert _packs(baseline)[0].read_bytes() == original


@pytest.mark.parametrize("categories", [["same"] * 3, ["a", "b", "c"]])
@pytest.mark.parametrize("dry_run", [False, True])
def test_budget_applies_across_and_within_groups_without_truncation(
    archive, tmp_path, categories, dry_run,
):
    add, export, conn = archive
    for category in categories:
        add(category=category)
    limits = replace(LIMITS, max_sources=3, reserved_sources=1, max_messages_per_source=1)
    with pytest.raises(ExportLimitError, match="source budget exceeded"):
        export(tmp_path / "rejected", limits, dry_run=dry_run)
    assert not (tmp_path / "rejected").exists()
    assert conn.execute("SELECT COUNT(*) FROM exports").fetchone()[0] == 0


def test_soft_targets_yield_to_hard_source_budget(archive, tmp_path):
    add, export, _ = archive
    for _ in range(5):
        add()
    limits = replace(LIMITS, max_sources=1, target_words_per_source=1)
    result = export(tmp_path / "complete", limits)
    assert result["files_written"] == 1
    assert result["messages_exported"] == 5
    _assert_manifest_matches_bytes(result)


def test_dry_run_uses_actual_splitting_and_does_not_modify_db_or_live_output(archive, tmp_path):
    add, export, conn = archive
    for _ in range(5):
        add()
    limits = replace(LIMITS, max_messages_per_source=2)
    changes_before = conn.total_changes
    dry = export(tmp_path / "dry", limits, dry_run=True)
    assert not (tmp_path / "dry").exists()
    assert conn.total_changes == changes_before
    assert conn.execute("SELECT COUNT(*) FROM exports").fetchone()[0] == 0
    actual = export(tmp_path / "actual", limits)
    assert dry["would_write"] == actual["files_written"] == 3
    assert dry["would_export"] == actual["messages_exported"] == 5
    assert dry["budget_used"] == actual["budget_used"] == 3
    assert dry["groups"] == 1


def test_normalized_categories_merge_without_losing_original_message_order(archive, tmp_path):
    add, export, _ = archive
    add(category="Same Name", body="FIRST marker", date="2024-06-01")
    add(category="same-name", body="SECOND marker", date="2024-01-01")
    result = export(tmp_path / "out")
    assert result["groups"] == result["files_written"] == 1
    content = _packs(tmp_path / "out")[0].read_text()
    assert content.index("FIRST marker") < content.index("SECOND marker")
    assert "category: same-name" in content


def test_long_category_split_preserves_sequence_suffix(archive, tmp_path):
    add, export, _ = archive
    for index in range(3):
        add(category="a" * 160, body=f"Synthetic marker {index}")
    result = export(tmp_path / "out", replace(LIMITS, max_messages_per_source=1))
    paths = _packs(tmp_path / "out")
    assert result["files_written"] == len(paths) == 3
    assert {path.name[-11:] for path in paths} == {"2024-001.md", "2024-002.md", "2024-003.md"}
    assert all(len(path.stem) <= 160 for path in paths)
    _assert_manifest_matches_bytes(result)


def test_residual_block_covers_late_messages_before_any_budget_failure(archive, tmp_path):
    add, export, conn = archive
    add(body="Clean synthetic text")
    add(body="Call synthetic number 555-867-5309")
    limits = replace(LIMITS, max_sources=1, max_messages_per_source=1)
    with pytest.raises(ResidualFindingsBlocked) as error:
        export(tmp_path / "out", limits, findings_policy="block")
    assert error.value.counts == {"phone_number": 1}
    assert not (tmp_path / "out").exists()
    assert conn.execute("SELECT COUNT(*) FROM exports").fetchone()[0] == 0


def test_thread_counts_and_undated_group_survive_disk_projection(archive, tmp_path):
    add, export, _ = archive
    add(thread="shared", date=None)
    add(thread="shared", date=None)
    add(thread="different", date=None)
    result = export(tmp_path / "out")
    row = json.loads(Path(result["manifest_json"]).read_text())[0]
    assert row["date_band"] == "undated"
    assert row["thread_count"] == 2
    assert row["message_count"] == 3


def test_reexport_replaces_changed_categories_then_removes_all_excluded_packs(archive, tmp_path):
    add, export, conn = archive
    add(category="old-category", body="Synthetic prior pack")
    out = tmp_path / "out"
    export(out)
    old_path, = _packs(out)
    unrelated = out / "synthetic" / "notes.txt"
    unrelated.write_text("Keep this unrelated file")
    conn.execute("UPDATE classifications SET category_path = 'new-category'")
    conn.commit()
    export(out)
    assert not old_path.exists()
    assert len(_packs(out)) == 1
    assert "new-category" in _packs(out)[0].parts
    conn.execute("UPDATE classifications SET export_profile = 'exclude'")
    conn.commit()
    for _ in range(2):
        result = export(out)
        assert result["files_written"] == result["messages_exported"] == 0
        assert not _packs(out)
        assert json.loads(Path(result["manifest_json"]).read_text()) == []
    assert unrelated.read_text() == "Keep this unrelated file"


def test_reexport_refuses_user_modified_pack_without_adding_ledger_row(archive, tmp_path):
    from mboxer.exporters.publication import ExportPublicationError

    add, export, conn = archive
    add(category="general")
    out = tmp_path / "out"
    export(out)
    path, = _packs(out)
    path.write_text("User edited synthetic content")
    before = conn.execute("SELECT COUNT(*) FROM exports").fetchone()[0]
    with pytest.raises(ExportPublicationError, match="modified"):
        export(out)
    assert path.read_text() == "User edited synthetic content"
    assert conn.execute("SELECT COUNT(*) FROM exports").fetchone()[0] == before


@pytest.mark.parametrize("field", [
    "max_words_per_source", "max_bytes_per_source", "max_messages_per_source",
    "target_words_per_source", "target_bytes_per_source", "target_sources",
])
@pytest.mark.parametrize("value", [0, -1])
def test_nonpositive_packing_limits_rejected(field, value):
    with pytest.raises(ConfigError, match=f"{field} must be positive"):
        validate_notebooklm_limits(replace(LIMITS, **{field: value}))
