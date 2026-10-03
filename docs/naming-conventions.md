# Naming Conventions

## Project names

```text
GitHub repo:      uscient/mboxer
Python package:   mboxer
CLI command:      mboxer
SQLite default:   var/mboxer.sqlite
```

## Filesystem slugs

Generated category and message directory names use filesystem-safe slugs:

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

## Account directory names

Account keys are preserved exactly; they are not converted to slugs or silently
renamed. New keys must be a single portable directory component: nonempty, at
most 255 UTF-8 bytes, without path separators, control characters, Windows-reserved
characters or device names, or trailing dots/spaces. `.` and `..` are rejected.

Existing unsafe keys remain readable in SQLite and account commands. Attachment
extraction and exports reject them before writing output; changing an existing
identity requires an explicit repair. These checks do not isolate output from
pre-existing directory symlinks or make case-distinct account keys safe on a
case-insensitive filesystem. Use account keys that are distinct on the host
filesystem and output directories you control.

## JSONL manifest filenames

A JSONL export writes `<stem>.manifest.json` beside its output, replacing only
the final extension. For example, `messages.2024.jsonl` produces
`messages.2024.manifest.json`. An output named `messages.manifest.json` produces
`messages.manifest.manifest.json`, so its manifest cannot overwrite that output.

## Attachment storage

Pattern:

```text
data/attachments/<account-key>/<year>/<message-id-slug>/<safe-filename>
```

Example:

```text
data/attachments/primary-gmail/2024/message-001-example-com/invoice-2024-03.pdf
```

Never assume attachment filenames are safe or unique.
