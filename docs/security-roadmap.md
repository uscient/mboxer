# Security and Scrubbing Roadmap

`mboxer` should leave room for careful security checks before export.

## Export profiles

```text
raw
  Full body text and metadata. Local use only.

reviewed
  Full text, but only messages approved for export.

scrubbed
  Redacted sensitive patterns according to policy.

metadata-only
  Headers, dates, senders, subjects, attachment names, and summaries only.

exclude
  Do not export.
```

## Current scan checks

Message checks:

- email addresses
- phone numbers
- SSN-like values
- credit-card-like values

## Future scan checks

Reserved message detector names, not active claims:

- postal addresses
- medical terms
- legal terms
- financial account-like values
- password / credential leakage hints

Attachment checks:

- unsafe extension
- macro-capable Office file
- executable/archive file
- encrypted file
- oversized file
- unknown MIME type

## Recommended default

The default cloud-oriented NotebookLM export should be `scrubbed` or `reviewed`, not `raw`.

Raw exports are acceptable only for local-only workflows.

## Database support

Security findings should be stored, not just logged, so exports can be filtered and regenerated later.

The `security_findings` table should record:

- finding type
- severity
- message id or attachment id
- detector name
- excerpt or metadata
- review status
- created timestamp

Implemented export support:

- exports can be flagged with residual finding counts by type
- exports can warn or block when projected export text still contains detected-sensitive items
- export manifests and run metadata record residual counts, policy, and detector descriptors

## Residual export gate

`on_residual_findings` controls what happens after a record is projected for export and the
projected body text is scanned again:

- `allow`: write the export and record residual counts in manifest metadata
- `warn`: write the export, record residual counts, and emit a counts-only warning
- `block`: abort before export files or export rows are written when residual counts are non-empty

The default is `warn`.

The scanner runs through a deterministic in-process detector registry. The active registry currently
contains regex detectors for email addresses, phone numbers, SSN-like values, and credit-card-like
values. Physical-address, medical, legal, financial-account, and credential detectors are reserved
future names, not active detection or scrubbing claims.
