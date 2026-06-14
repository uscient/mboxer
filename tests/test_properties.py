"""Property-based tests for the slug / filename safety boundary (Hypothesis).

These fuzz the security-relevant string sanitizers — naming.slugify,
naming.normalize_category_path, and attachments._safe_attachment_filename — with
adversarial input (unicode, control chars, path separators, traversal sequences,
encoded-word tokens) and assert invariants that must hold for EVERY input, not
just hand-picked cases. The point is the security boundary, so the invariants are
meaningful (no escape, allowed charset, bounded) rather than "doesn't crash".
"""
from __future__ import annotations

from pathlib import PurePosixPath

import pytest
from hypothesis import example, given, settings
from hypothesis import strategies as st

from mboxer.attachments import MAX_FILENAME_STEM as ATT_STEM
from mboxer.attachments import _safe_attachment_filename
from mboxer.naming import MAX_FILENAME_STEM as SLUG_STEM
from mboxer.naming import normalize_category_path, slugify

# Bounded for CI sanity; pure string work, so no per-example deadline.
SETTINGS = settings(max_examples=300, deadline=None)

# Adversarial text: control chars, separators, dots, unicode letters, etc.
ADVERSARIAL = st.text(st.characters(min_codepoint=0, max_codepoint=0x2FFF), max_size=300)

SLUG_ALLOWED = set("abcdefghijklmnopqrstuvwxyz0123456789-")


# ── slugify ───────────────────────────────────────────────────────────────────

@SETTINGS
@given(ADVERSARIAL)
@example("../../etc/passwd")
@example("..\\..\\windows")
@example("café résumé")
@example("=?utf-8?b?Y2Fmw6k=?=")
@example("\x00\x01\x02")
@example("")
@pytest.mark.unit
def test_slugify_invariants(s):
    out = slugify(s)
    assert out                                  # never empty (untitled fallback)
    assert set(out) <= SLUG_ALLOWED             # only lowercase alnum + hyphen
    assert "/" not in out and "\\" not in out   # no path separators
    assert ".." not in out                      # no traversal (no dots at all)
    assert not out.startswith("-") and not out.endswith("-")
    assert all(ord(c) >= 32 for c in out)       # no control / null bytes
    assert len(out) <= SLUG_STEM                # bounded
    assert slugify(out) == out                  # idempotent


@SETTINGS
@given(ADVERSARIAL, st.integers(min_value=8, max_value=400))
@pytest.mark.unit
def test_slugify_respects_max_length(s, n):
    assert len(slugify(s, max_length=n)) <= n


# ── normalize_category_path ────────────────────────────────────────────────────

@SETTINGS
@given(ADVERSARIAL)
@example("../../etc")
@example("Legal / Smith & Jones / Estate")
@example("a\\b\\c\\..\\..")
@pytest.mark.unit
def test_normalize_category_path_invariants(s):
    out = normalize_category_path(s)
    assert out                                  # never empty (general fallback)
    assert "\\" not in out                       # backslashes folded to '/'
    segments = out.split("/")
    assert ".." not in segments                 # no traversal segment
    for seg in segments:
        assert seg                               # no empty segments
        assert set(seg) <= SLUG_ALLOWED         # each segment is a clean slug
    assert not PurePosixPath(out).is_absolute()  # stays relative
    assert normalize_category_path(out) == out   # idempotent


# ── _safe_attachment_filename (the on-disk security boundary) ──────────────────

@SETTINGS
@given(st.one_of(st.none(), ADVERSARIAL), st.integers(min_value=0, max_value=99))
@example("../../etc/passwd", 0)
@example("....//....//x", 0)
@example(None, 3)
@example("", 0)
@example("\x00/\x01", 0)
@pytest.mark.unit
def test_safe_attachment_filename_cannot_escape_directory(name, idx):
    safe = _safe_attachment_filename(name, idx)
    assert safe                                  # never empty (attachment-<idx> fallback)
    assert "/" not in safe and "\\" not in safe   # a single path component
    assert "\x00" not in safe                     # no null byte
    assert all(ord(c) >= 32 for c in safe)        # no control chars
    assert len(safe) <= ATT_STEM + 11             # bounded (stem[:120] + '.' + ext<=10)
    # As a child of ANY base directory it stays inside that base (no traversal).
    base = PurePosixPath("/safe/base")
    assert (base / safe).parent == base
