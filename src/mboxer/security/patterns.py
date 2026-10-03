"""Shared regex definitions for scanning and configured redaction."""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class RedactionRule:
    finding_type: str
    pattern: re.Pattern[str]
    config_key: str
    replacement: str


# Order is part of the existing scrub behavior for overlapping patterns.
REDACTION_RULES = (
    RedactionRule(
        "email_address",
        re.compile(r"\b[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}\b"),
        "redact_email_addresses", "[EMAIL REDACTED]",
    ),
    RedactionRule(
        "phone_number",
        re.compile(r"\b(?:\+?1[\s\-.]?)?\(?\d{3}\)?[\s\-.]?\d{3}[\s\-.]?\d{4}\b"),
        "redact_phone_numbers", "[PHONE REDACTED]",
    ),
    RedactionRule(
        "ssn_like", re.compile(r"\b\d{3}[-\s]\d{2}[-\s]\d{4}\b"),
        "redact_ssn_like_numbers", "[SSN REDACTED]",
    ),
    RedactionRule(
        "credit_card_like", re.compile(r"\b(?:\d{4}[\s\-]){3}\d{4}\b"),
        "redact_credit_card_like_numbers", "[CARD REDACTED]",
    ),
)
