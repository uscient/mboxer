Add the smallest useful neutral producer-event seam for mboxer, without connecting to an external custody system.

Requirements:

- Do not add network calls.
- Do not invent a final external API/import boundary.
- Keep mboxer independent.
- Prefer a neutral module name like `events`, `activity`, `audit`, or `producer`.
- Events should be append-oriented descriptions of local operations, not mutable state.
- Use JSON-serializable payloads.
- Do not include sensitive raw body content by default.
- Add tests.
- Watch for instruction-surface changes and report them.

Inspect operational evidence around ingest runs, classifications, category review, security findings, exports, and manifests before implementing.

End with:

- What seam you added and why.
- Files changed.
- Tests run.
- Why this does not couple mboxer to any external system.
- Later abstraction opportunities.
- Instruction-surface changes.
