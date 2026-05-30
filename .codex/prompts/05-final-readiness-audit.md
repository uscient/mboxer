# mboxer final external intake readiness audit

You are working in the `mboxer` repo.

Goal: perform a final no-code readiness audit after the manifest, event seam, and security/export boundary work is complete.

Constraints:

- Do not modify files.
- Do not invent an external intake API.
- Do not recommend broad rewrites unless there is a concrete blocker.
- Separate proven code behavior from recommendations.
- Watch for instruction-surface files and report them explicitly.

Tasks:

1. Run `git status --short`.
2. Inspect the current repo state.
3. Confirm whether `mboxer` is ready to produce safe projections for a configured external destination once an API/import boundary exists.
4. Identify remaining blockers vs nice-to-have improvements.
5. Draft a concrete future external API/import adapter plan that keeps `mboxer` independent.
6. Identify the safest first integration PR once an external intake endpoint is available.

Output:

- Readiness verdict.
- Evidence supporting the verdict.
- Blockers, if any.
- Nice-to-have improvements.
- Future adapter plan.
- First integration PR recommendation.
- Tests or checks run.
- Instruction-surface changes.
