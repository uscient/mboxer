from __future__ import annotations

import re
from typing import Any, Protocol

Finding = dict[str, Any]

_PATTERNS = {
    "email_address": re.compile(r"\b[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}\b"),
    "phone_number": re.compile(r"\b(?:\+?1[\s\-.]?)?\(?\d{3}\)?[\s\-.]?\d{3}[\s\-.]?\d{4}\b"),
    "ssn_like": re.compile(r"\b\d{3}[-\s]\d{2}[-\s]\d{4}\b"),
    "credit_card_like": re.compile(r"\b(?:\d{4}[\s\-]){3}\d{4}\b"),
}


class Detector(Protocol):
    name: str
    version: int
    kind: str
    deterministic: bool

    def detect(self, text: str) -> list[Finding]: ...


class RegexDetector:
    name, version, kind, deterministic = "regex", 1, "regex", True

    def detect(self, text: str) -> list[Finding]:
        out: list[Finding] = []
        for finding_type, pattern in _PATTERNS.items():
            matches = pattern.findall(text)
            if matches:
                out.append({
                    "finding_type": finding_type,
                    "severity": "medium",
                    "detector": "regex",
                    "excerpt": matches[0][:100],
                    "count": len(matches),
                    "kind": "regex",
                    "version": 1,
                })
        return out


REGISTRY: list[Detector] = [RegexDetector()]


def run_detectors(text: str) -> list[Finding]:
    return [finding for detector in REGISTRY for finding in detector.detect(text)]


def active_detector_descriptors() -> list[dict[str, Any]]:
    return [{"name": d.name, "kind": d.kind, "version": d.version} for d in REGISTRY]
