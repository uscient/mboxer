Perform a no-code readiness audit for `mboxer` as a future uScientDB producer.

Requirements:

- Do not modify files.
- Run `git status --short` first.
- Inspect CLI, schema, migrations, ingest, normalize, classify, taxonomy, security, exporters, manifests, config, and tests.
- Identify existing evidence/producer seams.
- Identify missing readiness pieces for append-only event emission.
- Identify fragile coupling risks.
- Identify test gaps.
- Watch for instruction-surface files: `AGENTS.md`, `CLAUDE.md`, `.codex/`, `.claude/`, `.agents/`, hooks, rules, skills, prompts, MCP config, and related files.

End with:

- Current readiness assessment.
- Top gaps.
- PR-sized tasks in recommended order.
- Files likely involved.
- Risks / cautions.
- Instruction-surface findings.
