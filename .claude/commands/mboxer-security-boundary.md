Audit mboxer security and export boundary behavior.

Requirements:

- Keep changes PR-sized.
- Do not inspect real user archives.
- Do not add external services.
- Do not claim full DLP or semantic PII detection.
- Do not change export profile semantics without tests and explicit rationale.
- Watch for instruction-surface changes and report them.

Inspect security scan, scrub, policy, NotebookLM export, JSONL export, manifest behavior, tests, and config defaults.

Focus on whether `raw`, `reviewed`, `scrubbed`, `metadata-only`, and `exclude` are clear and tested; whether exports can leak raw body text under safer profiles; whether manifests avoid sensitive raw body content; and whether attachments are handled safely.

Implement only focused fixes/tests where there is clear evidence of a gap.

End with the standard task report from `AGENTS.md`.
