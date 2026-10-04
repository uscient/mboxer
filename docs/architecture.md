# MBoxer architecture

MBoxer is a local-first Python command-line application. The implementation map
is [PROJECT.md](../PROJECT.md).

## Data flow

New MBOX ingestion uses an account and a resolved source path. Ingest normalizes
message headers and body text, records labels and per-source thread summaries,
and optionally extracts attachments. SQLite stores the normalized archive and
operational records needed to resume imports, classify messages, scan bodies,
and regenerate exports. Migrated legacy evidence may retain NULL account IDs.

Rule classification reads YAML rules and runs at message or thread level. The
CLI resolves one account per classification command. Account-scoped thread
classification combines messages sharing a thread key across that account's
sources, then inherits its assignment to messages unless an explicit message rule
has equal or greater confidence. Its participant summary comes from the messages,
not the stored per-source thread summary. Taxonomy review manages existing
category proposals; the rule classifier neither generates proposals nor requires
assigned category paths to have been approved. LLM classification is not
implemented.

Security scanning records regex findings from message bodies. Export projection
resolves an effective classification and content profile, applies configured
body redaction, and checks residual body findings before publication. Selection
uses the greatest numeric confidence, then favors explicit message rules over
inheritance. Equally ranked rows with incompatible effective export profiles
block export unless an explicit profile override resolves the conflict. JSONL
classification fields are a display option and do not switch off policy
resolution. Profile and residual-findings behavior is described in
[security behavior](security-roadmap.md).

## Persistence and recovery

The database is built from versioned migrations. A migration and its version
record commit together. Ingest isolates failed message writes with savepoints;
force replacement rolls back message changes if replacement fails, while
registration and run-history rows can remain. See
[ingest integrity](ingest-integrity.md) and [schema](sqlite-schema.md).

JSONL and NotebookLM stage projected output on disk; NotebookLM also uses a
temporary SQLite spool for grouping. This avoids retaining the entire archive's
body text in Python memory, but still needs temporary disk capacity, per-record
memory, and per-output bookkeeping. Ingest and classification have separate
memory costs; the application as a whole is not a constant-memory pipeline.

NotebookLM packs complete rendered content against configured source, word,
byte, and message limits. Its dry runs use that same projection and packing
calculation. Publication first copies staged files beside the destination so it
can publish across filesystems. Destination locks prevent cooperating publishers
from overlapping. Handled failures restore previous files; failure during
recovery retains a backup and lock for inspection. Abrupt process termination and
power loss are separate recovery limitations; see
[packing and publication](notebooklm-limits.md).

NotebookLM output is grouped by account, category, and UTC year, using `undated`
when no normalized date is available:

```text
exports/notebooklm/<account-key>/<category-path>/<date-band>/<source-pack>.md
```

NotebookLM publication validates its previous manifest and ownership marker,
removes obsolete owned packs, and preserves unrelated files. JSONL publication
replaces its explicitly selected output and sidecar manifest; it does not use the
NotebookLM ownership inventory.

Manifests and database export records use shared lineage metadata construction.
The metadata includes effective policy, limits, detector descriptors, config
path references, exported-file hashes, and counts, rather than message bodies
or security excerpts. Local operational database rows can retain full paths.
Current `export_items` rows describe output files, not every file's constituent
message IDs. The source-pack filenames carry category/date context even outside
their folders.

## Shared components

Configuration comes from explicit YAML, a legacy local example, or the bundled
`defaults.yaml`. Repeated path resolution and selected scalar defaults are
centralized; explicit files do not inherit bundled rules, taxonomy, or limit
profile dictionaries. The CLI exposes operation-specific overrides. See
[configuration](configuration.md) for precedence, active settings, and fields
retained only as descriptive metadata.

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
