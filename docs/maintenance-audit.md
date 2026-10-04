# Maintenance audit — 2026-10-03

Original inspected baseline: `dev` at
`aa1b9873baaeb6f0c3a5440c19b41c9a5741271d`. At that inspection, `master`
contained the same source tree and there were no open PRs. All reproductions used
synthetic mail and temporary databases.

Repair status below is refreshed against `master` at `9c214f5`, promoted in
[#27](https://github.com/uscient/mboxer/pull/27). It includes the export,
ingest, consolidation, and review fixes in #22–#26 and #28. The original
findings and measurements remain historical evidence; the limitations at the
end describe the remaining work.

The original suite passed **349 tests**, with **94.33% branch coverage** on
Python 3.12.14. Passing tests did not cover the defects below. This audit is a
dated observation, not an additional source of project policy.

## Original repair groups (completed)

| Area | Original verified gap | Implemented repair |
| --- | --- | --- |
| Verification | Main CI and Bandit ignored PRs into `dev`; schema workflow validated the reference snapshot rather than runtime migrations | CI and Bandit trigger for both branches; `CI gate` aggregates selected lint, tests, and installed-wheel checks; migration tests inspect the runtime-built schema |
| Installation | Default configuration resolved relative to the current directory and was absent from wheels | One bundled default configuration, verified by an installed-wheel smoke check outside the checkout |
| Configuration | Some example settings described unimplemented attachment scans, quarantine, and export controls | Unimplemented security placeholders removed; retained descriptive export metadata labeled explicitly |
| Source identity | The migration-built database enforced globally unique MBOX paths despite account-scoped source lookups | Migration preserves identifiers and permits the same path under different accounts |
| Recovery | Failed migrations could leave partial DDL; failed message writes could leave partial records | Atomic migration/version updates and message savepoints |
| Force ingest | Shrinking a replaced archive retained stale messages; failure could publish a new source hash over old evidence | Transactional source replacement with tested rollback and reclassification |
| Normalization | The UTC field retained original offsets; HTML retention setting was ineffective | Known offsets normalize to UTC and the HTML retention setting is honored |
| Export policy | Disabling JSONL classification metadata also disabled per-message export policies | Policy resolution runs independently of presentation settings |
| Output paths | Arbitrary account keys could become traversal/absolute path components | Unsafe path components are rejected without silently renaming identities |
| JSONL manifests | Removing two suffixes could collide with an output filename or another dated manifest | Only the output's final suffix is replaced |

These repairs merged into `dev` in [#23](https://github.com/uscient/mboxer/pull/23),
[#22](https://github.com/uscient/mboxer/pull/22), and
[#24](https://github.com/uscient/mboxer/pull/24). The table preserves the original
findings rather than describing outstanding defects. Ignored configuration
placeholders were initially labeled and were removed during
[#26](https://github.com/uscient/mboxer/pull/26).

## Measured optimization

SQLite chose account-only indexes for repeated classification and findings
lookups. Additive composite indexes on
`classifications(account_id, message_db_id, classifier_type)`,
`classifications(account_id, thread_key, target_type, classifier_type)` and
`security_findings(account_id, message_db_id)` address the measured lookup cost.

An isolated comparison used three fresh databases per variant, 4,000 synthetic
messages, five messages per thread, roughly 2 KB bodies, and one finding per
message. Median times on the same execution host were:

| Operation | Original indexes | Composite indexes |
| --- | ---: | ---: |
| Thread classification | 1.700 s | 0.086 s |
| Initial scan | 1.033 s | 0.411 s |
| Re-scan | 1.034 s | 0.410 s |
| Already-classified thread check | 3.280 s | 0.0023 s |

Both variants produced 800 classified threads, 4,000 initial findings, and zero
new findings on re-scan. These are workload-specific local measurements, not
performance guarantees. The reusable [benchmark](performance.md) measures a
different, explicitly described corpus with one finding per ten messages.

## Completed follow-ups

[#25](https://github.com/uscient/mboxer/pull/25) subsequently merged the remaining
NotebookLM publication, packing, and body-memory repairs into `dev`:

- Managed generations are staged before publication; prior manifest ownership
  controls stale-pack removal. Handled failures restore previous output.
- Packing counts complete rendered text and UTF-8 bytes and enforces the source
  budget. Dry runs use the same packing calculation.
- JSONL and NotebookLM use disk-backed staging; security scanning iterates body
  rows. [Memory measurements](export-memory.md) document the workload and limits.

[#26](https://github.com/uscient/mboxer/pull/26) consolidated configuration access,
MIME decoding, record projection, lineage metadata, and redaction patterns. It
removed historical agent setup packs, speculative prompts, and unused
configuration scaffolding. AGENTS.md provides navigation and PROJECT.md maps the
implementation.

Review fixes also established the following current behavior:

- **Competing classifications:** one effective row is selected by confidence,
  then explicit-rule precedence. Differing equally ranked winning profiles abort
  export unless a valid explicit profile override resolves the conflict. JSONL
  and NotebookLM use the same resolver. See
  [security behavior](security-roadmap.md#classification-and-profile-selection)
  and [`test_policy_resolution.py`](../tests/test_policy_resolution.py).
- **Ingest recovery:** failed final source checks record failed runs, and
  replacing one source retains restrictive inherited policies on untouched
  messages until successful reclassification. See
  [`test_ingest_review.py`](../tests/test_ingest_review.py).
- **Caller transactions:** failed JSONL export restores its savepoint without
  discarding earlier caller writes; successful export commits the connection.
  NotebookLM dry-run preserves pending caller work. See
  [`test_streaming_export.py`](../tests/test_streaming_export.py) and
  [`test_policy_resolution.py`](../tests/test_policy_resolution.py).
- **Unicode attachments:** [#28](https://github.com/uscient/mboxer/pull/28) limits
  sanitized filename components to 255 UTF-8 bytes and reserves collision-suffix
  space without splitting characters. Long Unicode names no longer make an
  otherwise valid message fail extraction. Attachment and message cleanup still
  runs for interruptions; narrowing those handlers would leave partial evidence.
  See [`test_ingest_attachment_filenames.py`](../tests/test_ingest_attachment_filenames.py)
  and [`test_interrupt_cleanup.py`](../tests/test_interrupt_cleanup.py).

## Remaining limitations

- **Scanning coverage:** body regex detection does not cover sensitive metadata,
  attachments, or malware. `reviewed` does not enforce human-review state. The
  [security capability gaps](security-roadmap.md#possible-future-capabilities)
  are proposals, not implemented controls.
- **Export metadata:** dedicated lineage fields are sanitized, but account labels
  and configuration snapshots can retain sensitive values or paths. Body
  redaction does not cover those fields.
- **Recovery boundaries:** handled errors are tested, but process termination,
  power loss, and concurrent publication need the operational care described in
  [publication behavior](notebooklm-limits.md).
- **Archive scaling:** staging trades temporary disk and I/O for lower body
  memory use. The largest message, thread processing, and configured source
  budget still matter; the measured workloads do not prove all archives fit.
- **Release administration:** source inspection does not verify environment
  reviewers, signed-tag policy, or PyPI Trusted Publisher settings.
- **Check enforcement:** workflow definitions do not establish branch-protection
  requirements. `CI gate` covers its selected lint, test, and package jobs; the
  separate Bandit workflow uses `exit_zero: true` and is not a blocking security
  findings gate.
