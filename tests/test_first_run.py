"""First-run workflow tests: synthetic fixture ingest, CLI account commands,
Ollama model resolution, account-scoped paths, and thread-level classification."""
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from mboxer.accounts import create_account
from mboxer.classify import run_rule_classification
from mboxer.config import OllamaConfigError, load_config, resolve_ollama_model
from mboxer.db import init_db
from mboxer.exporters.notebooklm import export_notebooklm
from mboxer.ingest import ingest_mbox
from mboxer.limits import resolve_notebooklm_limits

SYNTHETIC_MBOX = Path(__file__).parent / "fixtures" / "synthetic.mbox"
EXAMPLE_CONFIG_PATH = "config/mboxer.example.yaml"

# Shared config for ingest tests
INGEST_CONFIG = {
    "paths": {"attachments_dir": "/tmp/test-attachments"},
    "ingest": {"batch_commit_size": 10, "store_body_html": False, "max_body_chars": 50000},
}

CLASSIFY_CONFIG = {
    **INGEST_CONFIG,
    "taxonomy": {"locked_categories": ["postal/usps-informed-delivery"]},
    "rules": [
        {
            "name": "usps-informed-delivery",
            "match": {
                "from_contains": ["usps"],
                "subject_contains": ["informed delivery"],
            },
            "assign": {
                "category_path": "postal/usps-informed-delivery",
                "sensitivity": "medium",
                "export_profile": "metadata-only",
            },
        }
    ],
}


@pytest.fixture()
def db_primary(tmp_path):
    db_path = tmp_path / "mboxer.sqlite"
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    create_account(conn, "primary-gmail", email_address="user@example.com")
    conn.close()
    return db_path


# ── Synthetic fixture ────────────────────────────────────────────────────────

def test_synthetic_mbox_exists():
    assert SYNTHETIC_MBOX.exists(), f"Fixture missing: {SYNTHETIC_MBOX}"


def test_synthetic_mbox_message_count():
    import mailbox
    mbox = mailbox.mbox(str(SYNTHETIC_MBOX))
    assert len(list(mbox)) == 5


# ── Fresh init-db ────────────────────────────────────────────────────────────

def test_init_db_fresh(tmp_path):
    db_path = tmp_path / "fresh.sqlite"
    init_db(db_path)
    assert db_path.exists()
    conn = sqlite3.connect(db_path)
    versions = {r[0] for r in conn.execute("SELECT version FROM schema_migrations").fetchall()}
    conn.close()
    assert "001_initial" in versions
    assert "002_multi_account" in versions


# ── CLI: account add / list / show ───────────────────────────────────────────

def _run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "mboxer", *args],
        capture_output=True, text=True,
    )


def test_cli_account_add_and_list(tmp_path):
    db = str(tmp_path / "test.sqlite")
    r = _run_cli("account", "add", "primary-gmail",
                 "--display-name", "Primary Gmail",
                 "--email", "user@example.com",
                 "--db", db, "--config", EXAMPLE_CONFIG_PATH)
    assert r.returncode == 0, r.stderr
    assert "primary-gmail" in r.stdout

    r2 = _run_cli("account", "list", "--db", db, "--config", EXAMPLE_CONFIG_PATH)
    assert r2.returncode == 0
    assert "primary-gmail" in r2.stdout


def test_cli_account_show(tmp_path):
    db = str(tmp_path / "test.sqlite")
    _run_cli("account", "add", "primary-gmail",
             "--email", "user@example.com",
             "--db", db, "--config", EXAMPLE_CONFIG_PATH)

    r = _run_cli("account", "show", "primary-gmail",
                 "--db", db, "--config", EXAMPLE_CONFIG_PATH)
    assert r.returncode == 0
    assert "primary-gmail" in r.stdout
    assert "user@example.com" in r.stdout


# ── Synthetic MBOX ingest ────────────────────────────────────────────────────

def test_synthetic_ingest_primary_gmail(tmp_path, db_primary):
    counts = ingest_mbox(
        SYNTHETIC_MBOX,
        config=INGEST_CONFIG,
        db_path=db_primary,
        account_key="primary-gmail",
        source_name="Synthetic Test",
    )
    assert counts["inserted"] == 5
    assert counts["errors"] == 0


def test_synthetic_ingest_threads(tmp_path, db_primary):
    ingest_mbox(SYNTHETIC_MBOX, config=INGEST_CONFIG, db_path=db_primary, account_key="primary-gmail")
    conn = sqlite3.connect(db_primary)
    threads = conn.execute("SELECT COUNT(*) FROM threads").fetchone()[0]
    conn.close()
    # 5 messages: 2 in medical thread + 3 standalone = at least 4 threads
    assert threads >= 4


def test_synthetic_ingest_gmail_labels(tmp_path, db_primary):
    ingest_mbox(SYNTHETIC_MBOX, config=INGEST_CONFIG, db_path=db_primary, account_key="primary-gmail")
    conn = sqlite3.connect(db_primary)
    label_count = conn.execute("SELECT COUNT(*) FROM labels").fetchone()[0]
    conn.close()
    # Fixture has: Inbox, Important, Sent, Bills, Personal = 5 distinct labels
    assert label_count >= 4


def test_synthetic_ingest_idempotent(tmp_path, db_primary):
    ingest_mbox(SYNTHETIC_MBOX, config=INGEST_CONFIG, db_path=db_primary, account_key="primary-gmail")
    counts2 = ingest_mbox(SYNTHETIC_MBOX, config=INGEST_CONFIG, db_path=db_primary, account_key="primary-gmail")
    assert counts2["inserted"] == 0
    assert counts2["skipped"] == 5


# ── Account-scoped attachment path ───────────────────────────────────────────

def test_account_scoped_attachment_path(tmp_path):
    """Attachments must land under attachments_dir/<account-key>/."""
    from mboxer.attachments import attachment_output_path

    path = attachment_output_path(
        base_dir=tmp_path / "attachments",
        account_key="primary-gmail",
        date_str="2024-01-01",
        message_id="<test-001@example.com>",
        filename="invoice.pdf",
    )
    assert "primary-gmail" in path.parts, f"account-key missing from path: {path}"
    assert path.name == "invoice.pdf"


# ── Thread-level rule classification smoke test ──────────────────────────────

def test_thread_level_classification_smoke(tmp_path, db_primary):
    ingest_mbox(SYNTHETIC_MBOX, config=CLASSIFY_CONFIG, db_path=db_primary, account_key="primary-gmail")
    conn = sqlite3.connect(db_primary)
    try:
        account_id = conn.execute(
            "SELECT id FROM accounts WHERE account_key = 'primary-gmail'"
        ).fetchone()[0]
        result = run_rule_classification(conn, CLASSIFY_CONFIG, account_id=account_id, level="message")
        assert result["classified"] >= 1
        row = conn.execute(
            "SELECT category_path FROM classifications WHERE classifier_type = 'rule'"
        ).fetchone()
        assert row[0] == "postal/usps-informed-delivery"
    finally:
        conn.close()


# ── NotebookLM dry-run export ────────────────────────────────────────────────

def test_notebooklm_dry_run_synthetic(tmp_path, db_primary):
    ingest_mbox(SYNTHETIC_MBOX, config=INGEST_CONFIG, db_path=db_primary, account_key="primary-gmail")
    config = load_config(EXAMPLE_CONFIG_PATH)
    limits = resolve_notebooklm_limits(config, "ultra_safe")
    conn = sqlite3.connect(db_primary)
    try:
        account_id = conn.execute(
            "SELECT id FROM accounts WHERE account_key = 'primary-gmail'"
        ).fetchone()[0]
        stats = export_notebooklm(
            conn, INGEST_CONFIG, limits, tmp_path / "out",
            account_id=account_id, account_key="primary-gmail",
            account_email="user@example.com",
            dry_run=True, db_path=str(db_primary),
        )
    finally:
        conn.close()
    assert stats["dry_run"] is True
    assert not (tmp_path / "out").exists()


# ── Ollama model resolution ───────────────────────────────────────────────────

def test_ollama_model_from_config():
    config = load_config(EXAMPLE_CONFIG_PATH)
    model = resolve_ollama_model(config, role="classifier")
    assert model == "llama3.1:8b"


def test_ollama_model_cli_override():
    config = load_config(EXAMPLE_CONFIG_PATH)
    model = resolve_ollama_model(config, role="classifier", cli_model="mistral:7b")
    assert model == "mistral:7b"


def test_ollama_model_role_specific():
    config = {
        "classification": {
            "ollama": {
                "default_model": "llama3.1:8b",
                "models": {"summarizer": "phi3:mini"},
            }
        }
    }
    assert resolve_ollama_model(config, role="summarizer") == "phi3:mini"
    assert resolve_ollama_model(config, role="classifier") == "llama3.1:8b"


def test_ollama_model_fallback_to_default():
    config = {
        "classification": {
            "ollama": {
                "default_model": "llama3.1:8b",
                "models": {},
            }
        }
    }
    assert resolve_ollama_model(config, role="taxonomy_manager") == "llama3.1:8b"


def test_ollama_model_missing_raises():
    config = {"classification": {"ollama": {}}}
    with pytest.raises(OllamaConfigError, match="No Ollama model configured"):
        resolve_ollama_model(config, role="classifier")


def test_ollama_precedence_cli_beats_config():
    config = {
        "classification": {
            "ollama": {
                "default_model": "llama3.1:8b",
                "models": {"classifier": "phi3:mini"},
            }
        }
    }
    assert resolve_ollama_model(config, role="classifier", cli_model="gemma2:9b") == "gemma2:9b"
