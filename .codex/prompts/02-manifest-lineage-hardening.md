# mboxer manifest and lineage hardening

You are working in the `mboxer` repo.

Goal: harden existing export manifest and lineage behavior so future external systems can understand what was produced, from what inputs, under what config/policy, without adding external custody/API integration yet.

Constraints:

- Keep changes PR-sized.
- Do not add external service dependencies.
- Do not invent a network client.
- Preserve current CLI behavior unless a test proves a bug.
- Do not mutate existing historical data unexpectedly.
- Prefer additive manifest fields and tests.
- Do not include raw sensitive body content in manifests.
- Watch for instruction-surface changes and report them explicitly.

Inspect first:

- `src/mboxer/exporters/manifest.py`
- NotebookLM exporter
- JSONL exporter
- `exports` / `export_items` schema usage
- config paths and export profile behavior
- tests around manifests and exports

Desired direction:

- Manifest should clearly record export type, account, source DB/config context where available, export profile, scrub/security posture, category path, generated files, item counts, limits/splitting behavior, and timestamps.
- Keep enough information for a future external API/import adapter to emit an append-only handoff record about the export.
- Add or strengthen tests.

Before final report, run targeted tests and then broader tests if feasible.

Output:

- Summary of inspection.
- Files changed.
- Tests added/updated.
- Exact behavior changes.
- Limitations left intentionally unresolved.
- Abstraction seams noticed for later integration.
- Instruction-surface changes.
