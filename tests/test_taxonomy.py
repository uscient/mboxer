import sqlite3
from mboxer.db import init_db
from mboxer.accounts import create_account
from mboxer.taxonomy import (
    seed_categories_from_config,
    ensure_category,
    get_all_categories,
    approve_proposal,
    reject_proposal,
)


CONFIG = {
    "taxonomy": {
        "locked_categories": ["medical", "medical/hospital-billing", "legal", "household/utilities"]
    }
}


import pytest


@pytest.fixture()
def db(tmp_path):
    db_path = tmp_path / "test.sqlite"
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    yield conn
    conn.close()


def test_seed_global_categories(db):
    added = seed_categories_from_config(db, CONFIG)
    assert added == 4
    cats = get_all_categories(db)
    paths = {c["path"] for c in cats}
    assert "medical" in paths
    assert "medical/hospital-billing" in paths
    all_global = all(c["is_global"] for c in cats)
    assert all_global


def test_seed_idempotent(db):
    seed_categories_from_config(db, CONFIG)
    added2 = seed_categories_from_config(db, CONFIG)
    assert added2 == 0


def test_seed_account_specific(db):
    create_account(db, "dad-gmail")
    account_id = db.execute("SELECT id FROM accounts WHERE account_key = 'dad-gmail'").fetchone()[0]
    added = seed_categories_from_config(db, CONFIG, account_id=account_id)
    assert added == 4
    cats = get_all_categories(db, account_id, include_global=False)
    assert all(not c["is_global"] for c in cats)


def test_global_and_account_categories_coexist(db):
    """Same path can exist as global AND as account-specific."""
    create_account(db, "dad-gmail")
    account_id = db.execute("SELECT id FROM accounts WHERE account_key = 'dad-gmail'").fetchone()[0]
    ensure_category(db, "legal/correspondence")
    ensure_category(db, "legal/correspondence", account_id=account_id)

    cats = get_all_categories(db, account_id)
    matches = [c for c in cats if c["path"] == "legal/correspondence"]
    assert len(matches) == 2
    scopes = {c["is_global"] for c in matches}
    assert True in scopes and False in scopes


def test_ensure_category_idempotent(db):
    cat_id = ensure_category(db, "personal/journal")
    cat_id2 = ensure_category(db, "personal/journal")
    assert cat_id == cat_id2


def test_category_proposals_are_account_scoped(db):
    create_account(db, "dad-gmail")
    account_id = db.execute("SELECT id FROM accounts WHERE account_key = 'dad-gmail'").fetchone()[0]
    db.execute(
        "INSERT INTO category_proposals (account_id, proposed_path, reason, confidence, status) "
        "VALUES (?, ?, ?, ?, 'pending')",
        (account_id, "finance/investments", "Detected brokerage emails", 0.85),
    )
    db.commit()

    from mboxer.taxonomy import list_pending_proposals
    proposals = list_pending_proposals(db, account_id)
    assert len(proposals) == 1
    assert proposals[0]["proposed_path"] == "finance/investments"

    # Proposals for this account don't show up in another account's view
    create_account(db, "personal-gmail")
    personal_id = db.execute(
        "SELECT id FROM accounts WHERE account_key = 'personal-gmail'"
    ).fetchone()[0]
    personal_proposals = list_pending_proposals(db, personal_id)
    assert len(personal_proposals) == 0


def test_approve_proposal(db):
    create_account(db, "test-acct")
    account_id = db.execute("SELECT id FROM accounts WHERE account_key = 'test-acct'").fetchone()[0]
    db.execute(
        "INSERT INTO category_proposals (account_id, proposed_path, reason, confidence, status) "
        "VALUES (?, ?, ?, ?, 'pending')",
        (account_id, "finance/investments", "Reason", 0.85),
    )
    db.commit()
    proposal_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    path = approve_proposal(db, proposal_id)
    assert path == "finance/investments"
    row = db.execute("SELECT status FROM category_proposals WHERE id = ?", (proposal_id,)).fetchone()
    assert row[0] == "approved"
