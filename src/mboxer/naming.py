from __future__ import annotations

import re
from pathlib import Path

MAX_FILENAME_STEM = 160


def slugify(value: str, *, max_length: int = MAX_FILENAME_STEM) -> str:
    """Make a filesystem-safe lowercase slug."""
    value = value.strip().lower()
    value = value.replace("&", " and ")
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = re.sub(r"-+", "-", value).strip("-")
    if not value:
        value = "untitled"
    return value[:max_length].rstrip("-") or "untitled"


def normalize_category_path(path: str) -> str:
    """Normalize a category path into slash-delimited slugs."""
    parts = [slugify(part) for part in re.split(r"[/\\]+", path) if part.strip()]
    return "/".join(parts) or "general"


def category_to_directory(base: str | Path, category_path: str, date_band: str | None = None) -> Path:
    """Turn a category path into a directory under the export base."""
    out = Path(base)
    for part in normalize_category_path(category_path).split("/"):
        out /= part
    if date_band:
        out /= slugify(date_band, max_length=40)
    return out


def source_pack_filename(category_path: str, date_band: str, sequence: int, extension: str = "md") -> str:
    """Create a semantic NotebookLM source-pack filename."""
    category_slug = normalize_category_path(category_path).replace("/", "-")
    date_slug = slugify(date_band, max_length=40)
    stem = f"{category_slug}-{date_slug}-{sequence:03d}"
    stem = stem[:MAX_FILENAME_STEM].rstrip("-")
    return f"{stem}.{extension.lstrip('.')}"
