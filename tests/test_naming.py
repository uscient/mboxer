from mboxer.naming import normalize_category_path, slugify, source_pack_filename


def test_slugify():
    assert slugify("Legal / Smith & Jones") == "legal-smith-and-jones"


def test_category_path():
    assert normalize_category_path("Medical / Hospital Billing") == "medical/hospital-billing"


def test_source_pack_filename():
    assert source_pack_filename("Medical/Hospital Billing", "2024", 1) == "medical-hospital-billing-2024-001.md"
