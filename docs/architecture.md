# MBoxer architecture

MBoxer is a local-first Python command-line application. The implementation map
is [PROJECT.md](../PROJECT.md).

## Data flow

An MBOX source belongs to an account. Ingest normalizes message headers and body
text, records labels and thread membership, and optionally extracts attachments.
SQLite stores both the normalized archive and the operational records needed to
resume imports, classify messages, scan bodies, and regenerate exports.

Rule classification runs at message or thread level. Thread assignments are
inherited by their messages. Taxonomy review manages existing category proposals;
the rule classifier does not generate them. LLM classification is not implemented.

Security scanning records regex findings from message bodies. Export projection
resolves an effective classification and content profile, applies configured
redaction, and checks residual findings before publication. JSONL classification
fields are a display option and do not switch off policy resolution.

## Persistence and recovery

The database is built from versioned migrations. A migration and its version
record commit together. Ingest isolates failed message writes with savepoints;
force replacement rolls back source changes if replacement fails. See
[ingest integrity](ingest-integrity.md) and [schema](sqlite-schema.md).

JSONL and NotebookLM process bodies through disk-backed staging. NotebookLM packs
complete rendered content against configured source, word, byte, and message
limits. Dry runs use that same projection and packing calculation. Publication
uses destination-local staging and restores the previous generation on handled
failures. Process termination and power loss are separate recovery limitations;
see [packing and publication](notebooklm-limits.md).

NotebookLM output is grouped by account, category, and year:

```text
exports/notebooklm/<account-key>/<category-path>/<date-band>/<source-pack>.md
```

Manifests and database export records use shared lineage metadata construction.
The metadata includes effective policy, limits, detector descriptors, config
path references, exported-file hashes, and counts, rather than message bodies
or security excerpts.
The source-pack filenames carry category/date context even outside their folders.

## Shared components

Configuration comes from explicit YAML, a legacy local example, or the bundled
`defaults.yaml`. Repeated path resolution is centralized; explicit files do not
inherit bundled rules or taxonomy. The CLI exposes operation-specific overrides.

Shared MIME helpers decode encoded headers and select attachment parts. One
file hashing helper streams SHA-256 for source identity and export lineage.
One redaction rule registry supplies the scanner, scrubber, and manifest's
redaction-switch names. Exporters share classification, projection, findings,
and lineage helpers while retaining their format-specific renderers.

## Scope of current implementation

All delivery is to local files. No upload, external API delivery, LLM service,
web UI, attachment scanner, or malware detector is implemented. The body regex
scanner does not certify metadata or attachments as safe. See
[security behavior](security-roadmap.md) for the exact current profile meanings.
