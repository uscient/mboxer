# Naming Conventions

## Project names

```text
GitHub repo:      xormania/mboxer
Python package:   mboxer
CLI command:      mboxer
SQLite default:   var/mboxer.sqlite
```

## Filesystem slugs

All generated paths should use filesystem-safe slugs:

```text
lowercase
spaces → hyphens
slashes only for category hierarchy
remove punctuation unless useful
collapse repeated hyphens
limit filename length
```

Example:

```text
Legal / Smith & Jones / Estate Correspondence
```

becomes:

```text
legal/smith-jones/estate-correspondence/
```

## Category paths

Canonical category paths are slash-delimited lowercase slugs:

```text
medical/hospital-billing
postal/usps-informed-delivery
household/utilities/electric
family/recipient-family/correspondence
```

Category paths may become filesystem directories. Do not store display labels as primary identifiers.

## NotebookLM source pack filenames

Pattern:

```text
<top-category>-<topic>-<date-band>-<sequence>.md
```

Examples:

```text
medical-hospital-billing-2024-001.md
legal-law-firm-correspondence-2023-2024-001.md
postal-usps-informed-delivery-2022-2024-001.md
household-utilities-electric-2024-001.md
family-recipient-family-correspondence-2020-2024-001.md
```

The filename should remain meaningful even if the directory hierarchy is lost.

## Attachment storage

Pattern:

```text
data/attachments/<mbox-source-slug>/<message-hash>/<attachment-slug>
```

Example:

```text
data/attachments/main-archive/4f1d9a2c/invoice-2024-03.pdf
```

Never assume attachment filenames are safe or unique.
