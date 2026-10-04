# Security behavior and remaining work

MBoxer uses deterministic body-text regex detection and configurable redaction.
It does not scan attachments, detect malware, or establish that an archive or
export is free of sensitive information.

## Current export profiles

| Profile | Current behavior |
| --- | --- |
| `raw` | Retains body text; the residual findings policy still applies. |
| `reviewed` | Uses the same scrubbing path as `scrubbed`; no human-review state is checked. |
| `scrubbed` | Applies enabled regex redactions to body text when `security.scrub_enabled` is true. |
| `metadata-only` | Drops body text and retains message metadata. |
| `exclude` | Omits the message. |

All exports are local files; MBoxer does not upload them or enforce how they are
subsequently shared. A profile name alone does not certify an export as safe.

## Classification and profile selection

Both exporters resolve one effective classification for each message before
applying presentation settings. Only classifications belonging to that message's
account participate. Selection follows
[`resolve_message_classification`](../src/mboxer/exporters/classification.py):

1. Highest numeric confidence wins. Missing confidence ranks below every numeric
   confidence; nonnumeric or non-finite confidence aborts export.
2. At equal confidence, explicit `rule` and `rule_hint` classifications outrank
   other classifier types, including inherited classifications.
3. Equally ranked winning rows must agree on the effective export profile.
   Compatible ties retain the oldest row's metadata and export the message once.
4. Conflicting winning profiles abort before publication, preserving prior
   output and export history. Resolve the classification evidence or supply an
   explicit run-level `--export-profile`.

Profile selection uses the explicit override, then the selected classification's
profile, then `security.default_export_profile`. Invalid stored profiles fall
back to the configured default; a missing or invalid configured default uses
`scrubbed`. A valid explicit override applies to every candidate message, including
messages classified `exclude`, and can resolve a tied-policy conflict. It does
not bypass confidence validation or the residual findings policy.

JSONL's `include_classification` controls displayed fields only. Regression tests
cover both settings and NotebookLM in
[`test_policy_resolution.py`](../tests/test_policy_resolution.py). See the
[content profiles](../README.md#content-profiles-and-security) for
profile overrides.

## Detection and scrubbing

[`security/patterns.py`](../src/mboxer/security/patterns.py) defines each active
pattern, finding type, redaction switch, and replacement text. The detector
registry and scrubber consume those same rules for email addresses, phone
numbers, SSN-like values, and credit-card-like values.

The bundled configuration enables all four redaction switches. Explicit
configuration files are independent: omitted redaction switches are disabled.
`security.scrub_enabled: false` disables body redaction even for `scrubbed` and
`reviewed` profiles. Disabling redaction does not remove detectors from residual
scans. Pattern matches are heuristic; the number patterns do not validate an
identity or a card number.

`security-scan` stores body findings in `security_findings`. Export projection
scrubs bodies when requested, then the residual gate scans the projected body.
These are separate operations: `security.scan_enabled: false` disables the
standalone stored scan, but does not disable export residual assessment. Stored
findings include the first matched excerpt per message and detector/finding type and can
therefore contain sensitive values; repeated scans avoid adding identical rows.
Headers, subjects, recipients, and attachment names can still contain sensitive
information. They are outside the body redaction and residual scan. Manifests
and export-run metadata record counts and detector descriptions, without copying
the stored finding excerpts. Those summaries are not a safety certification.
Export metadata also retains account labels and configuration values, including
the JSONL format configuration. Dedicated lineage path fields are sanitized, but
arbitrary metadata and embedded configuration paths are not redacted.

## Residual findings gate

`security.on_residual_findings` (or `--findings-policy`) selects:

- `allow`: publish the export and record residual counts.
- `warn`: publish, record counts, and emit a counts-only warning.
- `block`: abort before publishing files or export ledger rows if findings remain.

The default is `warn`. Temporary staging can be created before a block; it is
cleaned up on handled failure. Existing outputs are preserved. Recovery limits
are described in [packing and publication](notebooklm-limits.md). Profile
projection and counts-only residual warnings are covered by
[`test_scrub_export.py`](../tests/test_scrub_export.py) and
[`test_findings_gate.py`](../tests/test_findings_gate.py).

## Possible future capabilities

Attachment scanning/quarantine, credential detection, semantic medical/legal
classification, physical-address redaction, and human-review gating are not
implemented. Old placeholder YAML keys have been removed from the bundled
example. These capabilities would need implementation and behavioral tests;
setting an old placeholder key does not enable them. This list describes gaps,
not a committed implementation schedule.
