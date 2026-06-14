from __future__ import annotations

from .scan import scan_text


class ResidualFindingsBlocked(Exception):
    """Raised when residual detected-sensitive items would be exported."""

    def __init__(self, counts: dict[str, int]) -> None:
        self.counts = dict(counts)
        super().__init__(f"export blocked: residual detected-sensitive items {self.counts}")


def residual_finding_types(projected_body: str | None) -> dict[str, int]:
    """Return counts by finding type for sensitive items still present in export text."""
    if not projected_body:
        return {}
    counts: dict[str, int] = {}
    for finding in scan_text(projected_body):
        finding_type = finding["finding_type"]
        counts[finding_type] = counts.get(finding_type, 0) + finding["count"]
    return counts


def merge_counts(into: dict[str, int], more: dict[str, int]) -> None:
    for key, value in more.items():
        into[key] = into.get(key, 0) + value
