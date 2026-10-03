from __future__ import annotations

from typing import Any

from .patterns import REDACTION_RULES


def scrub_text(text: str, config: dict[str, Any]) -> str:
    security = config.get("security") or {}
    for rule in REDACTION_RULES:
        if security.get(rule.config_key):
            text = rule.pattern.sub(rule.replacement, text)
    return text
