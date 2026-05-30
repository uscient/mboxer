Perform a final no-code readiness audit for mboxer before uScientDB integration.

Requirements:

- Do not modify files.
- Do not invent the uScientDB API.
- Separate proven behavior from recommendations.
- Run `git status --short` first.
- Inspect current repo state.
- Confirm whether mboxer is ready to become a uScientDB producer once a server API exists.
- Identify blockers versus nice-to-have improvements.
- Draft a concrete future adapter plan that keeps mboxer independent.
- Identify the safest first integration PR once uScientDB is available.
- Watch for instruction-surface changes and report them.

End with:

- Readiness verdict.
- Evidence supporting the verdict.
- Blockers.
- Nice-to-have improvements.
- Future adapter plan.
- First integration PR recommendation.
- Tests/checks run.
- Instruction-surface findings.
