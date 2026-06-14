"""Golden end-to-end pipeline test.

Drives the REAL CLI through the whole pipeline (init-db -> account -> ingest ->
classify -> security-scan -> export notebooklm + jsonl) on a fixed in-code corpus
and compares the full set of exported artifacts against a committed golden.

This is the full-wiring regression net, not exhaustive coverage — the units cover
the components. It is marked ``e2e`` so it stays out of the ``-m unit`` inner loop.

Volatile fields are normalized before comparison: tmp_path, ISO/SQLite timestamps,
SHA-256 digests, and the setuptools-scm tool version (which changes every commit).

Re-bless after an intentional output change:

    MBOXER_BLESS_GOLDEN=1 python -m pytest tests/test_e2e_pipeline.py
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest

from mboxer import __version__

GOLDEN = Path(__file__).parent / "golden" / "pipeline_export.json"
BLESS = os.environ.get("MBOXER_BLESS_GOLDEN") == "1"

# Fixed corpus chosen to exercise three distinct export postures via the shipped
# example-config rules: USPS (assign -> metadata-only, body dropped), a utility
# statement (assign_hint -> scrubbed), and an unmatched personal note carrying a
# phone number (default scrubbed -> redacted).
MESSAGES = [
    (
        "From: auto-reply@usps.com\nTo: user@example.com\n"
        "Subject: Your Informed Delivery Daily Digest\n"
        "Date: Mon, 01 Jan 2024 08:00:00 +0000\nMessage-ID: <golden-usps-1@usps.com>\n\n"
        "Here are the mail pieces scheduled for delivery today.\n"
    ),
    (
        "From: noreply@electric.example.com\nTo: user@example.com\n"
        "Subject: Your January Statement is Ready\n"
        "Date: Wed, 03 Jan 2024 09:00:00 +0000\nMessage-ID: <golden-util-1@electric.example.com>\n\n"
        "Your statement for January 2024 is now available. Amount due: 124.87 dollars.\n"
    ),
    (
        "From: friend@example.net\nTo: user@example.com\nSubject: Catching up\n"
        "Date: Thu, 04 Jan 2024 14:00:00 +0000\nMessage-ID: <golden-personal-1@example.net>\n\n"
        "Hey, been a while. Call me at 555-123-4567 this weekend.\n"
    ),
]

_TS_ISO = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z?")
_TS_SQL = re.compile(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}")
_SHA256 = re.compile(r"\b[0-9a-f]{64}\b")


def _normalize(text: str, tmp_path: Path) -> str:
    text = text.replace(str(tmp_path), "<TMP>")
    text = text.replace(__version__, "<VERSION>")
    text = _TS_ISO.sub("<TS>", text)
    text = _TS_SQL.sub("<TS>", text)
    text = _SHA256.sub("<SHA256>", text)
    return text


def _snapshot(out_dir: Path, tmp_path: Path) -> dict[str, str]:
    snap: dict[str, str] = {}
    for f in sorted(out_dir.rglob("*")):
        if f.is_file():
            rel = f.relative_to(out_dir).as_posix()
            snap[rel] = _normalize(f.read_text(encoding="utf-8"), tmp_path)
    return snap


@pytest.mark.e2e
def test_golden_pipeline(run_cli, cli_config, mbox_factory, tmp_path):
    mbox = mbox_factory(MESSAGES, name="golden.mbox")
    assert run_cli("init-db", "--config", cli_config).exit_code == 0
    assert run_cli("account", "add", "primary", "--email", "u@example.com",
                   "--config", cli_config).exit_code == 0
    assert run_cli("ingest", str(mbox), "--config", cli_config, "--account", "primary",
                   "--source-name", "golden").exit_code == 0
    assert run_cli("classify", "--config", cli_config, "--account", "primary",
                   "--level", "thread").exit_code == 0
    assert run_cli("security-scan", "--config", cli_config, "--account", "primary").exit_code == 0

    out = tmp_path / "export"
    assert run_cli("export", "notebooklm", "--config", cli_config, "--account", "primary",
                   "--profile", "ultra_safe", "--out", out).exit_code == 0
    assert run_cli("export", "jsonl", "--config", cli_config, "--account", "primary",
                   "--out", out / "messages.jsonl").exit_code == 0

    snapshot = _snapshot(out, tmp_path)

    if BLESS:
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_text(json.dumps(snapshot, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        pytest.skip(f"golden re-blessed: {GOLDEN}")

    assert GOLDEN.exists(), f"golden missing; regenerate with MBOXER_BLESS_GOLDEN=1 ({GOLDEN})"
    expected = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert snapshot == expected
