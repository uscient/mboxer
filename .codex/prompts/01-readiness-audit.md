# mboxer readiness audit

You are working in the `mboxer` repo.

Goal: inspect the current repo and produce a readiness map for making `mboxer` a strong future safe-projection producer for configured external destinations, without implementing external custody/API integration yet.

Constraints:

- Do not modify files.
- Do not redesign the app.
- Do not add external service dependencies.
- Do not invent an external intake API.
- Do not make broad speculative recommendations without tying them to current code.
- Treat `mboxer` as a local-first email archive processor whose job is to ingest Gmail/Takeout MBOX archives, normalize emails, store durable SQLite evidence, classify, scan/scrub, and export NotebookLM/JSONL packs.
- Watch for instruction-surface files: `AGENTS.md`, `CLAUDE.md`, `.codex/`, `.claude/`, `.agents/`, hooks, rules, skills, prompts, MCP config, and related files. Report anything discovered.

Tasks:

1. Run `git status --short`.
2. Inspect CLI, schema, migrations, ingest, normalize, classify, taxonomy, security, exporters, manifests, config, and tests.
3. Identify the strongest existing producer/evidence seams.
4. Identify missing readiness pieces for future append-only event emission.
5. Identify fragile areas where future external API/import integration could cause drift or coupling.
6. Identify test gaps that should be closed before adding any external integration.
7. Recommend a PR-sized implementation sequence, ordered by safety and value.

Output only:

- Summary of what you inspected.
- Current readiness assessment.
- Top gaps.
- Recommended PR-sized tasks.
- Files likely involved.
- Risks / cautions.
- Any instruction-surface files discovered or changed.
