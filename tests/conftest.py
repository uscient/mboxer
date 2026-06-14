"""Shared pytest fixtures for the mboxer test suite.

Consolidates the per-file ``_make_mbox`` builders and ``CONFIG`` dicts (via
``_factories``) and adds a ``run_cli`` helper that drives ``mboxer.cli.main`` the
way the existing findings-gate tests do (monkeypatch argv -> call -> capture).
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

import pytest

# Ensure sibling helper modules (e.g. ``_factories``) are importable from both
# this conftest and the test modules, independent of pytest's import mode.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from mboxer.accounts import create_account  # noqa: E402
from mboxer.db import init_db  # noqa: E402

from _factories import base_config, make_attachment_message, make_mbox  # noqa: E402

SYNTHETIC_MBOX = Path(__file__).parent / "fixtures" / "synthetic.mbox"


@pytest.fixture
def tmp_db(tmp_path: Path) -> Path:
    """A freshly initialized SQLite database under tmp_path."""
    db_path = tmp_path / "mboxer.sqlite"
    init_db(db_path)
    return db_path


@pytest.fixture
def make_account(tmp_db: Path) -> Callable[..., int]:
    """Factory: create an account in ``tmp_db`` and return its row id."""
    def _make(account_key: str = "test-gmail", **kwargs: Any) -> int:
        conn = sqlite3.connect(tmp_db)
        try:
            return create_account(conn, account_key, **kwargs)
        finally:
            conn.close()
    return _make


@pytest.fixture
def mbox_factory(tmp_path: Path) -> Callable[..., Path]:
    """Factory: write messages to an mbox under tmp_path and return its path."""
    def _make(messages: list[str], name: str = "test.mbox") -> Path:
        path = tmp_path / name
        make_mbox(path, messages)
        return path
    return _make


@pytest.fixture
def config(tmp_path: Path) -> dict[str, Any]:
    """Base config with ``attachments_dir`` rooted under tmp_path.

    Use for tests that actually extract attachments; plain pipeline tests can use
    :func:`_factories.base_config` directly at module level.
    """
    cfg = base_config()
    cfg["paths"] = {"attachments_dir": str(tmp_path / "attachments")}
    return cfg


@pytest.fixture
def mime_factory() -> Callable[..., str]:
    """Factory returning :func:`_factories.make_attachment_message`."""
    return make_attachment_message


@pytest.fixture
def run_cli(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> Callable[..., SimpleNamespace]:
    """Invoke ``mboxer.cli.main(*args)`` and capture exit code + output.

    Generalizes the existing pattern (set ``sys.argv``, call ``main()``, catch
    ``SystemExit``). ``main()`` converts ``ConfigError``/``AccountError`` into
    ``SystemExit(<message>)``; that message is surfaced via ``.stderr`` so tests
    can assert on it. Returns ``SimpleNamespace(exit_code, stdout, stderr)``.
    """
    def _run(*args: Any) -> SimpleNamespace:
        from mboxer.cli import main

        monkeypatch.setattr(sys, "argv", ["mboxer", *[str(a) for a in args]])
        exit_code = 0
        err_extra = ""
        try:
            main()
        except SystemExit as exc:
            if isinstance(exc.code, int):
                exit_code = exc.code
            elif exc.code is None:
                exit_code = 0
            else:
                # main() raised SystemExit(str) for ConfigError/AccountError.
                exit_code = 1
                err_extra = str(exc.code)
        captured = capsys.readouterr()
        return SimpleNamespace(
            exit_code=exit_code,
            stdout=captured.out,
            stderr=captured.err + err_extra,
        )

    return _run
