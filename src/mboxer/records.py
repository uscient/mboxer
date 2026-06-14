from __future__ import annotations

import json
from typing import Any

_ADDRESS_FIELDS = (
    ("recipients_json", "recipients"),
    ("cc_json", "cc"),
    ("bcc_json", "bcc"),
)


def loads_address_list(value: str) -> list[str]:
    """Decode a DB-backed address-list JSON value into a strict list of strings."""
    parsed = json.loads(value)
    if not isinstance(parsed, list):
        raise ValueError("address-list JSON must be an array")
    if not all(isinstance(item, str) for item in parsed):
        raise ValueError("address-list JSON elements must be strings")
    return parsed


def decode_address_fields(record: dict[str, Any]) -> dict[str, Any]:
    """Replace address-list JSON fields on a materialized row with typed lists."""
    for json_field, list_field in _ADDRESS_FIELDS:
        if json_field in record:
            record[list_field] = loads_address_list(record.pop(json_field))
    return record
