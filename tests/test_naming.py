from mboxer.naming import (
    category_to_directory,
    normalize_category_path,
    slugify,
    source_pack_filename,
)


def test_slugify():
    assert slugify("Legal / Smith & Jones") == "legal-smith-and-jones"


def test_category_path():
    assert normalize_category_path("Medical / Hospital Billing") == "medical/hospital-billing"


def test_source_pack_filename():
    assert source_pack_filename("Medical/Hospital Billing", "2024", 1) == "medical-hospital-billing-2024-001.md"


def test_category_path_blocks_export_directory_traversal(tmp_path):
    out = category_to_directory(tmp_path, "../Secrets\\Finance / .. / Tax", "2024/../../q1")

    assert out.is_relative_to(tmp_path)
    assert ".." not in out.relative_to(tmp_path).parts
    assert out.relative_to(tmp_path).parts == (
        "untitled",
        "secrets",
        "finance",
        "untitled",
        "tax",
        "2024-q1",
    )
