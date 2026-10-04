"""Scanning and selective scrubbing agree on the supported sensitive text."""
import pytest

from mboxer.security.scan import scan_text
from mboxer.security.scrub import scrub_text


@pytest.mark.parametrize("finding_type,config_key,value,replacement", [
    ("email_address", "redact_email_addresses", "team+test@example.org", "[EMAIL REDACTED]"),
    ("phone_number", "redact_phone_numbers", "555-867-5309", "[PHONE REDACTED]"),
    ("ssn_like", "redact_ssn_like_numbers", "123-45-6789", "[SSN REDACTED]"),
    ("credit_card_like", "redact_credit_card_like_numbers", "4111 1111 1111 1111", "[CARD REDACTED]"),
])
def test_detected_values_follow_their_redaction_setting(finding_type, config_key, value, replacement):
    text = f"First: {value}; second: {value}."
    assert scan_text(text) == [{
        "finding_type": finding_type, "severity": "medium", "detector": "regex",
        "excerpt": value, "count": 2, "kind": "regex", "version": 1,
    }]
    assert scrub_text(text, {}) == text
    assert scrub_text(text, {"security": {config_key: False}}) == text
    scrubbed = scrub_text(text, {"security": {config_key: True}})
    assert scrubbed == f"First: {replacement}; second: {replacement}."
    assert scan_text(scrubbed) == []


def test_scan_retains_first_excerpt_and_counts_many_occurrences():
    text = "first@example.org " + "later@example.net " * 20000
    assert scan_text(text) == [{
        "finding_type": "email_address", "severity": "medium", "detector": "regex",
        "excerpt": "first@example.org", "count": 20001, "kind": "regex", "version": 1,
    }]


def test_selective_scrub_preserves_disabled_finding_types():
    text = "Contact team@example.org or 555-867-5309; SSN 123-45-6789."
    result = scrub_text(text, {"security": {"redact_phone_numbers": True}})
    assert result == "Contact team@example.org or [PHONE REDACTED]; SSN 123-45-6789."
    assert [finding["finding_type"] for finding in scan_text(result)] == [
        "email_address", "ssn_like",
    ]
