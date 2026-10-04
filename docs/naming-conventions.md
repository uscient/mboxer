# Naming conventions

## Project identifiers and defaults

| Item | Value |
|---|---|
| GitHub repository | `uscient/mboxer` |
| Distribution name | `uscient-mboxer` |
| Python package and CLI | `mboxer` |
| Default database | `var/mboxer.sqlite` |
| Default attachment root | `data/attachments` |
| Default NotebookLM root | `exports/notebooklm` |
| Default JSONL output | `exports/rag/messages.jsonl` |

Paths are configurable; see [configuration](configuration.md).

## Slugs and category paths

`slugify` lowercases text, expands `&` to `and`, replaces runs of characters
outside ASCII letters and digits with a hyphen, and strips edge hyphens. An empty
result becomes `untitled`. This is normalization, not Unicode transliteration:
non-ASCII text can lose information or collide with another slug.

Category paths split on forward or backward slashes, discard blank segments,
and slug each remaining component. Components are limited to 160 characters.
A path with no nonblank segments becomes `general`; punctuation-only components
become `untitled`. Category paths are identifiers that can become directories,
not unsanitized display labels.

For example:

```text
Legal / Smith & Jones / Estate Correspondence
```

becomes:

```text
legal/smith-and-jones/estate-correspondence/
```

Other paths include `medical/hospital-billing`,
`postal/usps-informed-delivery`, and `household/utilities/electric`.

## NotebookLM packs

The current exporter groups messages by normalized category and UTC year.
Missing dates use `undated`. It writes:

```text
<notebooklm-root>/<account-key>/<category-path>/<year-or-undated>/<filename>.md
```

The filename flattens the category hierarchy with hyphens, appends the date band,
and ends with a sequence number starting at `001` for each category/date group.
The number has at least three digits; it continues beyond `999`. Examples:

```text
medical-hospital-billing-2024-001.md
legal-law-firm-correspondence-2023-001.md
postal-usps-informed-delivery-2022-002.md
household-utilities-electric-undated-001.md
```

The filename stem is limited to 160 characters by shortening the category
prefix; the date/sequence suffix is retained. Date-band slugs are limited to
40 characters, though the current exporter emits only a year or `undated`.
Markdown extension, category folders, and year grouping are current fixed
behavior. The similarly named `format` and `split_strategy` configuration fields
are descriptive manifest metadata, not switches that change that behavior.

Each account directory also contains `manifest.csv`, `manifest.json`, and a
`.mboxer-notebooklm.json` ownership marker. Publication detects conflicting
staged paths and refuses to overwrite unrelated files or modified owned packs; see
[packing and publication](notebooklm-limits.md).

## Account directory names

Account keys are preserved exactly; they are not converted to slugs or silently
renamed. New keys must be a single portable directory component: nonempty, at
most 255 UTF-8 bytes, without path separators, nonprintable characters,
Windows-reserved characters or device names, or trailing dots/spaces.
`.` and `..` are rejected.

Existing unsafe keys remain readable in SQLite and account commands. Attachment
extraction and exports reject them before writing output; changing an existing
identity requires an explicit repair. Key validation does not distinguish
case-equivalent names on case-insensitive filesystems. Attachment extraction also
does not reject pre-existing symlinks in its parent directories; export
publication checks its destination and parents for symlinks. Use distinct account
keys and output directories you control.

## JSONL manifests

A JSONL export writes `<stem>.manifest.json` beside its output, replacing only
the final extension. For example, `messages.2024.jsonl` produces
`messages.2024.manifest.json`. An output named `messages.manifest.json` produces
`messages.manifest.manifest.json`, so its manifest cannot overwrite that output.

## Attachment storage

Ingest uses:

```text
<attachments-root>/<account-key>/<year-or-undated>/<message-id-slug>/<safe-filename>
```

For example:

```text
data/attachments/primary-gmail/2024/message-001-example-com/invoice-2024-03.pdf
```

The message directory is a slug limited to 60 characters. If the message has no
Message-ID, ingest uses its MBOX key as the directory input. Attachments from
different messages or sources can share a directory when those inputs collide;
the database retains their message/source association.

Attachment filenames use separate rules from directory slugs. Unicode letters
and numbers, underscores, periods, and hyphens are retained; other characters
become underscores. Leading/trailing periods and underscores are stripped before
length trimming, and repeated underscores collapse. An empty or absent name
becomes `attachment-<index>`, using the zero-based attachment index in its message.

The existing character limit is applied first: names longer than 130 characters
keep up to 120 stem characters and an extension of at most 10 characters when
available; otherwise they keep the first 120 characters. A second limit fits the
component within 255 UTF-8 bytes without splitting a Unicode character. It
preserves an extension when at least one stem character still fits, and otherwise
truncates the whole name. Existing shorter names retain their spelling.

If a destination exists, extraction tries `-1`, `-2`, and subsequent suffixes,
normally before the extension, while reserving their UTF-8 bytes in the same
255-byte budget. Exclusive file creation prevents an existing payload from being
overwritten if another writer wins a race; the extraction reports an error in
that case. Sanitization and byte limits do not implement all host-specific
filename rules, such as Windows attachment device names or total path limits.

SQLite `original_filename` retains the decoded source filename;
`safe_filename` stores the sanitized base name before collision suffixing.
`storage_path` identifies the actual extracted file. The
`attachment_output_path` helper predicts a base path without creating directories
or checking existing-file collisions; use recorded storage paths to locate files.
