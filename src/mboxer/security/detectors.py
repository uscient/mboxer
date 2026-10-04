from __future__ import annotations

from typing import Any, Protocol

from .patterns import REDACTION_RULES

Finding = dict[str, Any]


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
        for rule in REDACTION_RULES:
            matches = rule.pattern.finditer(text)
            first = next(matches, None)
            if first is not None:
                out.append({
                    "finding_type": rule.finding_type,
                    "severity": "medium",
                    "detector": "regex",
                    "excerpt": first.group()[:100],
                    "count": 1 + sum(1 for _ in matches),
                    "kind": "regex",
                    "version": 1,
                })
        return out


REGISTRY: list[Detector] = [RegexDetector()]


def run_detectors(text: str) -> list[Finding]:
    return [finding for detector in REGISTRY for finding in detector.detect(text)]


def active_detector_descriptors() -> list[dict[str, Any]]:
    return [{"name": d.name, "kind": d.kind, "version": d.version} for d in REGISTRY]
