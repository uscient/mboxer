Harden mboxer export manifest and lineage behavior without adding uScientDB integration.

Requirements:

- Keep changes PR-sized.
- Do not add network calls or uScientDB dependencies.
- Prefer additive manifest fields and tests.
- Do not include raw sensitive body content in manifests.
- Inspect `src/mboxer/exporters/manifest.py`, NotebookLM exporter, JSONL exporter, export schema usage, config export profile behavior, and export/manifest tests.
- Preserve current CLI behavior unless a test proves a bug.
- Watch for instruction-surface changes and report them.

Desired outcome:

Manifests should better record export type, account, source DB/config context where available, export profile, scrub/security posture, category path, generated files, item counts, splitting/limits behavior, and timestamps.

Run targeted tests and broader tests if feasible.

End with the standard task report from `AGENTS.md`.
