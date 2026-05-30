# mboxer security and export boundary audit

You are working in the `mboxer` repo.

Goal: audit and, if safe, tighten tests around scan/scrub/export boundary behavior before mboxer becomes a future safe-projection producer for configured external custody systems.

Constraints:

- Keep changes PR-sized.
- Do not claim full DLP or semantic PII detection.
- Do not inspect real user archives.
- Do not add external services.
- Do not change export profile semantics without tests and explicit rationale.
- Watch for instruction-surface changes and report them explicitly.

Inspect:

- `src/mboxer/security/scan.py`
- `src/mboxer/security/scrub.py`
- `src/mboxer/security/policy.py`
- NotebookLM exporter
- JSONL exporter
- manifest behavior
- tests for scan/scrub/export profiles
- config defaults around cloud-style exports

Focus questions:

1. Are `raw`, `reviewed`, `scrubbed`, `metadata-only`, and `exclude` behavior clear and tested?
2. Can exported files accidentally include raw body text when a safer profile is expected?
3. Do manifests avoid sensitive raw body content?
4. Are security findings represented clearly without overstating scanner capability?
5. Are attachments excluded, referenced, or represented safely in exports?

Implement only focused fixes/tests where there is clear evidence of a gap.

Output:

- What you inspected.
- Findings.
- Files changed.
- Tests run.
- Remaining risks.
- Recommended next step.
- Instruction-surface changes.
