"""Synthetic streaming, publication failure, and bounded payload regressions."""
from __future__ import annotations

import gc
import hashlib
import json
import sqlite3
import tracemalloc
from pathlib import Path

import pytest

from mboxer.accounts import create_account
from mboxer.db import init_db
from mboxer.exporters.jsonl import export_jsonl
from mboxer.exporters.publication import ExportPublicationError
from mboxer.security.findings import ResidualFindingsBlocked
from mboxer.security.scan import run_security_scan

CONFIG = {
    "security": {"default_export_profile": "raw", "on_residual_findings": "block"},
}


class CommitFailureConnection(sqlite3.Connection):
    fail_commit = False

    def commit(self):
        if self.fail_commit:
            raise sqlite3.OperationalError("synthetic commit failure")
        super().commit()


def seeded_db(tmp_path, count=6, body="Synthetic clean content.", thread_padding=0):
    path = tmp_path / "synthetic.sqlite"
    init_db(path)
    conn = sqlite3.connect(path, factory=CommitFailureConnection)
    account_id = create_account(conn, "synthetic")
    conn.execute(
        "INSERT INTO mbox_sources (id, account_id, source_name, source_slug, file_path) "
        "VALUES (1, ?, 'synthetic', 'synthetic', 'synthetic.mbox')", (account_id,),
    )
    conn.executemany(
        "INSERT INTO messages (source_id, account_id, mbox_key, message_id, thread_key, "
        "subject, sender, recipients_json, cc_json, bcc_json, date_utc, body_text, "
        "body_hash, body_chars, body_word_count) "
        "VALUES (1, ?, ?, ?, ?, 'Synthetic', 'sender@example.invalid', '[]', '[]', '[]', "
        "'2024-01-01', ?, ?, ?, ?)",
        (
            (account_id, str(index), f"synthetic-{index}@example.invalid",
             f"thread-{index}-" + "x" * thread_padding, body,
             hashlib.sha256(body.encode()).hexdigest(), len(body), len(body.split()))
            for index in range(count)
        ),
    )
    conn.commit()
    return conn, account_id


def publish(conn, account_id, out_path, config=None):
    return export_jsonl(
        conn, config or CONFIG, out_path, account_id=account_id, account_key="synthetic",
    )


def test_late_residual_block_preserves_prior_pair_and_ledger(tmp_path):
    conn, account_id = seeded_db(tmp_path, count=100)
    out = tmp_path / "published" / "messages.jsonl"
    try:
        original = publish(conn, account_id, out)
        manifest = Path(original["manifest_path"])
        prior = (out.read_bytes(), manifest.read_bytes())
        conn.execute("UPDATE messages SET body_text = 'Contact late@example.invalid' WHERE id = 100")
        conn.commit()
        with pytest.raises(ResidualFindingsBlocked, match="email_address"):
            publish(conn, account_id, out)
        assert (out.read_bytes(), manifest.read_bytes()) == prior
        assert conn.execute("SELECT COUNT(*) FROM exports").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM export_items").fetchone()[0] == 1
        assert not conn.in_transaction
        assert {p.name for p in out.parent.iterdir()} == {out.name, manifest.name}
    finally:
        conn.close()


def test_late_residual_block_creates_no_destination(tmp_path):
    conn, account_id = seeded_db(tmp_path, count=100)
    try:
        conn.execute("UPDATE messages SET body_text = 'Contact late@example.invalid' WHERE id = 100")
        conn.commit()
        out = tmp_path / "absent" / "messages.jsonl"
        with pytest.raises(ResidualFindingsBlocked):
            publish(conn, account_id, out)
        assert not out.parent.exists()
        assert conn.execute("SELECT COUNT(*) FROM exports").fetchone()[0] == 0
    finally:
        conn.close()


def test_failed_commit_restores_previous_files_and_rolls_back_new_ledger(tmp_path):
    conn, account_id = seeded_db(tmp_path)
    out = tmp_path / "published" / "messages.jsonl"
    try:
        original = publish(conn, account_id, out)
        manifest = Path(original["manifest_path"])
        prior = (out.read_bytes(), manifest.read_bytes())
        sibling = out.parent / "unrelated.txt"
        sibling.write_bytes(b"KEEP")
        conn.execute("UPDATE messages SET body_text = 'Changed clean content.'")
        conn.commit()
        conn.fail_commit = True
        with pytest.raises(ExportPublicationError, match="restored") as failure:
            publish(conn, account_id, out)
        assert isinstance(failure.value.__cause__, sqlite3.OperationalError)
        assert (out.read_bytes(), manifest.read_bytes()) == prior
        assert sibling.read_bytes() == b"KEEP"
        assert conn.execute("SELECT COUNT(*) FROM exports").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM export_items").fetchone()[0] == 1
        assert not conn.in_transaction
    finally:
        conn.close()


def test_stream_preserves_order_policy_and_exportable_thread_count(tmp_path):
    conn, account_id = seeded_db(tmp_path, count=6)
    try:
        conn.execute("UPDATE messages SET date_utc = NULL WHERE id = 2")
        conn.execute("UPDATE messages SET date_utc = '2023-01-01' WHERE id = 3")
        conn.execute("UPDATE messages SET thread_key = 'shared' WHERE id IN (1, 4)")
        conn.executemany(
            "INSERT INTO classifications (account_id, target_type, message_db_id, "
            "category_path, export_profile, classifier_type, confidence) "
            "VALUES (?, 'message', ?, 'synthetic', ?, 'rule', ?)",
            [(account_id, 5, "exclude", 1.0), (account_id, 5, "raw", 0.5),
             (account_id, 6, "metadata-only", 1.0)],
        )
        conn.commit()
        config = {**CONFIG, "exports": {"jsonl": {"include_classification": False}}}
        result = publish(conn, account_id, tmp_path / "messages.jsonl", config)
        records = [json.loads(line) for line in (tmp_path / "messages.jsonl").read_text().splitlines()]
        assert [record["id"] for record in records] == [3, 1, 4, 6, 2]
        assert all("classification" not in record for record in records)
        assert records[3]["body_text"] is None
        assert records[3]["body_word_count"] is None
        assert result["candidate_message_count"] == 6
        assert result["excluded_message_count"] == 1
        manifest = json.loads(Path(result["manifest_path"]).read_text())[0]
        assert manifest["thread_count"] == 4
        assert manifest["message_count"] == 5
        assert manifest["date_min"] == "2023-01-01"
        assert manifest["date_max"] == "2024-01-01"
        assert manifest["generated_sha256"] == hashlib.sha256(
            (tmp_path / "messages.jsonl").read_bytes()
        ).hexdigest()
    finally:
        conn.close()


def test_staged_manifest_retains_final_relative_lineage_paths(tmp_path, monkeypatch):
    conn, account_id = seeded_db(tmp_path)
    monkeypatch.chdir(tmp_path)
    try:
        result = publish(conn, account_id, Path("relative/messages.2024.jsonl"))
        manifest = json.loads(Path(result["manifest_path"]).read_text())[0]
        assert manifest["generated_path"] == "relative/messages.2024.jsonl"
        assert manifest["source_path"] == "relative/messages.2024.jsonl"
        ledger = conn.execute("SELECT output_file FROM export_items").fetchone()[0]
        assert ledger == "relative/messages.2024.jsonl"
        assert "mboxer-jsonl-" not in json.dumps(manifest)
    finally:
        conn.close()


@pytest.mark.parametrize("operation", ["jsonl", "scan"])
def test_python_payload_memory_does_not_grow_with_archive_size(tmp_path, operation):
    # About 16 MiB of payload plus 1 MiB of distinct thread names in the larger
    # case. Measure only the operation, not corpus construction. This catches
    # body fetchall(), retained projections, and a high-cardinality Python set;
    # native SQLite caches are outside tracemalloc and configured separately.
    peaks = []
    for count in (64, 2048):
        root = tmp_path / str(count)
        root.mkdir()
        conn, account_id = seeded_db(root, count, "synthetic clean words " * 390, 512)
        try:
            gc.collect()
            tracemalloc.start()
            if operation == "jsonl":
                result = publish(conn, account_id, root / "output.jsonl")
                assert result["messages_written"] == count
            else:
                assert run_security_scan(conn, CONFIG, account_id=account_id) == {
                    "scanned": count, "findings": 0,
                }
            peaks.append(tracemalloc.get_traced_memory()[1])
            tracemalloc.stop()
        finally:
            tracemalloc.stop()
            conn.close()
    assert peaks[1] < peaks[0] + 1_000_000
    assert peaks[1] < 4_000_000


def test_streamed_security_scan_preserves_account_scope_and_idempotence(tmp_path):
    conn, account_id = seeded_db(tmp_path, count=30, body="Call 555-867-5309.")
    try:
        other = create_account(conn, "other")
        conn.execute("UPDATE messages SET account_id = ? WHERE id > 20", (other,))
        conn.commit()
        assert run_security_scan(conn, CONFIG, account_id=account_id) == {
            "scanned": 20, "findings": 20,
        }
        assert run_security_scan(conn, CONFIG, account_id=account_id) == {
            "scanned": 20, "findings": 0,
        }
        assert conn.execute("SELECT COUNT(*) FROM security_findings WHERE account_id = ?", (other,)).fetchone()[0] == 0
    finally:
        conn.close()


def test_partial_pair_install_failure_restores_prior_generation(tmp_path, monkeypatch):
    from mboxer.exporters import publication

    conn, account_id = seeded_db(tmp_path)
    out = tmp_path / "published" / "messages.jsonl"
    try:
        original = publish(conn, account_id, out)
        manifest = Path(original["manifest_path"])
        previous = (out.read_bytes(), manifest.read_bytes())
        conn.execute("UPDATE messages SET body_text = 'Changed clean content.'")
        conn.commit()
        replace = publication.os.replace
        armed = True

        def fail_second_install(source, destination):
            nonlocal armed
            if armed and Path(destination) == manifest:
                armed = False
                raise OSError("synthetic second-file installation failure")
            return replace(source, destination)

        monkeypatch.setattr(publication.os, "replace", fail_second_install)
        with pytest.raises(ExportPublicationError, match="restored"):
            publish(conn, account_id, out)
        assert not armed
        assert (out.read_bytes(), manifest.read_bytes()) == previous
        assert conn.execute("SELECT COUNT(*) FROM exports").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM export_items").fetchone()[0] == 1
        assert not conn.in_transaction
    finally:
        conn.close()
