import sqlite3

import pytest

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


def _insert_proposal(
    conn: sqlite3.Connection,
    *,
    account_id: int | None = None,
    path: str = "finance/investments",
    display_name: str | None = None,
    status: str = "pending",
) -> int:
    conn.execute(
        "INSERT INTO category_proposals "
        "(account_id, proposed_path, display_name, reason, confidence, status) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (account_id, path, display_name, "synthetic proposal reason", 0.85, status),
    )
    conn.commit()
    return conn.execute("SELECT last_insert_rowid()").fetchone()[0]


def test_pending_proposal_does_not_create_category(db):
    proposal_id = _insert_proposal(db, path="Finance / Investments")

    cats = get_all_categories(db)
    proposal = db.execute(
        "SELECT status FROM category_proposals WHERE id = ?", (proposal_id,)
    ).fetchone()

    assert cats == []
    assert proposal[0] == "pending"


def test_rejected_proposal_does_not_create_category_and_records_review(db):
    proposal_id = _insert_proposal(db, path="finance/investments")

    reject_proposal(db, proposal_id, note="not a governed category")

    row = db.execute(
        "SELECT status, reviewed_at, reviewed_note FROM category_proposals WHERE id = ?",
        (proposal_id,),
    ).fetchone()
    cats = get_all_categories(db)

    assert row[0] == "rejected"
    assert row[1] is not None
    assert row[2] == "not a governed category"
    assert cats == []


def test_approved_proposal_creates_normalized_active_category_and_records_review(db):
    create_account(db, "test-acct")
    account_id = db.execute("SELECT id FROM accounts WHERE account_key = 'test-acct'").fetchone()[0]
    proposal_id = _insert_proposal(
        db,
        account_id=account_id,
        path=" Finance / Investments ",
        display_name="Investments",
    )

    path = approve_proposal(db, proposal_id, note="approved after review")

    assert path == "finance/investments"
    cat = db.execute(
        "SELECT account_id, path, display_name, is_locked, is_active "
        "FROM categories WHERE account_id = ? AND path = ?",
        (account_id, "finance/investments"),
    ).fetchone()
    proposal = db.execute(
        "SELECT status, reviewed_at, reviewed_note FROM category_proposals WHERE id = ?",
        (proposal_id,),
    ).fetchone()

    assert cat == (account_id, "finance/investments", "Investments", 0, 1)
    assert proposal[0] == "approved"
    assert proposal[1] is not None
    assert proposal[2] == "approved after review"


def test_approval_does_not_duplicate_or_mutate_existing_locked_category(db):
    seed_categories_from_config(db, CONFIG)
    before = db.execute(
        "SELECT id, display_name, is_locked, is_active FROM categories "
        "WHERE account_id IS NULL AND path = 'medical/hospital-billing'"
    ).fetchone()
    proposal_id = _insert_proposal(
        db,
        path="Medical / Hospital Billing",
        display_name="Different Name",
    )

    path = approve_proposal(db, proposal_id)

    rows = db.execute(
        "SELECT id, display_name, is_locked, is_active FROM categories "
        "WHERE account_id IS NULL AND path = 'medical/hospital-billing'"
    ).fetchall()
    assert path == "medical/hospital-billing"
    assert rows == [before]


def test_approval_reactivates_only_the_intended_existing_category(db):
    finance_id = ensure_category(db, "finance/investments")
    other_id = ensure_category(db, "finance/taxes")
    db.execute("UPDATE categories SET is_active = 0 WHERE id IN (?, ?)", (finance_id, other_id))
    db.commit()
    proposal_id = _insert_proposal(db, path="Finance / Investments")

    path = approve_proposal(db, proposal_id)

    rows = db.execute(
        "SELECT path, is_active FROM categories WHERE path LIKE 'finance/%' ORDER BY path"
    ).fetchall()
    assert path == "finance/investments"
    assert rows == [("finance/investments", 1), ("finance/taxes", 0)]


def test_reapproving_or_rerejecting_reviewed_proposal_fails_safely(db):
    approved_id = _insert_proposal(db, path="finance/investments")
    approve_proposal(db, approved_id)

    with pytest.raises(ValueError, match="No pending proposal"):
        approve_proposal(db, approved_id)
    with pytest.raises(ValueError, match="No pending proposal"):
        reject_proposal(db, approved_id)

    rejected_id = _insert_proposal(db, path="finance/taxes")
    reject_proposal(db, rejected_id)

    with pytest.raises(ValueError, match="No pending proposal"):
        reject_proposal(db, rejected_id)
    with pytest.raises(ValueError, match="No pending proposal"):
        approve_proposal(db, rejected_id)


def test_unknown_proposal_ids_fail_safely(db):
    with pytest.raises(ValueError, match="No pending proposal"):
        approve_proposal(db, 999)
    with pytest.raises(ValueError, match="No pending proposal"):
        reject_proposal(db, 999)
