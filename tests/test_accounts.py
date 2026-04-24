import sqlite3
import pytest
from mboxer.db import init_db
from mboxer.accounts import (
    AccountError,
    create_account,
    get_account,
    get_account_by_id,
    list_accounts,
    update_account,
    resolve_account,
    ensure_default_account,
)


@pytest.fixture()
def db(tmp_path):
    db_path = tmp_path / "test.sqlite"
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    yield conn
    conn.close()


def test_create_and_get(db):
    account_id = create_account(db, "dad-gmail", display_name="Dad Gmail", email_address="dad@example.com")
    assert isinstance(account_id, int)
    account = get_account(db, "dad-gmail")
    assert account is not None
    assert account["account_key"] == "dad-gmail"
    assert account["display_name"] == "Dad Gmail"
    assert account["email_address"] == "dad@example.com"
    assert account["provider"] == "gmail"


def test_get_by_id(db):
    account_id = create_account(db, "personal-gmail")
    account = get_account_by_id(db, account_id)
    assert account is not None
    assert account["account_key"] == "personal-gmail"


def test_get_missing_returns_none(db):
    assert get_account(db, "nonexistent") is None


def test_duplicate_key_raises(db):
    create_account(db, "test-account")
    with pytest.raises(Exception):
        create_account(db, "test-account")


def test_list_accounts(db):
    create_account(db, "alpha-gmail")
    create_account(db, "beta-gmail")
    accounts = list_accounts(db)
    keys = [a["account_key"] for a in accounts]
    assert "alpha-gmail" in keys
    assert "beta-gmail" in keys
    assert keys == sorted(keys)


def test_update_account(db):
    create_account(db, "test-acct")
    ok = update_account(db, "test-acct", display_name="Updated Name", email_address="new@example.com")
    assert ok
    account = get_account(db, "test-acct")
    assert account["display_name"] == "Updated Name"
    assert account["email_address"] == "new@example.com"


def test_update_nonexistent_returns_false(db):
    ok = update_account(db, "ghost", display_name="X")
    assert not ok


def test_resolve_account_explicit(db):
    create_account(db, "dad-gmail")
    account = resolve_account(db, "dad-gmail")
    assert account["account_key"] == "dad-gmail"


def test_resolve_account_explicit_not_found(db):
    with pytest.raises(AccountError, match="not found"):
        resolve_account(db, "nonexistent")


def test_resolve_account_sole_account(db, capsys):
    create_account(db, "only-gmail")
    account = resolve_account(db, None)
    assert account["account_key"] == "only-gmail"
    out = capsys.readouterr().out
    assert "only-gmail" in out


def test_resolve_account_zero_accounts(db):
    with pytest.raises(AccountError, match="none exist"):
        resolve_account(db, None)


def test_resolve_account_multiple_accounts(db):
    create_account(db, "dad-gmail")
    create_account(db, "personal-gmail")
    with pytest.raises(AccountError, match="--account"):
        resolve_account(db, None)


def test_ensure_default_account(db):
    account = ensure_default_account(db, "default-gmail")
    assert account["account_key"] == "default-gmail"
    account2 = ensure_default_account(db, "default-gmail")
    assert account["id"] == account2["id"]
