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

## Future scan checks

Message checks:

- email addresses
- phone numbers
- SSN-like values
- credit-card-like values
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
