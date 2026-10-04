# Security behavior and remaining work

MBoxer uses deterministic body-text regex detection and configurable redaction.
It does not scan attachments, detect malware, or establish that an archive or
export is free of sensitive information.

## Current export profiles

| Profile | Current behavior |
| --- | --- |
| `raw` | Retains body text. Files are local, but no upload restriction is enforced. |
| `reviewed` | Uses the same scrubbing path as `scrubbed`; no human-review state is checked. |
| `scrubbed` | Applies the enabled regex redactions to body text. |
| `metadata-only` | Drops body text and retains message metadata. |
| `exclude` | Omits the message. |

The effective classification is resolved before presentation settings are
applied. Competing classifications prefer the most restrictive valid export
profile; JSONL's `include_classification` only controls displayed fields.
See the [command reference](../README.md#export-content-profiles---export-profile)
for run-level overrides.

## Detection and scrubbing

`security/patterns.py` defines each active pattern, finding type, redaction switch,
and replacement text. The detector registry and scrubber consume those same
rules for email addresses, phone numbers, SSN-like values, and credit-card-like
values. Disabling a redaction does not remove the detector from residual scans.

`security-scan` stores body findings in `security_findings`. Export projection
scrubs bodies when requested, then the residual gate scans the projected body.
Headers, subjects, recipients, and attachment names can still contain sensitive
information. Counts and detector descriptions in manifests are not a safety
certification.

## Residual findings gate

`security.on_residual_findings` (or `--findings-policy`) selects:

- `allow`: publish the export and record residual counts.
- `warn`: publish, record counts, and emit a counts-only warning.
- `block`: abort before publishing files or export ledger rows if findings remain.

The default is `warn`. Temporary staging can be created before a block; it is
cleaned up on handled failure. Existing outputs are preserved. Recovery limits
are described in [packing and publication](notebooklm-limits.md).

## Unimplemented capabilities

Attachment scanning/quarantine, credential detection, semantic medical/legal
classification, physical-address redaction, and human-review gating are not
implemented. Old placeholder YAML keys have been removed from the bundled
example. These capabilities would need implementation and behavioral tests;
setting an old placeholder key does not enable them.
