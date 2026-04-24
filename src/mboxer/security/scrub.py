from __future__ import annotations

import re
from typing import Any

_REDACTORS = {
    "ssn_like": (
        re.compile(r"\b\d{3}[-\s]\d{2}[-\s]\d{4}\b"),
        "[SSN REDACTED]",
    ),
    "credit_card_like": (
        re.compile(r"\b(?:\d{4}[\s\-]){3}\d{4}\b"),
        "[CARD REDACTED]",
    ),
    "phone_number": (
        re.compile(r"\b(?:\+?1[\s\-.]?)?\(?\d{3}\)?[\s\-.]?\d{3}[\s\-.]?\d{4}\b"),
        "[PHONE REDACTED]",
    ),
}


def scrub_text(text: str, config: dict[str, Any]) -> str:
    security = config.get("security", {})
    if security.get("redact_phone_numbers"):
        pattern, replacement = _REDACTORS["phone_number"]
        text = pattern.sub(replacement, text)
    if security.get("redact_ssn_like_numbers"):
        pattern, replacement = _REDACTORS["ssn_like"]
        text = pattern.sub(replacement, text)
    if security.get("redact_credit_card_like_numbers"):
        pattern, replacement = _REDACTORS["credit_card_like"]
        text = pattern.sub(replacement, text)
    return text
